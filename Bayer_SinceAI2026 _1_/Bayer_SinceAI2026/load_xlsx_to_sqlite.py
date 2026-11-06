#!/usr/bin/env python3
"""Load the Bayer Pharmaceuticals x Since AI 2026 builder data pack (.xlsx) into SQLite.

Pure standard library (zipfile + ElementTree + sqlite3) - no pandas/openpyxl required.

What it does:
  * one SQLite table per tabular worksheet (header row -> column names)
  * type inference: INTEGER / REAL / TEXT; empty cells -> NULL
  * Excel serial dates converted to ISO 'YYYY-MM-DD' text
  * primary keys applied where candidate values prove unique (verified, not assumed)
  * indexes on common join columns
  * five convenience views for analysis
  * post-load validation: row counts vs Package_Overview + orphan referential checks

Run:  python3 load_xlsx_to_sqlite.py
Re-running is safe: existing tables/views are dropped and rebuilt.
"""

import html
import re
import sqlite3
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
XLSX = HERE / "Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx"
DB = HERE / "bayer_sinceai.db"

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

EXCEL_EPOCH = date(1899, 12, 30)  # Excel serial 0
SERIAL_MIN, SERIAL_MAX = 20000, 80000  # plausible date serials (1954 .. 2118)

# Documentation sheets are rendered into DATA_PACK_README.md, not loaded as tables.
DOC_SHEETS = {"START_HERE", "Package_Overview"}

# (sheet, column) pairs that hold Excel serial dates -> converted to ISO text.
DATE_COLUMNS = {
    ("Analytics_Assets", "created_date"),
    ("Analytics_Assets", "last_modified"),
    ("Asset_Usage", "month"),
    ("Product_Market_Monthly", "month"),
    ("Launch_Milestones", "milestone_date"),
    ("Business_Requests", "request_date"),
    ("Change_Log", "date"),
}

# Candidate primary keys per sheet; applied only if values prove unique at load time.
PK_CANDIDATES = {
    "Products": ["product_id"],
    "Markets": ["market_id"],
    "Owners": ["owner_id"],
    "KPI_Catalog": ["kpi_id"],
    "Workspaces": ["workspace_id"],
    "Semantic_Models": ["model_id"],
    "Analytics_Assets": ["asset_id"],
    "Asset_KPI_Map": ["asset_id", "kpi_id"],
    "Asset_Usage": ["asset_id", "month"],
    "Lineage_Edges": ["source_id", "target_id", "edge_type"],
    "Product_Market_Monthly": ["product_id", "market_id", "month"],
    "Launch_Milestones": ["milestone_id"],
    "Market_Access": ["product_id", "market_id"],
    "Supply_Operations": ["product_id", "market_id"],
    "Data_Quality": ["issue_id"],
    "Governance_Signals": ["signal_id"],
    "Migration_Backlog": ["source_asset_id"],
    "Business_Requests": ["request_id"],
    "Governance_Rules": ["rule_id"],
    "Data_Dictionary": ["sheet", "field"],
    "Change_Log": ["version"],
}

# Join columns that get an index in every table where they appear.
INDEX_COLUMNS = {
    "asset_id", "kpi_id", "model_id", "owner_id", "workspace_id",
    "product_id", "market_id", "source_id", "target_id", "record_id",
}

# Data-row counts per sheet (matches Package_Overview metrics).
EXPECTED_COUNTS = {
    "Public_References": 6,
    "Products": 7,
    "Markets": 14,
    "Owners": 60,
    "KPI_Catalog": 56,
    "Workspaces": 16,
    "Semantic_Models": 75,
    "Analytics_Assets": 360,
    "Asset_KPI_Map": 1454,
    "Asset_Usage": 3600,
    "Lineage_Edges": 438,
    "Product_Market_Monthly": 980,
    "Launch_Milestones": 35,
    "Market_Access": 98,
    "Supply_Operations": 98,
    "Data_Quality": 147,
    "Governance_Signals": 410,
    "Migration_Backlog": 94,
    "Business_Requests": 150,
    "Governance_Rules": 8,
    "Data_Dictionary": 13,
    "Change_Log": 1,
}

