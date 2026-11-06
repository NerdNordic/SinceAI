"""Load the Bayer builder data pack into MongoDB Atlas and add vector embeddings where they help.

Every data sheet becomes a normal collection (numbers stay numbers and are queried exactly).
Embeddings are added to only two collections, plus an empty chart registry:

    kpi_catalog       -> user phrase ("toimitusvarmuus") finds the right KPI
    analytics_assets  -> description built from each report's KPIs, products and markets
    chart_registry    -> charts the bot creates; near-duplicate detection

    MONGODB_URI=... GEMINI_API_KEY=... python seed_mongo.py --xlsx data_pack.xlsx
    python seed_mongo.py --xlsx data_pack.xlsx --dry-run out/      # no Mongo, no Gemini
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import vector_store as vs

HERE = Path(__file__).resolve().parent

# sheet -> (collection, natural key used as _id or None)
SHEETS: dict[str, tuple[str, str | None]] = {
    "Products": ("products", "product_id"),
    "Markets": ("markets", "market_id"),
    "Owners": ("owners", "owner_id"),
    "KPI_Catalog": ("kpi_catalog", "kpi_id"),
    "Workspaces": ("workspaces", "workspace_id"),
    "Semantic_Models": ("semantic_models", "model_id"),
    "Analytics_Assets": ("analytics_assets", "asset_id"),
    "Asset_KPI_Map": ("asset_kpi_map", None),
    "Asset_Usage": ("asset_usage", None),
    "Lineage_Edges": ("lineage_edges", None),
    "Product_Market_Monthly": ("product_market_monthly", None),
    "Launch_Milestones": ("launch_milestones", "milestone_id"),
    "Market_Access": ("market_access", None),
    "Supply_Operations": ("supply_operations", None),
    "Data_Quality": ("data_quality", "issue_id"),
    "Governance_Signals": ("governance_signals", "signal_id"),
    "Migration_Backlog": ("migration_backlog", None),
    "Business_Requests": ("business_requests", "request_id"),
    "Governance_Rules": ("governance_rules", "rule_id"),
    "Data_Dictionary": ("data_dictionary", None),
    "Public_References": ("public_references", None),
}

REGULAR_INDEXES: dict[str, list[list[tuple[str, int]]]] = {
    "product_market_monthly": [[("product_id", 1), ("market_id", 1), ("month", 1)]],
    "supply_operations": [[("product_id", 1), ("market_id", 1)], [("supply_source", 1)]],
    "market_access": [[("product_id", 1), ("market_id", 1)]],
    "asset_usage": [[("asset_id", 1), ("month", 1)]],
    "asset_kpi_map": [[("asset_id", 1)], [("kpi_id", 1)]],
    "lineage_edges": [[("source_id", 1)], [("target_id", 1)]],
    "governance_signals": [[("asset_id", 1)]],
    "analytics_assets": [[("product_scope", 1), ("market_scope", 1)], [("canonical_metrics", 1)]],
    "chart_registry": [[("fingerprint", 1)]],
}

# collection -> (index name, filter fields). Atlas M0 allows 3 search/vector indexes in total.
VECTOR_INDEXES: dict[str, tuple[str, list[str]]] = {
    "kpi_catalog": (vs.KPI_INDEX, ["definition_status", "canonical_metric", "domain", "approval_status"]),
    "analytics_assets": (vs.ASSET_INDEX, ["product_scope", "market_scope", "platform", "lifecycle_status", "endorsement"]),
    "chart_registry": (vs.CHART_INDEX, ["role", "plant", "status", "kpi_ids"]),
}


# --------------------------------------------------------------------------- loading

def clean(v: Any) -> Any:
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if math.isnan(v) else float(v)
    return v


def load_sheets(xlsx: Path) -> dict[str, list[dict[str, Any]]]:
    frames = pd.read_excel(xlsx, sheet_name=list(SHEETS))
    collections: dict[str, list[dict[str, Any]]] = {}
    for sheet, (coll, key) in SHEETS.items():
        df = frames[sheet]
        if key and df[key].duplicated().any():
            print(f"  ! {sheet}.{key} is not unique; using generated ids")
            key = None
        docs = []
        for i, row in enumerate(df.to_dict(orient="records")):
            doc = {str(k): clean(v) for k, v in row.items()}
            if key:
                doc["_id"] = doc[key]
            doc["_source"] = {"file": xlsx.name, "sheet": sheet, "row": i + 2, "provenance": "datapack"}
            docs.append(doc)
        collections[coll] = docs
    return collections


# --------------------------------------------------------------------------- embedding texts

def enrich_kpis(kpis: list[dict], aliases: dict[str, list[str]]) -> None:
    for k in kpis:
        al = aliases.get(k["canonical_metric"], [])
        k["aliases"] = al
        k["embedding_text"] = (
            f"KPI {k['kpi_name']}. Canonical metric: {k['canonical_metric']}. "
            f"Domain: {k['domain']}. Unit: {k['unit']}. Frequency: {k['default_frequency']}. "
            f"Also called: {', '.join(al)}."
        )
        k["_enrichment"] = {"aliases": "curated (kpi_aliases.json)", "embedding_text": "derived"}


def enrich_assets(assets: list[dict], kpi_map: list[dict], kpis: list[dict], workspaces: list[dict], markets: list[dict]) -> None:
    """Describe each report by what it measures, not by its name: names in the data pack do not match content."""
    kpi_by_id = {k["kpi_id"]: k for k in kpis}
    ws_name = {w["workspace_id"]: w["workspace_name"] for w in workspaces}
    mk_name = {m["market_id"]: m["market_name"] for m in markets}
    by_asset: dict[str, list[str]] = {}
    for row in kpi_map:
        by_asset.setdefault(row["asset_id"], []).append(row["kpi_id"])
    for a in assets:
        ids = sorted(by_asset.get(a["asset_id"], []))
        metrics = sorted({kpi_by_id[i]["canonical_metric"] for i in ids if i in kpi_by_id})
        variants = sorted(kpi_by_id[i]["kpi_name"] for i in ids if i in kpi_by_id and kpi_by_id[i]["definition_status"] != "canonical")
        a["kpi_ids"] = ids
        a["canonical_metrics"] = metrics
        a["non_canonical_kpis"] = variants
        market = mk_name.get(a["market_scope"], a["market_scope"])
        a["embedding_text"] = (
            f"{a['asset_type']} in {a['platform']} for {a['product_scope']}, market {market}. "
            f"Measures: {', '.join(metrics) or 'none'}. Workspace: {ws_name.get(a['workspace_id'], a['workspace_id'])}. "
            f"Delivery model: {a['delivery_model']}."
        )
        a["_enrichment"] = {"kpi_ids/canonical_metrics": "derived from Asset_KPI_Map", "embedding_text": "derived"}


def fake_vectors(texts: list[str], dim: int) -> list[list[float]]:
    """Deterministic stand-in for dry runs and tests (no API calls)."""
    out = []
    for t in texts:
        seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        out.append(vs._normalize(rng.standard_normal(dim).tolist()))
    return out


def add_embeddings(docs: list[dict], fake: bool) -> None:
    texts = [d["embedding_text"] for d in docs]
    vectors = fake_vectors(texts, vs.EMBED_DIM) if fake else vs.embed(texts)
    for d, v in zip(docs, vectors):
        d["embedding"] = v
        d["embedding_model"] = "fake" if fake else vs.EMBED_MODEL
        d["embedding_dim"] = len(v)


# --------------------------------------------------------------------------- mongo

def vector_index_definition(filters: list[str]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"type": "vector", "path": "embedding", "numDimensions": vs.EMBED_DIM, "similarity": "cosine"}
    ]
    fields += [{"type": "filter", "path": f} for f in filters]
    return {"fields": fields}


def write_mongo(db, collections: dict[str, list[dict]], skip_vector_indexes: bool, wait: int) -> None:
    for coll, docs in collections.items():
        # delete_many (not drop) keeps existing search indexes in place
        db[coll].delete_many({})
        if docs:
            db[coll].insert_many(docs)
        print(f"  {coll:<24} {len(docs):>5} docs")

    if "chart_registry" not in db.list_collection_names():
        db.create_collection("chart_registry")
        print("  chart_registry           created (empty, never overwritten)")

    for coll, specs in REGULAR_INDEXES.items():
        for keys in specs:
            db[coll].create_index(keys)

    if skip_vector_indexes:
        return

    from pymongo.errors import OperationFailure
    from pymongo.operations import SearchIndexModel

    for coll, (name, filters) in VECTOR_INDEXES.items():
        existing = {i["name"]: i for i in db[coll].list_search_indexes()}
        definition = vector_index_definition(filters)
        if name in existing:
            old = existing[name].get("latestDefinition", {})
            if old.get("fields") != definition["fields"]:
                db[coll].update_search_index(name, definition)
                print(f"  vector index {name:<14} updated")
            else:
                print(f"  vector index {name:<14} exists")
            continue
        try:
            db[coll].create_search_index(SearchIndexModel(definition=definition, name=name, type="vectorSearch"))
            print(f"  vector index {name:<14} created on {coll}")
        except OperationFailure as exc:
            print(f"  ! could not create {name}: {exc}. Atlas M0 allows 3 search/vector indexes in total.")

    if wait:
        deadline = time.time() + wait
        pending = set(VECTOR_INDEXES)
        while pending and time.time() < deadline:
            for coll in list(pending):
                name = VECTOR_INDEXES[coll][0]
                idx = next((i for i in db[coll].list_search_indexes() if i["name"] == name), None)
                if idx and idx.get("queryable"):
                    pending.discard(coll)
            if pending:
                time.sleep(5)
        print("  vector indexes queryable" if not pending else f"  ! still building: {sorted(pending)}")


def write_dry_run(out: Path, collections: dict[str, list[dict]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for coll, docs in collections.items():
        with (out / f"{coll}.jsonl").open("w", encoding="utf-8") as f:
            for d in docs:
                f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
        print(f"  {coll:<24} {len(docs):>5} docs -> {out / (coll + '.jsonl')}")
    defs = {coll: {"name": n, "type": "vectorSearch", "definition": vector_index_definition(f)} for coll, (n, f) in VECTOR_INDEXES.items()}
    (out / "vector_indexes.json").write_text(json.dumps(defs, indent=2), encoding="utf-8")
    print(f"  vector index definitions -> {out / 'vector_indexes.json'}")


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--db", default=os.environ.get("MONGODB_DB", "bayer_hackathon"))
    ap.add_argument("--aliases", default=str(HERE / "kpi_aliases.json"))
    ap.add_argument("--dry-run", metavar="DIR", help="write JSONL files instead of MongoDB; no API calls")
    ap.add_argument("--fake-embeddings", action="store_true", help="deterministic fake vectors (testing)")
    ap.add_argument("--skip-embeddings", action="store_true")
    ap.add_argument("--skip-vector-indexes", action="store_true")
    ap.add_argument("--wait", type=int, default=120, help="seconds to wait for vector indexes to become queryable")
    args = ap.parse_args(argv)

    xlsx = Path(args.xlsx)
    print(f"loading {xlsx.name}")
    collections = load_sheets(xlsx)

    aliases = {k: v for k, v in json.loads(Path(args.aliases).read_text(encoding="utf-8")).items() if not k.startswith("_")}
    missing = sorted({k["canonical_metric"] for k in collections["kpi_catalog"]} - set(aliases))
    if missing:
        print(f"  ! no aliases for: {missing}")
    enrich_kpis(collections["kpi_catalog"], aliases)
    enrich_assets(collections["analytics_assets"], collections["asset_kpi_map"], collections["kpi_catalog"],
                  collections["workspaces"], collections["markets"])

    if not args.skip_embeddings:
        fake = args.fake_embeddings or bool(args.dry_run)
        print(f"embedding with {'fake vectors' if fake else vs.EMBED_MODEL} ({vs.EMBED_DIM} dims)")
        add_embeddings(collections["kpi_catalog"], fake)
        add_embeddings(collections["analytics_assets"], fake)

    stamp = datetime.now(timezone.utc)
    for docs in collections.values():
        for d in docs:
            d["_source"]["loaded_at"] = stamp

    if args.dry_run:
        write_dry_run(Path(args.dry_run), collections)
        return

    uri = os.environ.get("MONGODB_URI")
    if not uri:
        sys.exit("Set MONGODB_URI (mongodb+srv://user:pass@cluster.../)")
    from pymongo import MongoClient

    client = MongoClient(uri, appname="since-ai-seed")
    print(f"writing to database {args.db}")
    write_mongo(client[args.db], collections, args.skip_vector_indexes, args.wait)
    print("done")


if __name__ == "__main__":
    main()
