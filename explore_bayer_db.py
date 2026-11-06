import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "Bayer_SinceAI2026 _1_" / "Bayer_SinceAI2026" / "bayer_sinceai.db"
OUT = BASE / "findings.json"

con = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)


def rows(sql, *params):
    return con.execute(sql, params).fetchall()


def one(sql, *params):
    return con.execute(sql, params).fetchone()[0]


def hdr(title):
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def sub(title):
    print(f"\n-- {title}")


def table(headers, data):
    if not data:
        print("  (none)")
        return
    widths = [max([len(str(h))] + [len(str(r[i])) for r in data]) for i, h in enumerate(headers)]
    print("  " + "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)).rstrip())
    print("  " + "  ".join("-" * w for w in widths))
    for r in data:
        print("  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip())


def crosstab(pairs, row_label, col_label):
    counts = Counter(pairs)
    rorder = sorted({r for r, _ in pairs})
    corder = sorted({c for _, c in pairs})
    data = [[r] + [counts[(r, c)] for c in corder] + [sum(counts[(r, c)] for c in corder)] for r in rorder]
    headers = [row_label] + corder + ["total"]
    data.append(["total"] + [sum(counts[(r, c)] for r in rorder) for c in corder] + [len(pairs)])
    table(headers, data)
    return {f"{r}|{c}": counts[(r, c)] for r in rorder for c in corder}


USAGE_SQL = """
SELECT a.asset_id, a.asset_name, a.platform, a.lifecycle_status, a.endorsement,
       a.estimated_audience, a.product_scope, a.market_scope, a.model_id,
       SUM(u.views), AVG(u.unique_users), SUM(u.exports), AVG(u.avg_load_ms),
       SUM(u.query_errors), MAX(u.month),
       SUM(CASE WHEN u.month >= ? THEN u.views ELSE 0 END),
       SUM(CASE WHEN u.month < ? THEN u.views ELSE 0 END)
FROM Analytics_Assets a JOIN Asset_Usage u ON u.asset_id = a.asset_id
GROUP BY a.asset_id
"""

months = [r[0] for r in rows("SELECT DISTINCT month FROM Asset_Usage ORDER BY month")]
recent_cutoff = months[-3]
usage = {}


def load_usage():
    for r in rows(USAGE_SQL, recent_cutoff, recent_cutoff):
        usage[r[0]] = {
            "asset_id": r[0], "asset_name": r[1], "platform": r[2],
            "lifecycle_status": r[3], "endorsement": r[4],
            "estimated_audience": r[5], "product_scope": r[6],
            "market_scope": r[7], "model_id": r[8], "views": r[9],
            "avg_users": round(r[10] or 0, 1), "exports": r[11],
            "avg_load_ms": round(r[12] or 0), "errors": r[13],
            "last_month": r[14], "recent3_views": r[15], "prior_views": r[16],
        }


def s1_estate(f):
    hdr("1. ESTATE OVERVIEW")
    sub("Core counts")
    counts = {
        "assets": one("SELECT COUNT(*) FROM Analytics_Assets"),
        "semantic_models": one("SELECT COUNT(*) FROM Semantic_Models"),
        "kpis": one("SELECT COUNT(*) FROM KPI_Catalog"),
        "lineage_edges": one("SELECT COUNT(*) FROM Lineage_Edges"),
        "usage_rows": one("SELECT COUNT(*) FROM Asset_Usage"),
        "governance_signals": one("SELECT COUNT(*) FROM Governance_Signals"),
        "migration_items": one("SELECT COUNT(*) FROM Migration_Backlog"),
        "business_requests": one("SELECT COUNT(*) FROM Business_Requests"),
    }
    table(["metric", "value"], [[k, v] for k, v in counts.items()])
    f["counts"] = counts

    sub("Assets: platform x lifecycle")
    ct = crosstab(rows("SELECT platform, lifecycle_status FROM Analytics_Assets"), "platform", "lifecycle")
    f["platform_x_lifecycle"] = ct

    sub("Assets: type x platform")
    ct2 = crosstab(rows("SELECT asset_type, platform FROM Analytics_Assets"), "asset_type", "platform")
    f["assettype_x_platform"] = ct2

    sub("Semantic models: endorsement x refresh status")
    ct3 = crosstab(rows("SELECT endorsement, refresh_status FROM Semantic_Models"), "endorsement", "refresh_status")
    f["model_endorsement_x_refresh"] = ct3

    sub("Coverage gaps")
    orphan_models = rows(
        "SELECT model_id, model_name, endorsement, refresh_status FROM Semantic_Models m "
        "WHERE NOT EXISTS (SELECT 1 FROM Lineage_Edges e "
        "WHERE e.source_id = m.model_id AND e.edge_type = 'MODEL_TO_ASSET')"
    )
    orphan_assets = rows(
        "SELECT asset_id, asset_name FROM Analytics_Assets a WHERE NOT EXISTS "
        "(SELECT 1 FROM Lineage_Edges e WHERE e.target_id = a.asset_id)"
    )
    print(f"  models with no downstream assets: {len(orphan_models)}")
    table(["model", "name", "endorsement", "refresh"], orphan_models[:8])
    print(f"  assets with no lineage edge at all: {len(orphan_assets)}")
    f["orphan_models"] = [list(r) for r in orphan_models]
    f["orphan_assets"] = len(orphan_assets)

    sub("Busiest workspaces (by asset count)")
    top_ws = rows(
        "SELECT w.workspace_name, w.platform, COUNT(*) FROM Analytics_Assets a "
        "JOIN Workspaces w ON w.workspace_id = a.workspace_id "
        "GROUP BY w.workspace_id ORDER BY 3 DESC LIMIT 8"
    )
    table(["workspace", "platform", "assets"], top_ws)
    f["top_workspaces"] = [list(r) for r in top_ws]


def s2_duplicates(f):
    hdr("2. DUPLICATE / OVERLAP DETECTION")
    sub("Asset groups sharing identical scope (product x market x model)")
    groups = rows(
        "SELECT product_scope, market_scope, model_id, COUNT(*) FROM Analytics_Assets "
        "GROUP BY 1, 2, 3 HAVING COUNT(*) > 1 ORDER BY 4 DESC"
    )
    dup_assets = one(
        "SELECT COUNT(*) FROM Analytics_Assets WHERE (product_scope, market_scope, model_id) IN "
        "(SELECT product_scope, market_scope, model_id FROM Analytics_Assets "
        "GROUP BY 1, 2, 3 HAVING COUNT(*) > 1)"
    )
    print(f"  {len(groups)} scope-groups contain multiple assets, covering {dup_assets} assets in total")
    table(["product", "market", "model", "assets"], groups[:10])
    f["scope_groups_multi"] = len(groups)
    f["scope_group_assets"] = dup_assets

    sub("Cross-platform overlap: same product x market served on both platforms")
    xplats = rows(
        "SELECT product_scope, market_scope, COUNT(DISTINCT platform) FROM Analytics_Assets "
        "GROUP BY 1, 2 HAVING COUNT(DISTINCT platform) > 1 ORDER BY 2 DESC, 1"
    )
    print(f"  {len(xplats)} product-market scopes served on more than one platform")
    table(["product", "market", "platforms"], xplats[:10])
    f["cross_platform_scopes"] = len(xplats)

    sub("Exact duplicate asset names")
    namedup = rows(
        "SELECT asset_name, COUNT(*) c, GROUP_CONCAT(platform), COUNT(DISTINCT platform) "
        "FROM Analytics_Assets GROUP BY asset_name HAVING c > 1 ORDER BY c DESC LIMIT 10"
    )
    n_names = one("SELECT COUNT(*) FROM (SELECT asset_name FROM Analytics_Assets GROUP BY 1 HAVING COUNT(*) > 1)")
    n_assets = one(
        "SELECT COUNT(*) FROM Analytics_Assets WHERE asset_name IN "
        "(SELECT asset_name FROM Analytics_Assets GROUP BY 1 HAVING COUNT(*) > 1)"
    )
    print(f"  {n_names} asset names are shared by {n_assets} assets")
    table(["asset_name", "count", "platforms", "distinct_platforms"], namedup)
    f["duplicate_names"] = n_names
    f["duplicate_name_assets"] = n_assets


def s3_usage(f):
    hdr("3. USAGE PROFILING")
    views_sorted = sorted(u["views"] for u in usage.values())
    p10 = views_sorted[len(views_sorted) // 10]
    p90 = views_sorted[-(len(views_sorted) // 10)]
    print(f"  usage window: {months[0]} .. {months[-1]} (recent 3 months from {recent_cutoff})")
    print(f"  per-asset total views: min={views_sorted[0]}, p10={p10}, median={views_sorted[len(views_sorted)//2]}, p90={p90}, max={views_sorted[-1]}")

    sub("Monthly estate usage trend")
    trend = rows(
        "SELECT month, SUM(views), SUM(exports), SUM(query_errors) FROM Asset_Usage GROUP BY month ORDER BY month"
    )
    table(["month", "views", "exports", "errors"], trend)
    f["monthly_views"] = {m: v for m, v, _, _ in trend}

    sub(f"Active assets with bottom-decile usage (views <= {p10}) — waste candidates")
    waste = [
        [u["asset_id"], u["asset_name"], u["platform"], u["views"], u["avg_users"]]
        for u in usage.values() if u["lifecycle_status"] == "active" and u["views"] <= p10
    ]
    waste.sort(key=lambda r: r[3])
    print(f"  {len(waste)} active assets with near-zero consumption")
    table(["asset", "name", "platform", "views", "avg_users"], waste[:10])
    f["active_low_usage"] = len(waste)

    sub(f"Legacy / retire-candidate assets with top-decile usage (views >= {p90}) — risky retirement")
    risky = [
        [u["asset_id"], u["asset_name"], u["lifecycle_status"], u["views"], u["avg_users"]]
        for u in usage.values() if u["lifecycle_status"] != "active" and u["views"] >= p90
    ]
    risky.sort(key=lambda r: -r[3])
    print(f"  {len(risky)} non-active assets still heavily used")
    table(["asset", "name", "lifecycle", "views", "avg_users"], risky[:10])
    f["nonactive_high_usage"] = len(risky)

    sub("Usage momentum: recent 3 months vs prior 7 months (top decliners among active assets)")
    decliners = []
    for u in usage.values():
        if u["prior_views"] > 0 and u["lifecycle_status"] == "active":
            ratio = u["recent3_views"] / (u["prior_views"] / 7 * 3)
            if ratio < 0.5:
                decliners.append([u["asset_id"], u["asset_name"], u["views"], round(ratio, 2)])
    decliners.sort(key=lambda r: r[3])
    print(f"  {len(decliners)} active assets with recent usage under 50% of prior pace")
    table(["asset", "name", "total_views", "recent_vs_prior"], decliners[:10])
    f["active_declining_usage"] = len(decliners)

    sub("Worst performers: load time and query errors")
    by_load = sorted(usage.values(), key=lambda u: -u["avg_load_ms"])[:5]
    table(["asset", "name", "avg_load_ms", "errors"],
          [[u["asset_id"], u["asset_name"], u["avg_load_ms"], u["errors"]] for u in by_load])
    by_err = sorted(usage.values(), key=lambda u: -u["errors"])[:5]
    table(["asset", "name", "errors", "views"],
          [[u["asset_id"], u["asset_name"], u["errors"], u["views"]] for u in by_err])
    f["p10_views"] = p10
    f["p90_views"] = p90


def s4_kpi(f):
    hdr("4. KPI GOVERNANCE & CONFLICTS")
    sub("Canonical metrics with conflicting definitions")
    conflicts = rows(
        "SELECT canonical_metric, variant_count, variants, canonical_variants, approved_variants "
        "FROM v_kpi_conflicts ORDER BY variant_count DESC, canonical_metric"
    )
    print(f"  {len(conflicts)} canonical metrics have more than one KPI variant")
    table(["canonical_metric", "variants", "detail", "canonical", "approved"], conflicts)
    f["kpi_conflict_count"] = len(conflicts)
    f["kpi_conflicts"] = [list(r) for r in conflicts]

    sub("Definition / approval status across KPI catalog")
    table(["definition_status", "approval_status", "count"],
          rows("SELECT definition_status, approval_status, COUNT(*) FROM KPI_Catalog GROUP BY 1, 2 ORDER BY 3 DESC"))
    f["kpi_status"] = [list(r) for r in rows(
        "SELECT definition_status, approval_status, COUNT(*) FROM KPI_Catalog GROUP BY 1, 2 ORDER BY 3 DESC")]

    sub("Assets referencing unapproved KPI variants")
    unappr = rows(
        "SELECT k.kpi_id, k.kpi_name, k.canonical_metric, COUNT(DISTINCT m.asset_id) "
        "FROM Asset_KPI_Map m JOIN KPI_Catalog k ON k.kpi_id = m.kpi_id "
        "WHERE k.approval_status != 'approved' "
        "GROUP BY k.kpi_id ORDER BY 4 DESC LIMIT 15"
    )
    n_assets_unappr = one(
        "SELECT COUNT(DISTINCT m.asset_id) FROM Asset_KPI_Map m JOIN KPI_Catalog k ON k.kpi_id = m.kpi_id "
        "WHERE k.approval_status != 'approved'"
    )
    print(f"  {n_assets_unappr} assets reference at least one unapproved KPI variant")
    table(["kpi", "name", "canonical", "assets_using"], unappr)
    f["assets_using_unapproved_kpis"] = n_assets_unappr

    sub("Assets mixing multiple KPI variants of the same canonical metric")
    mixing = rows(
        "SELECT m.asset_id, a.asset_name, k.canonical_metric, COUNT(DISTINCT m.kpi_id) "
        "FROM Asset_KPI_Map m JOIN KPI_Catalog k ON k.kpi_id = m.kpi_id "
        "JOIN Analytics_Assets a ON a.asset_id = m.asset_id "
        "GROUP BY m.asset_id, k.canonical_metric HAVING COUNT(DISTINCT m.kpi_id) > 1 "
        "ORDER BY 4 DESC LIMIT 15"
    )
    print(f"  {len(mixing)} asset/canonical-metric combinations mix conflicting definitions (top 15 shown)")
    table(["asset", "name", "canonical_metric", "kpi_variants_used"], mixing)
    f["asset_metric_mixing"] = len(mixing)


def s5_lineage(f):
    hdr("5. LINEAGE & BLAST RADIUS")
    sub("Edge types")
    edges = rows("SELECT edge_type, COUNT(*) FROM Lineage_Edges GROUP BY 1 ORDER BY 2 DESC")
    table(["edge_type", "count"], edges)
    f["edge_types"] = [list(r) for r in edges]

    sub("Downstream blast radius per semantic model (top 10)")
    blast = rows(
        "SELECT m.model_id, m.model_name, m.refresh_status, m.endorsement, COUNT(e.target_id) "
        "FROM Semantic_Models m LEFT JOIN Lineage_Edges e "
        "ON e.source_id = m.model_id AND e.edge_type = 'MODEL_TO_ASSET' "
        "GROUP BY m.model_id ORDER BY 5 DESC, m.model_id LIMIT 10"
    )
    table(["model", "name", "refresh", "endorsement", "downstream_assets"], blast)
    f["top_blast_radius"] = [list(r) for r in blast]

    sub("Models with failed refresh and their downstream exposure")
    failed = rows(
        "SELECT m.model_id, m.model_name, COUNT(e.target_id) FROM Semantic_Models m "
        "JOIN Lineage_Edges e ON e.source_id = m.model_id AND e.edge_type = 'MODEL_TO_ASSET' "
        "WHERE m.refresh_status = 'failed' GROUP BY m.model_id ORDER BY 3 DESC"
    )
    n_down = sum(r[2] for r in failed)
    print(f"  {len(failed)} failed models affect {n_down} downstream assets")
    table(["model", "name", "downstream_assets"], failed)
    f["failed_refresh_models"] = len(failed)
    f["failed_refresh_downstream"] = n_down

    sub("Model-to-model dependencies")
    m2m = rows(
        "SELECT s.model_id, s.model_name, t.model_id, t.model_name "
        "FROM Lineage_Edges e "
        "JOIN Semantic_Models s ON s.model_id = e.source_id "
        "JOIN Semantic_Models t ON t.model_id = e.target_id "
        "WHERE e.edge_type = 'MODEL_TO_MODEL' ORDER BY s.model_id"
    )
    print(f"  {len(m2m)} model-to-model dependency edges")
    table(["from", "name", "to", "name"], m2m[:10])
    f["model_to_model"] = len(m2m)

    sub("Asset-to-asset embedded/derived links")
    n_a2a = one("SELECT COUNT(*) FROM Lineage_Edges WHERE edge_type = 'ASSET_TO_ASSET'")
    print(f"  {n_a2a} assets embed or derive from another asset (impacts retirement decisions)")
    f["asset_to_asset"] = n_a2a


def s6_governance(f):
    hdr("6. GOVERNANCE OVERLAY")
    sub("Signal codes x severity")
    ct = crosstab(rows("SELECT signal_code, severity FROM Governance_Signals"), "signal_code", "severity")
    f["signal_code_x_severity"] = ct
    sub("Signal statuses")
    table(["status", "count"], rows("SELECT status, COUNT(*) FROM Governance_Signals GROUP BY 1"))

    sub("Assets with missing owner")
    missing = rows(
        "SELECT a.asset_id, a.asset_name, a.platform, a.estimated_audience FROM Governance_Signals g "
        "JOIN Analytics_Assets a ON a.asset_id = g.asset_id "
        "WHERE g.signal_code = 'MISSING_OWNER' ORDER BY a.estimated_audience DESC"
    )
    print(f"  {len(missing)} assets have no owner")
    table(["asset", "name", "platform", "audience"], missing[:10])
    f["assets_missing_owner"] = len(missing)

    sub("Unendorsed assets with highest reach")
    reach = rows(
        "SELECT a.asset_id, a.asset_name, a.estimated_audience, a.endorsement, a.platform "
        "FROM Governance_Signals g JOIN Analytics_Assets a ON a.asset_id = g.asset_id "
        "WHERE g.signal_code = 'HIGH_REACH_UNENDORSED' "
        "ORDER BY a.estimated_audience DESC LIMIT 10"
    )
    print("  top 10 by estimated audience")
    table(["asset", "name", "audience", "endorsement", "platform"], reach)
    f["high_reach_unendorsed"] = one(
        "SELECT COUNT(*) FROM Governance_Signals WHERE signal_code = 'HIGH_REACH_UNENDORSED'")

    sub("Data quality issues: sheet x severity")
    ct2 = crosstab(rows("SELECT sheet, severity FROM Data_Quality"), "sheet", "severity")
    f["dq_sheet_x_severity"] = ct2
    sub("Most flagged fields (Semantic_Models sheet)")
    table(["field", "count"],
          rows("SELECT field, COUNT(*) FROM Data_Quality WHERE sheet = 'Semantic_Models' "
               "GROUP BY 1 ORDER BY 2 DESC"))

    sub("Composite asset risk score (top 10)")
    risk = rows(
        "SELECT a.asset_id, a.asset_name, a.lifecycle_status, "
        "(SELECT COUNT(*) FROM Governance_Signals g WHERE g.asset_id = a.asset_id AND g.severity = 'high'), "
        "(SELECT COUNT(*) FROM Governance_Signals g WHERE g.asset_id = a.asset_id AND g.severity != 'high'), "
        "(SELECT COUNT(*) FROM Data_Quality q WHERE q.record_id = a.asset_id AND q.severity = 'high'), "
        "(SELECT COUNT(*) FROM Data_Quality q WHERE q.record_id = a.asset_id AND q.severity != 'high'), "
        "m.refresh_status "
        "FROM Analytics_Assets a LEFT JOIN Semantic_Models m ON m.model_id = a.model_id"
    )
    scored = []
    for aid, name, life, hs, os_, hd, od, ref in risk:
        score = 3 * hs + os_ + 3 * hd + od
        if ref == "failed":
            score += 3
        elif ref == "warning":
            score += 1
        if life != "active":
            score += 1
        scored.append([score, aid, name, life, hs + os_, hd + od, ref])
    scored.sort(key=lambda r: -r[0])
    table(["score", "asset", "name", "lifecycle", "signals", "dq_issues", "model_refresh"],
          scored[:10])
    f["top_risk_assets"] = scored[:10]


def s7_migration(f):
    hdr("7. MIGRATION BACKLOG REALITY CHECK")
    sub("Recommended path x status")
    ct = crosstab(rows("SELECT recommended_path_candidate, status FROM Migration_Backlog"),
                  "recommended_path", "status")
    f["mig_path_x_status"] = ct
    sub("Complexity")
    table(["complexity", "count"], rows("SELECT complexity, COUNT(*) FROM Migration_Backlog GROUP BY 1"))

    sub("Duplicate target models (several backlog items pointed at the same semantic model)")
    dups = rows(
        "SELECT b.candidate_target_model_id, m.model_name, COUNT(*) "
        "FROM Migration_Backlog b JOIN Semantic_Models m ON m.model_id = b.candidate_target_model_id "
        "GROUP BY 1 HAVING COUNT(*) > 1 ORDER BY 3 DESC LIMIT 12"
    )
    print(f"  {len(dups)} target models receive more than one migrated asset")
    table(["target_model", "name", "incoming_items"], dups)
    f["duplicate_migration_targets"] = len(dups)

    sub("Target model occupancy (assets already living on each target)")
    occ = rows(
        "SELECT b.candidate_target_model_id, m.model_name, COUNT(DISTINCT b.source_asset_id), "
        "COUNT(DISTINCT CASE WHEN a.asset_id IS NOT NULL AND a.asset_id NOT IN "
        "(SELECT source_asset_id FROM Migration_Backlog) THEN a.asset_id END) "
        "FROM Migration_Backlog b JOIN Semantic_Models m ON m.model_id = b.candidate_target_model_id "
        "LEFT JOIN Analytics_Assets a ON a.model_id = b.candidate_target_model_id "
        "GROUP BY 1 ORDER BY 4 DESC LIMIT 12"
    )
    table(["target_model", "name", "incoming", "already_there"], occ)
    f["occupied_targets"] = len([r for r in occ if r[3] > 0])

    sub("Lifecycle of backlog source assets")
    table(["lifecycle", "count"],
          rows("SELECT a.lifecycle_status, COUNT(*) FROM Migration_Backlog b "
               "JOIN Analytics_Assets a ON a.asset_id = b.source_asset_id GROUP BY 1 ORDER BY 2 DESC"))

    sub("Usage cross-check: migrate-vs-retire sanity")
    mig_items = rows(
        "SELECT b.source_asset_id, b.recommended_path_candidate FROM Migration_Backlog b"
    )
    views_sorted = sorted(u["views"] for u in usage.values())
    p10 = views_sorted[len(views_sorted) // 10]
    p90 = views_sorted[-(len(views_sorted) // 10)]
    retire_should = [i for i, p in mig_items
                     if p in ("MIGRATE", "REBUILD_ON_SHARED_MODEL") and usage[i]["views"] <= p10]
    keep_check = [i for i, p in mig_items if p == "RETIRE" and usage[i]["views"] >= p90]
    print(f"  {len(retire_should)} MIGRATE/REBUILD items have bottom-decile usage (views <= {p10}) — retire instead?")
    table(["asset", "path", "views"],
          [[i, p, usage[i]["views"]] for i, p in mig_items if i in retire_should][:10])
    print(f"  {len(keep_check)} RETIRE items have top-decile usage (views >= {p90}) — verify before retiring")
    table(["asset", "views", "name"],
          [[i, usage[i]["views"], usage[i]["asset_name"]] for i in keep_check][:10])
    f["migrate_low_usage"] = len(retire_should)
    f["retire_high_usage"] = len(keep_check)


INTENTS = [
    ("replace/migrate", ("replace", "migrat", "migration")),
    ("consolidate", ("one executive view", "combin", "consolidat", "single")),
    ("new build", ("create", "new", "build")),
]


def classify_intent(text):
    t = text.lower()
    for label, kws in INTENTS:
        if any(k in t for k in kws):
            return label
    return "other"


def s8_requests(f):
    hdr("8. BUSINESS REQUESTS")
    total = one("SELECT COUNT(*) FROM Business_Requests")
    distinct = one("SELECT COUNT(DISTINCT request_text) FROM Business_Requests")
    print(f"  {total} requests, only {distinct} distinct texts (templated corpus)")
    sub("Intent mix over distinct request templates")

    counts = Counter()
    per_template = []
    for text, n in rows("SELECT request_text, COUNT(*) FROM Business_Requests GROUP BY 1 ORDER BY 2 DESC"):
        label = classify_intent(text)
        counts[label] += n
        per_template.append([label, n, text])
    table(["intent", "requests"], counts.most_common())
    f["request_intent_mix"] = dict(counts)
    sub("Templates (intent, count, text)")
    for label, n, text in per_template:
        print(f"  [{label}] x{n}: {text}")
    sub("Request context")
    table(["product_context", "count"], rows(
        "SELECT product_context, COUNT(*) FROM Business_Requests GROUP BY 1 ORDER BY 2 DESC LIMIT 10"))
    table(["market_context", "count"], rows(
        "SELECT market_context, COUNT(*) FROM Business_Requests GROUP BY 1 ORDER BY 2 DESC LIMIT 10"))
    table(["urgency", "status", "count"], rows(
        "SELECT urgency, status, COUNT(*) FROM Business_Requests GROUP BY 1, 2 ORDER BY 3 DESC"))


KPI_GROUNDING = {
    "Net Sales": "Product_Market_Monthly.net_sales_m_eur_syn",
    "Net Sales Growth": "derived: Product_Market_Monthly.net_sales_m_eur_syn MoM",
    "Units Shipped": "Product_Market_Monthly.units_shipped_syn",
    "Forecast Variance": "Product_Market_Monthly.forecast_variance_pct",
    "Demand Forecast Accuracy": "Supply_Operations.forecast_accuracy_pct_syn",
    "Demand Forecast Bias": "derived: Product_Market_Monthly forecast vs net sales",
    "Inventory Coverage": "Product_Market_Monthly.inventory_weeks_syn / Supply_Operations.inventory_weeks_syn",
    "On-Time In-Full": "Product_Market_Monthly.otif_pct_syn / Supply_Operations.otif_pct_syn",
    "Market Access Coverage": "Market_Access.coverage_pct_syn / Product_Market_Monthly.market_access_coverage_pct_syn",
    "Reimbursement Status Coverage": "Market_Access.reimbursement_status",
    "Launch Adoption Index": "derived: Launch_Milestones.first_commercial_sale + Product_Market_Monthly.net_sales",
}


def ground_status(metric):
    backing = KPI_GROUNDING.get(metric)
    if backing is None:
        return "not grounded"
    return "derived" if backing.startswith("derived:") else "grounded"


def s9_context(f):
    hdr("9. PHARMA CONTEXT DATA INVENTORY")
    sub("Sheet inventory (grain and row counts)")
    inv = [
        ["Products", "product", one("SELECT COUNT(*) FROM Products")],
        ["Markets", "market", one("SELECT COUNT(*) FROM Markets")],
        ["Product_Market_Monthly", "product x market x month", one("SELECT COUNT(*) FROM Product_Market_Monthly")],
        ["Launch_Milestones", "product x market milestone", one("SELECT COUNT(*) FROM Launch_Milestones")],
        ["Market_Access", "product x market", one("SELECT COUNT(*) FROM Market_Access")],
        ["Supply_Operations", "product x market", one("SELECT COUNT(*) FROM Supply_Operations")],
    ]
    table(["sheet", "grain", "rows"], inv)
    f["context_sheets"] = inv

    sub("Product_Market_Monthly coverage")
    lo, hi, n_months = rows(
        "SELECT MIN(month), MAX(month), COUNT(DISTINCT month) FROM Product_Market_Monthly")[0]
    print(f"  months: {lo} .. {hi} ({n_months} distinct months)")
    table(["product", "rows"],
          rows("SELECT p.product_name, COUNT(*) FROM Product_Market_Monthly pm "
               "JOIN Products p ON p.product_id = pm.product_id GROUP BY 1 ORDER BY 1"))
    table(["value_type", "rows"],
          rows("SELECT value_type, COUNT(*) FROM Product_Market_Monthly GROUP BY 1 ORDER BY 1"))
    f["pmm_months"] = n_months
    f["pmm_value_types"] = {k: v for k, v in rows(
        "SELECT value_type, COUNT(*) FROM Product_Market_Monthly GROUP BY 1")}

    sub("Markets: region x maturity")
    f["markets_region_x_maturity"] = crosstab(
        rows("SELECT region, market_maturity FROM Markets"), "region", "maturity")

    sub("Market access: reimbursement status x trend status")
    f["ma_reimb_x_trend"] = crosstab(
        rows("SELECT reimbursement_status, trend_status FROM Market_Access"),
        "reimbursement", "trend")

    sub("Supply operations: risk status")
    table(["risk_status", "rows", "avg_otif_pct", "avg_inventory_weeks"],
          rows("SELECT risk_status, COUNT(*), ROUND(AVG(otif_pct_syn), 1), ROUND(AVG(inventory_weeks_syn), 1) "
               "FROM Supply_Operations GROUP BY 1 ORDER BY 2 DESC"))
    n_hot = one("SELECT COUNT(*) FROM Supply_Operations WHERE risk_status != 'green'")
    hot = rows(
        "SELECT p.product_name, mk.market_name, s.otif_pct_syn, s.inventory_weeks_syn, s.risk_status "
        "FROM Supply_Operations s JOIN Products p ON p.product_id = s.product_id "
        "JOIN Markets mk ON mk.market_id = s.market_id "
        "WHERE s.risk_status != 'green' ORDER BY s.otif_pct_syn LIMIT 10")
    print(f"  {n_hot} non-green product-market hot spots (10 worst OTIF shown)")
    table(["product", "market", "otif_pct", "inv_weeks", "risk"], hot)
    f["supply_nongreen"] = n_hot

    sub("Launch milestones: type x status")
    f["lm_type_x_status"] = crosstab(
        rows("SELECT milestone_type, status FROM Launch_Milestones"), "milestone_type", "status")
    n_open = one("SELECT COUNT(*) FROM Launch_Milestones WHERE status != 'completed'")
    open_ms = rows(
        "SELECT p.product_name, mk.market_name, lm.milestone_type, lm.milestone_date, lm.status "
        "FROM Launch_Milestones lm JOIN Products p ON p.product_id = lm.product_id "
        "JOIN Markets mk ON mk.market_id = lm.market_id "
        "WHERE lm.status != 'completed' ORDER BY lm.milestone_date LIMIT 10")
    print(f"  {n_open} milestones not completed yet (10 by date shown)")
    table(["product", "market", "type", "date", "status"], open_ms)
    f["milestones_open"] = n_open


def s10_kpi_grounding(f):
    hdr("10. KPI GROUNDING (METADATA vs CONTEXT DATA)")
    sub("Canonical metrics mapped to context-sheet columns")
    metrics = rows("SELECT canonical_metric, COUNT(*) FROM KPI_Catalog GROUP BY 1 ORDER BY 1")
    data = []
    grounded = []
    for metric, variants in metrics:
        status = ground_status(metric)
        backing = KPI_GROUNDING.get(metric, "-")
        if status != "not grounded":
            grounded.append(metric)
        data.append([metric, variants, backing, status])
    table(["canonical_metric", "kpi_variants", "backed_by", "status"], data)
    n_ground = sum(1 for r in data if r[3] == "grounded")
    n_derive = sum(1 for r in data if r[3] == "derived")
    n_missing = len(data) - n_ground - n_derive
    print(f"  {n_ground} grounded, {n_derive} derivable, {n_missing} not grounded "
          f"(of {len(data)} canonical metrics)")
    f["kpi_grounding"] = data
    f["kpi_grounded"] = n_ground
    f["kpi_derived"] = n_derive
    f["kpi_not_grounded"] = n_missing

    sub("Ungrounded metrics and the assets that depend on them")
    ph = ",".join("?" * len(grounded))
    expo = rows(
        f"SELECT k.canonical_metric, COUNT(DISTINCT m.asset_id) FROM Asset_KPI_Map m "
        f"JOIN KPI_Catalog k ON k.kpi_id = m.kpi_id "
        f"WHERE k.canonical_metric NOT IN ({ph}) GROUP BY 1 ORDER BY 2 DESC", *grounded)
    table(["ungrounded_metric", "assets_using"], expo)
    f["ungrounded_metric_assets"] = [list(r) for r in expo]

    n_blind = one(
        f"SELECT COUNT(*) FROM (SELECT m.asset_id FROM Asset_KPI_Map m "
        f"JOIN KPI_Catalog k ON k.kpi_id = m.kpi_id GROUP BY m.asset_id "
        f"HAVING SUM(CASE WHEN k.canonical_metric IN ({ph}) THEN 1 ELSE 0 END) = 0)", *grounded)
    print(f"  {n_blind} assets reference ONLY ungrounded canonical metrics")
    f["assets_only_ungrounded_kpis"] = n_blind


METRIC_KEYWORDS = [
    ("Net Sales Growth", ("sales growth",)),
    ("Net Sales", ("net sales",)),
    ("Gross-to-Net Rate", ("gross-to-net",)),
    ("Budget Variance", ("budget variance",)),
    ("Demand Forecast Accuracy", ("forecast accuracy",)),
    ("Forecast Variance", ("forecast variance",)),
    ("Inventory Coverage", ("inventory",)),
    ("On-Time In-Full", ("on-time in-full", "otif")),
    ("Market Access Coverage", ("market access",)),
    ("Reimbursement Status Coverage", ("reimbursement",)),
    ("Launch Adoption Index", ("adoption", "first sales")),
]

DOMAIN_KEYWORDS = [
    ("Supply Chain", ("supply", "inventory", "on-time", "otif")),
    ("Market Access", ("market access", "reimbursement")),
    ("Launch Excellence", ("launch", "adoption", "readiness", "first sales")),
    ("Finance", ("net sales", "gross-to-net", "budget", "variance", "finance")),
    ("Commercial", ("product performance", "sales growth", "performance", "commercial", "growth")),
]


def resolve_markets(contexts):
    ids = set()
    for c in contexts:
        if one("SELECT COUNT(*) FROM Markets WHERE market_id = ?", c):
            ids.add(c)
        else:
            ids.update(r[0] for r in rows("SELECT market_id FROM Markets WHERE region = ?", c))
    return sorted(ids)


def find_covering(products, market_ids, domains):
    if not domains:
        return []
    products = products or ["All Pharma"]
    dph = ",".join("?" * len(domains))
    pph = ",".join("?" * len(products))
    sql = (
        "SELECT a.asset_id, a.asset_name, a.platform, a.endorsement, sm.refresh_status "
        "FROM Analytics_Assets a "
        "JOIN Asset_KPI_Map km ON km.asset_id = a.asset_id "
        "JOIN KPI_Catalog k ON k.kpi_id = km.kpi_id "
        "LEFT JOIN Semantic_Models sm ON sm.model_id = a.model_id "
        f"WHERE a.lifecycle_status = 'active' AND k.domain IN ({dph}) "
        f"AND (a.product_scope IN ({pph}) OR a.product_scope = 'All Pharma')"
    )
    params = list(domains) + list(products)
    if market_ids:
        mph = ",".join("?" * len(market_ids))
        sql += f" AND (a.market_scope IN ({mph}) OR a.market_scope = 'Global')"
        params += list(market_ids)
    else:
        sql += " AND a.market_scope = 'Global'"
    return rows(sql + " GROUP BY a.asset_id ORDER BY a.asset_id", *params)


def cover_score(a):
    u = usage.get(a[0])
    views = u["views"] if u else 0
    end = {"certified": 3, "promoted": 2, "none": 1}.get(a[3], 1)
    ref = {"healthy": 3, "warning": 1, "failed": 0}.get(a[4], 1)
    return views * end * ref


def s11_request_triage(f):
    hdr("11. REQUEST TRIAGE (BUILD-LESS CHECK)")
    metric_domain = {m: d for m, d in rows(
        "SELECT canonical_metric, MIN(domain) FROM KPI_Catalog GROUP BY 1")}
    product_names = [r[0] for r in rows("SELECT product_name FROM Products ORDER BY 1")]
    product_tas = rows("SELECT product_name, therapeutic_area FROM Products")
    regions = [r[0] for r in rows("SELECT DISTINCT region FROM Markets ORDER BY 1")]
    all_markets = [r[0] for r in rows("SELECT market_id FROM Markets ORDER BY 1")]

    templates = rows("SELECT request_text, COUNT(*) FROM Business_Requests GROUP BY 1 ORDER BY 2 DESC")
    triage = []
    n_newbuild_total = 0
    n_newbuild_covered = 0
    for text, n in templates:
        t = text.lower()
        intent = classify_intent(text)
        metrics = [m for m, kws in METRIC_KEYWORDS if any(k in t for k in kws)]
        domains = []
        for d, kws in DOMAIN_KEYWORDS:
            if any(k in t for k in kws) and d not in domains:
                domains.append(d)
        for m in metrics:
            d = metric_domain.get(m)
            if d and d not in domains:
                domains.append(d)
        text_products = [p for p in product_names if p.lower() in t]
        text_products += [p for p, ta in product_tas
                          if ta.lower() in t and p not in text_products]
        text_regions = [r for r in regions if r.lower() in t]
        ctx = rows("SELECT DISTINCT product_context, market_context FROM Business_Requests "
                   "WHERE request_text = ?", text)
        products = text_products or sorted({c for c, _ in ctx})
        if any(k in t for k in ("global", "country-level", "by country")):
            market_ids = all_markets
        elif text_regions:
            market_ids = resolve_markets(text_regions)
        else:
            market_ids = resolve_markets([c for _, c in ctx])
        cover = find_covering(products, market_ids, domains)
        cover.sort(key=cover_score, reverse=True)
        gaps = [m for m in metrics if ground_status(m) == "not grounded"]
        if not cover:
            verdict = "GENUINE NEW BUILD"
        elif len(cover) >= 8:
            verdict = f"CONSOLIDATE FIRST ({len(cover)} overlapping assets)"
        else:
            verdict = f"REUSE CANDIDATE ({len(cover)} assets)"
        triage.append({
            "intent": intent, "requests": n, "text": text, "products": products,
            "markets": market_ids, "metrics": metrics, "domains": domains,
            "covering_assets": len(cover), "top_assets": [list(c) for c in cover[:3]],
            "verdict": verdict, "data_gaps": gaps,
        })
        if intent == "new build":
            n_newbuild_total += n
            if cover:
                n_newbuild_covered += n

    sub("Per-template triage")
    for tri in triage:
        print(f"\n  [{tri['intent']}] x{tri['requests']}: {tri['text']}")
        print(f"   scope: products={', '.join(tri['products'])}; "
              f"markets={', '.join(tri['markets']) or 'Global'}")
        print("   metrics: " + (", ".join(f"{m} ({ground_status(m)})" for m in tri["metrics"])
                               or "(none named)"))
        print(f"   domains: {', '.join(tri['domains']) or '-'}")
        print(f"   covering active assets: {tri['covering_assets']}")
        for c in tri["top_assets"]:
            u = usage.get(c[0], {})
            print(f"     {c[0]}  {c[1]}  [{c[2]} | {c[3]} | {c[4] or '-'}]  views={u.get('views', 0)}")
        print(f"   verdict: {tri['verdict']}"
              + (f"  (data gap: {', '.join(tri['data_gaps'])})" if tri["data_gaps"] else ""))

    sub("Triage summary")
    table(["intent", "requests", "covering_assets", "verdict"],
          [[t_["intent"], t_["requests"], t_["covering_assets"], t_["verdict"]] for t_ in triage])
    n_reuse_tpl = sum(1 for t_ in triage if t_["covering_assets"] > 0)
    print(f"  {n_reuse_tpl}/10 templates have active assets already covering the requested scope")
    print(f"  {n_newbuild_covered} of {n_newbuild_total} new-build requests already covered "
          f"— candidates for reuse instead of new build")
    f["request_triage"] = triage
    f["newbuild_total_requests"] = n_newbuild_total
    f["newbuild_covered_requests"] = n_newbuild_covered
    f["templates_with_reuse_candidates"] = n_reuse_tpl


def summarize(f):
    hdr("KEY FINDINGS")
    lines = [
        f"Sprawl: {f['scope_groups_multi']} scope-groups hold {f['scope_group_assets']} assets; "
        f"{f['cross_platform_scopes']} product-market scopes served on both platforms; "
        f"{f['duplicate_name_assets']} assets share {f['duplicate_names']} duplicate names",
        f"Waste: {f['active_low_usage']} active assets with bottom-decile usage; "
        f"{f['active_declining_usage']} active assets with usage collapsing vs prior months",
        f"Retirement risk: {f['nonactive_high_usage']} legacy/retire-candidate assets still in top usage decile",
        f"KPI governance: {f['kpi_conflict_count']} canonical metrics have conflicting variants; "
        f"{f['assets_using_unapproved_kpis']} assets reference unapproved KPIs; "
        f"{f['asset_metric_mixing']} asset/metric pairs mix variants",
        f"Lineage: {f['failed_refresh_models']} failed-refresh models affect "
        f"{f['failed_refresh_downstream']} downstream assets; "
        f"{len(f['orphan_models'])} orphan models; {f['asset_to_asset']} embedded asset links",
        f"Ownership: {f['assets_missing_owner']} assets missing owner; "
        f"{f['high_reach_unendorsed']} high-reach unendorsed assets",
        f"Migration: 94 backlog items; {f['duplicate_migration_targets']} duplicate targets; "
        f"{f['migrate_low_usage']} migrate-items near-zero usage; {f['retire_high_usage']} retire-items top-decile usage",
        f"Requests: 150 requests from 10 templates; intent mix {f['request_intent_mix']}",
        f"KPI grounding: {f['kpi_grounded']} grounded + {f['kpi_derived']} derived vs "
        f"{f['kpi_not_grounded']} ungrounded canonical metrics; "
        f"{f['assets_only_ungrounded_kpis']} assets depend only on ungrounded metrics",
        f"Build less: {f['newbuild_covered_requests']} of {f['newbuild_total_requests']} new-build "
        f"requests already covered by active assets; {f['templates_with_reuse_candidates']}/10 "
        f"templates have reuse candidates",
    ]
    for l in lines:
        print(f"  - {l}")
    f["key_findings"] = lines


def main():
    load_usage()
    f = {}
    s1_estate(f)
    s2_duplicates(f)
    s3_usage(f)
    s4_kpi(f)
    s5_lineage(f)
    s6_governance(f)
    s7_migration(f)
    s8_requests(f)
    s9_context(f)
    s10_kpi_grounding(f)
    s11_request_triage(f)
    summarize(f)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(f, fh, indent=2, default=str)
    print(f"\nFindings written to {OUT}")


if __name__ == "__main__":
    main()