VIEWS = {
    "v_asset_monthly": """
        CREATE VIEW v_asset_monthly AS
        SELECT
          a.asset_id, a.asset_name, a.asset_type, a.platform,
          a.product_scope, a.market_scope, a.lifecycle_status,
          a.endorsement AS asset_endorsement, a.classification, a.delivery_model,
          a.estimated_audience, a.created_date, a.last_modified,
          a.owner_id, o.owner_name, o.role AS owner_role,
          o.status AS owner_status, o.scope AS owner_scope,
          a.workspace_id, w.workspace_name, w.environment AS workspace_environment,
          w.governance_mode AS workspace_governance_mode, w.platform AS workspace_platform,
          a.model_id, sm.model_name, sm.model_type, sm.endorsement AS model_endorsement,
          sm.refresh_frequency AS model_refresh_frequency,
          sm.refresh_status AS model_refresh_status,
          sm.ai_readiness AS model_ai_readiness,
          sm.ai_issue_pattern AS model_ai_issue_pattern,
          u.month, u.views, u.unique_users, u.exports, u.subscriptions,
          u.avg_load_ms, u.query_errors
        FROM Analytics_Assets a
        LEFT JOIN Asset_Usage u ON u.asset_id = a.asset_id
        LEFT JOIN Owners o ON o.owner_id = a.owner_id
        LEFT JOIN Workspaces w ON w.workspace_id = a.workspace_id
        LEFT JOIN Semantic_Models sm ON sm.model_id = a.model_id
    """,
    "v_governance": """
        CREATE VIEW v_governance AS
        SELECT
          g.signal_id, g.signal_code, g.severity, g.status AS signal_status,
          g.detected_by,
          a.asset_id, a.asset_name, a.asset_type, a.platform, a.lifecycle_status,
          a.endorsement AS asset_endorsement, a.estimated_audience,
          a.product_scope AS asset_product_scope, a.market_scope AS asset_market_scope,
          a.owner_id, o.owner_name, o.role AS owner_role, o.status AS owner_status,
          a.workspace_id, w.workspace_name
        FROM Governance_Signals g
        LEFT JOIN Analytics_Assets a ON a.asset_id = g.asset_id
        LEFT JOIN Owners o ON o.owner_id = a.owner_id
        LEFT JOIN Workspaces w ON w.workspace_id = a.workspace_id
    """,
    "v_migration": """
        CREATE VIEW v_migration AS
        SELECT
          mb.source_asset_id, mb.recommended_path_candidate, mb.complexity,
          mb.status AS backlog_status, mb.synthetic_reason,
          mb.candidate_target_model_id, tsm.model_name AS target_model_name,
          tsm.endorsement AS target_model_endorsement,
          tsm.ai_readiness AS target_model_ai_readiness,
          a.asset_name, a.asset_type, a.platform, a.lifecycle_status,
          a.endorsement AS asset_endorsement, a.estimated_audience,
          a.product_scope AS asset_product_scope, a.market_scope AS asset_market_scope,
          a.owner_id, o.owner_name, a.workspace_id, w.workspace_name,
          COALESCE(usage.total_views, 0) AS total_views_all_months,
          COALESCE(usage.months_with_usage, 0) AS months_with_usage,
          COALESCE(usage.max_monthly_unique_users, 0) AS max_monthly_unique_users
        FROM Migration_Backlog mb
        LEFT JOIN Analytics_Assets a ON a.asset_id = mb.source_asset_id
        LEFT JOIN Semantic_Models tsm ON tsm.model_id = mb.candidate_target_model_id
        LEFT JOIN Owners o ON o.owner_id = a.owner_id
        LEFT JOIN Workspaces w ON w.workspace_id = a.workspace_id
        LEFT JOIN (
          SELECT asset_id, SUM(views) AS total_views, COUNT(*) AS months_with_usage,
                 MAX(unique_users) AS max_monthly_unique_users
          FROM Asset_Usage
          GROUP BY asset_id
        ) usage ON usage.asset_id = mb.source_asset_id
    """,
    "v_product_monthly": """
        CREATE VIEW v_product_monthly AS
        SELECT
          pm.product_id, p.product_name, p.therapeutic_area, p.portfolio_stage,
          pm.market_id, mk.market_name, mk.region, mk.market_maturity,
          mk.regulatory_complexity,
          pm.month, pm.value_type, pm.net_sales_m_eur_syn, pm.forecast_m_eur_syn,
          pm.units_shipped_syn, pm.forecast_variance_pct,
          pm.market_access_coverage_pct_syn, pm.otif_pct_syn, pm.inventory_weeks_syn
        FROM Product_Market_Monthly pm
        JOIN Products p ON p.product_id = pm.product_id
        JOIN Markets mk ON mk.market_id = pm.market_id
    """,
    "v_kpi_conflicts": """
        CREATE VIEW v_kpi_conflicts AS
        SELECT
          k.canonical_metric, COUNT(*) AS variant_count,
          GROUP_CONCAT(k.kpi_id || ' - ' || k.kpi_name, ' | ') AS variants,
          SUM(CASE WHEN k.definition_status = 'canonical' THEN 1 ELSE 0 END)
            AS canonical_variants,
          SUM(CASE WHEN k.approval_status = 'approved' THEN 1 ELSE 0 END)
            AS approved_variants
        FROM KPI_Catalog k
        GROUP BY k.canonical_metric
        HAVING COUNT(*) > 1
    """,
}

# Informational orphan checks (the data is intentionally messy; orphans are reported,
# not rejected).
ORPHAN_CHECKS = [
    ("Analytics_Assets.model_id -> Semantic_Models",
     "SELECT COUNT(*) FROM Analytics_Assets a LEFT JOIN Semantic_Models s"
     " ON s.model_id = a.model_id"
     " WHERE a.model_id IS NOT NULL AND s.model_id IS NULL"),
    ("Analytics_Assets.owner_id -> Owners",
     "SELECT COUNT(*) FROM Analytics_Assets a LEFT JOIN Owners o"
     " ON o.owner_id = a.owner_id"
     " WHERE a.owner_id IS NOT NULL AND o.owner_id IS NULL"),
    ("Analytics_Assets.workspace_id -> Workspaces",
     "SELECT COUNT(*) FROM Analytics_Assets a LEFT JOIN Workspaces w"
     " ON w.workspace_id = a.workspace_id"
     " WHERE a.workspace_id IS NOT NULL AND w.workspace_id IS NULL"),
    ("Semantic_Models.owner_id -> Owners",
     "SELECT COUNT(*) FROM Semantic_Models s LEFT JOIN Owners o"
     " ON o.owner_id = s.owner_id"
     " WHERE s.owner_id IS NOT NULL AND o.owner_id IS NULL"),
    ("Semantic_Models.workspace_id -> Workspaces",
     "SELECT COUNT(*) FROM Semantic_Models s LEFT JOIN Workspaces w"
     " ON w.workspace_id = s.workspace_id"
     " WHERE s.workspace_id IS NOT NULL AND w.workspace_id IS NULL"),
    ("KPI_Catalog.owner_id -> Owners",
     "SELECT COUNT(*) FROM KPI_Catalog k LEFT JOIN Owners o"
     " ON o.owner_id = k.owner_id"
     " WHERE k.owner_id IS NOT NULL AND o.owner_id IS NULL"),
    ("Asset_Usage.asset_id -> Analytics_Assets",
     "SELECT COUNT(*) FROM Asset_Usage u LEFT JOIN Analytics_Assets a"
     " ON a.asset_id = u.asset_id WHERE a.asset_id IS NULL"),
    ("Asset_KPI_Map.asset_id -> Analytics_Assets",
     "SELECT COUNT(*) FROM Asset_KPI_Map m LEFT JOIN Analytics_Assets a"
     " ON a.asset_id = m.asset_id WHERE a.asset_id IS NULL"),
    ("Asset_KPI_Map.kpi_id -> KPI_Catalog",
     "SELECT COUNT(*) FROM Asset_KPI_Map m LEFT JOIN KPI_Catalog k"
     " ON k.kpi_id = m.kpi_id WHERE k.kpi_id IS NULL"),
    ("Lineage_Edges.source_id not in Semantic_Models/Analytics_Assets",
     "SELECT COUNT(*) FROM Lineage_Edges e WHERE e.source_id IS NOT NULL"
     " AND e.source_id NOT IN (SELECT model_id FROM Semantic_Models"
     " UNION SELECT asset_id FROM Analytics_Assets)"),
    ("Lineage_Edges.target_id not in Semantic_Models/Analytics_Assets",
     "SELECT COUNT(*) FROM Lineage_Edges e WHERE e.target_id IS NOT NULL"
     " AND e.target_id NOT IN (SELECT model_id FROM Semantic_Models"
     " UNION SELECT asset_id FROM Analytics_Assets)"),
    ("Governance_Signals.asset_id -> Analytics_Assets",
     "SELECT COUNT(*) FROM Governance_Signals g LEFT JOIN Analytics_Assets a"
     " ON a.asset_id = g.asset_id WHERE a.asset_id IS NULL"),
    ("Migration_Backlog.source_asset_id -> Analytics_Assets",
     "SELECT COUNT(*) FROM Migration_Backlog mb LEFT JOIN Analytics_Assets a"
     " ON a.asset_id = mb.source_asset_id WHERE a.asset_id IS NULL"),
    ("Migration_Backlog.candidate_target_model_id -> Semantic_Models",
     "SELECT COUNT(*) FROM Migration_Backlog mb LEFT JOIN Semantic_Models s"
     " ON s.model_id = mb.candidate_target_model_id"
     " WHERE mb.candidate_target_model_id IS NOT NULL AND s.model_id IS NULL"),
    ("Product_Market_Monthly.product_id -> Products",
     "SELECT COUNT(*) FROM Product_Market_Monthly pm LEFT JOIN Products p"
     " ON p.product_id = pm.product_id WHERE p.product_id IS NULL"),
    ("Product_Market_Monthly.market_id -> Markets",
     "SELECT COUNT(*) FROM Product_Market_Monthly pm LEFT JOIN Markets mk"
     " ON mk.market_id = pm.market_id WHERE mk.market_id IS NULL"),
    ("Launch_Milestones.product_id -> Products",
     "SELECT COUNT(*) FROM Launch_Milestones lm LEFT JOIN Products p"
     " ON p.product_id = lm.product_id WHERE p.product_id IS NULL"),
    ("Launch_Milestones.market_id -> Markets",
     "SELECT COUNT(*) FROM Launch_Milestones lm LEFT JOIN Markets mk"
     " ON mk.market_id = lm.market_id WHERE mk.market_id IS NULL"),
    ("Market_Access.product_id -> Products",
     "SELECT COUNT(*) FROM Market_Access ma LEFT JOIN Products p"
     " ON p.product_id = ma.product_id WHERE p.product_id IS NULL"),
    ("Market_Access.market_id -> Markets",
     "SELECT COUNT(*) FROM Market_Access ma LEFT JOIN Markets mk"
     " ON mk.market_id = ma.market_id WHERE mk.market_id IS NULL"),
    ("Supply_Operations.product_id -> Products",
     "SELECT COUNT(*) FROM Supply_Operations so LEFT JOIN Products p"
     " ON p.product_id = so.product_id WHERE p.product_id IS NULL"),
    ("Supply_Operations.market_id -> Markets",
     "SELECT COUNT(*) FROM Supply_Operations so LEFT JOIN Markets mk"
     " ON mk.market_id = so.market_id WHERE mk.market_id IS NULL"),
]

INT_RE = re.compile(r"^[+-]?\d+$")
NUM_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
SERIAL_RE = re.compile(r"^\d+(?:\.\d+)?$")


def read_workbook(path):
    """Parse the .xlsx and return {sheet_name: row_matrix} (raw cell strings)."""
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.get("Id"): rel.get("Target") for rel in rels}

    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{M}}}t")))

    def cell_value(c):
        t = c.get("t")
        v = c.find(f"{{{M}}}v")
        if t == "s" and v is not None:
            return shared[int(v.text)]
        if t == "inlineStr":
            return "".join(t.text or "" for t in c.iter(f"{{{M}}}t"))
        return v.text if v is not None else ""

    def col_index(ref):
        letters = "".join(ch for ch in (ref or "") if ch.isalpha())
        idx = 0
        for ch in letters:
            idx = idx * 26 + (ord(ch) - 64)
        return idx

    sheets = {}
    for sh in wb.find(f"{{{M}}}sheets"):
        name = sh.get("name")
        target = relmap[sh.get(f"{{{RNS}}}id")].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        ws = ET.fromstring(z.read(target))
        matrix = []
        for row in ws.iter(f"{{{M}}}row"):
            cells = {}
            width = 0
            for c in row.findall(f"{{{M}}}c"):
                ci = col_index(c.get("r"))
                cells[ci] = html.unescape(str(cell_value(c)))
                width = max(width, ci)
            matrix.append([cells.get(i, "") for i in range(1, width + 1)])
        sheets[name] = matrix
    return sheets


def tabular(matrix):
    """Split a sheet into (header, data rows); fully-empty rows are dropped."""
    if not matrix:
        return [], []
    header = matrix[0]
    data = [r for r in matrix[1:] if any(v != "" for v in r)]
    return header, data


def slugify(name, taken):
    s = re.sub(r"[^0-9A-Za-z_]+", "_", (name or "").strip()).strip("_").lower() or "col"
    if s[0].isdigit():
        s = "c_" + s
    base, n = s, 2
    while s in taken:
        s = f"{base}_{n}"
        n += 1
    taken.add(s)
    return s


def to_iso(value):
    """Excel serial date -> ISO date text; anything else passes through unchanged."""
    if SERIAL_RE.match(value or ""):
        serial = int(float(value))
        if SERIAL_MIN <= serial <= SERIAL_MAX:
            return (EXCEL_EPOCH + timedelta(days=serial)).isoformat()
    return value


def infer_affinity(values):
    vals = [v for v in values if v not in ("", None)]
    if not vals:
        return "TEXT"
    if all(INT_RE.match(v) for v in vals):
        return "INTEGER"
    if all(NUM_RE.match(v) for v in vals):
        return "REAL"
    return "TEXT"


def convert(value, affinity):
    if value in ("", None):
        return None
    if affinity == "INTEGER":
        return int(float(value))
    if affinity == "REAL":
        return float(value)
    return value


def load_sheet(conn, sheet, matrix):
    header, data = tabular(matrix)
    if not header or not any(v != "" for v in header):
        raise SystemExit(f"abort: sheet {sheet!r} has no header row")
    ncols = len(header)

    taken = set()
    cols = [slugify(h, taken) for h in header]

    rows = []
    for r in data:
        if len(r) < ncols:
            r = r + [""] * (ncols - len(r))
        elif len(r) > ncols:
            r = r[:ncols]
        rows.append(r)

    date_idx = {i for i, c in enumerate(cols) if (sheet, c) in DATE_COLUMNS}
    for r in rows:
        for i in date_idx:
            r[i] = to_iso(r[i])

    affinities = [infer_affinity([r[i] for r in rows]) for i in range(ncols)]

    pk_cols = PK_CANDIDATES.get(sheet, [])
    if pk_cols and not all(c in cols for c in pk_cols):
        print(f"  note  {sheet}: PK candidate columns missing - skipped")
        pk_cols = []
    pk_clause = ""
    if pk_cols:
        idxs = [cols.index(c) for c in pk_cols]
        keys = [tuple(r[i] for i in idxs) for r in rows]
        if len(set(keys)) == len(keys):
            pk_clause = (",\n  PRIMARY KEY ("
                        + ", ".join(f'"{c}"' for c in pk_cols) + ")")
        else:
            print(f"  note  {sheet}: PK candidate {pk_cols} not unique - plain index only")
            pk_cols = []

    coldefs = ",\n  ".join(f'"{c}" {a}' for c, a in zip(cols, affinities))
    conn.execute(f'DROP TABLE IF EXISTS "{sheet}"')
    conn.execute(f'CREATE TABLE "{sheet}" (\n  {coldefs}{pk_clause}\n)')

    placeholders = ", ".join("?" * ncols)
    payload = [[convert(v, a) for v, a in zip(r, affinities)] for r in rows]
    conn.executemany(f'INSERT INTO "{sheet}" VALUES ({placeholders})', payload)

    for c in cols:
        if c not in INDEX_COLUMNS and c not in pk_cols:
            continue
        if pk_clause and len(pk_cols) == 1 and c in pk_cols:
            continue  # single-column PK already indexes it
        conn.execute(f'CREATE INDEX "idx_{sheet}__{c}" ON "{sheet}"("{c}")')

    pk_note = f"  PK: ({', '.join(pk_cols)})" if pk_clause else ""
    print(f"  load  {sheet:24} {len(rows):>6} rows{pk_note}")
    return len(rows)


def validate(conn, counts):
    print("\nValidation - row counts vs Package_Overview")
    print("-" * 60)
    all_ok = True
    for sheet, expected in EXPECTED_COUNTS.items():
        actual = counts.get(sheet)
        if actual is None:
            print(f"  {sheet:24} MISSING TABLE")
            all_ok = False
        elif actual == expected:
            print(f"  {sheet:24} {actual:>6}  ok")
        else:
            print(f"  {sheet:24} {actual:>6}  MISMATCH (expected {expected})")
            all_ok = False
    extra = sorted(set(counts) - set(EXPECTED_COUNTS))
    if extra:
        print(f"  unexpected extra tables: {extra}")

    print("\nValidation - orphan checks (informational)")
    print("-" * 60)
    for label, sql in ORPHAN_CHECKS:
        n = conn.execute(sql).fetchone()[0]
        flag = "" if n == 0 else "  <-- orphans"
        print(f"  {label:58} {n:>4}{flag}")

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"\nSQLite integrity_check: {integrity}")
    if all_ok:
        print("All row-count checks passed.")
    else:
        print("ROW-COUNT MISMATCHES FOUND - see above.")
    return all_ok


def main():
    if not XLSX.exists():
        raise SystemExit(f"workbook not found: {XLSX}")
    print(f"Source : {XLSX}")
    print(f"Target : {DB}")
    print()

    workbook = read_workbook(XLSX)
    conn = sqlite3.connect(DB)
    # virtiofs mounts choke on the default rollback journal (create/delete of
    # "bayer_sinceai.db-journal"), which surfaces as
    # "attempt to write a readonly database". An in-memory journal sidesteps
    # the file churn; the build stays idempotent, so crash-safety is not needed.
    conn.execute("PRAGMA journal_mode=MEMORY")
    try:
        counts = {}
        for sheet, matrix in workbook.items():
            if sheet in DOC_SHEETS:
                print(f"  skip  {sheet:24} (documentation -> DATA_PACK_README.md)")
                continue
            counts[sheet] = load_sheet(conn, sheet, matrix)

        for name, sql in VIEWS.items():
            conn.execute(f'DROP VIEW IF EXISTS "{name}"')
            conn.execute(sql)
        conn.commit()

        total = sum(counts.values())
        print(f"\nLoaded {len(counts)} tables ({total:,} rows) and {len(VIEWS)} views.")
        ok = validate(conn, counts)
        if not ok:
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
