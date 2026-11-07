"""End-to-end test of Gemini embeddings + Atlas Vector Search.

    python test_search.py              # all tests
    python test_search.py --only kpi   # kpi | asset | chart

Needs MONGODB_URI and GEMINI_API_KEY (same as seed_mongo.py). Uses about 30 embedding calls.
Exit code 0 = all required checks passed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

from pymongo import MongoClient

import vector_store as vs

# (query, expected canonical metric). The first group uses words from kpi_aliases.json,
# the second group are paraphrases that are NOT in the alias list: they test real semantic matching.
KPI_CASES_ALIAS = [
    ("toimitusvarmuus", "On-Time In-Full"),
    ("OTIF", "On-Time In-Full"),
    ("varastoviikot", "Inventory Coverage"),
    ("kuinka kauan varasto riittää", "Inventory Coverage"),
    ("myynnin kasvu", "Net Sales Growth"),
    ("liikevaihto", "Net Sales"),
    ("ennustetarkkuus", "Demand Forecast Accuracy"),
    ("toteuma vs ennuste", "Forecast Variance"),
    ("korvattavuus", "Reimbursement Status Coverage"),
    ("markkinoille pääsy", "Market Access Coverage"),
    ("toimitetut kappaleet", "Units Shipped"),
    ("budjettipoikkeama", "Budget Variance"),
    ("katetuotto", "Operating Contribution"),
]
KPI_CASES_PARAPHRASE = [
    ("how reliable are our deliveries", "On-Time In-Full"),
    ("toimitetaanko tilaukset ajallaan", "On-Time In-Full"),
    ("how many weeks of stock do we have left", "Inventory Coverage"),
    ("paljonko tuotteita lähetettiin kuukaudessa", "Units Shipped"),
    ("are we beating the forecast", "Forecast Variance"),
    ("kuinka hyvin kysyntä osattiin ennustaa", "Demand Forecast Accuracy"),
]

RESET, GREEN, RED, YELLOW = "\033[0m", "\033[32m", "\033[31m", "\033[33m"


def ok(msg: str) -> None:
    print(f"  {GREEN}PASS{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}WARN{RESET} {msg}")


def check_indexes(db) -> bool:
    print("\nVector indexes")
    good = True
    for coll, name in (("kpi_catalog", vs.KPI_INDEX), ("analytics_assets", vs.ASSET_INDEX), ("chart_registry", vs.CHART_INDEX)):
        idx = next((i for i in db[coll].list_search_indexes() if i["name"] == name), None)
        if idx is None:
            fail(f"{coll}.{name} missing (run seed_mongo.py)")
            good = False
        elif not idx.get("queryable"):
            fail(f"{coll}.{name} not queryable yet (status {idx.get('status')}); wait a minute")
            good = False
        else:
            ok(f"{coll}.{name} queryable")
    return good


def test_kpis(db) -> tuple[int, int]:
    """Returns (top1 hits, total). Top-3 misses count as failures."""
    print("\nKPI search (canonical only): user phrase -> canonical KPI")
    top1 = failures = total = 0
    for group, cases in (("alias", KPI_CASES_ALIAS), ("paraphrase", KPI_CASES_PARAPHRASE)):
        print(f"  -- {group} --")
        for query, expected in cases:
            total += 1
            t0 = time.time()
            hits = vs.search_kpis(db, query, canonical_only=True, limit=3)
            ms = (time.time() - t0) * 1000
            got = [h["canonical_metric"] for h in hits]
            if any(h["definition_status"] != "canonical" for h in hits):
                fail(f"{query!r}: non-canonical KPI leaked through the filter")
                failures += 1
            elif got and got[0] == expected:
                top1 += 1
                ok(f"{query!r:<46} -> {hits[0]['_id']} {got[0]}  ({hits[0]['score']:.3f}, {ms:.0f} ms)")
            elif expected in got:
                warn(f"{query!r:<46} -> {expected} at rank {got.index(expected) + 1}; top1 was {got[0]}")
            else:
                fail(f"{query!r:<46} -> expected {expected}, got {got}")
                failures += 1

    print("\nKPI variants (why results are always resolved to canonical)")
    hits = vs.search_kpis(db, "Net Sales Local", canonical_only=False, limit=3)
    for h in hits:
        print(f"       {h['score']:.3f}  {h['_id']}  {h['kpi_name']:<28} {h['definition_status']:<20} -> {h['canonical_metric']}")
    if hits and hits[0]["definition_status"] != "canonical":
        ok("top hit is a variant; the app must map it to its canonical_metric before use")
    print(f"\n  KPI summary: top-1 {top1}/{total}, failures (not in top-3) {failures}")
    return top1, failures


def test_assets(db) -> int:
    print("\nAsset search: request -> existing Bayer reports")
    failures = 0
    query = "Nubeqa net sales growth and market access by country"
    hits = vs.search_assets(db, query, limit=5)
    for h in hits:
        print(f"       {h['score']:.3f}  {h['_id']}  {h['product_scope']:<11} {', '.join(h['canonical_metrics'])}")
    if any("Net Sales Growth" in h["canonical_metrics"] for h in hits):
        ok("a report measuring Net Sales Growth is in the top 5")
    else:
        fail("no report measuring Net Sales Growth in the top 5")
        failures += 1

    hits = vs.search_assets(db, query, filter={"product_scope": "Nubeqa"}, limit=5)
    if hits and all(h["product_scope"] == "Nubeqa" for h in hits):
        ok(f"filter product_scope=Nubeqa respected ({len(hits)} hits)")
    else:
        fail("filter product_scope=Nubeqa not respected")
        failures += 1
    return failures


def test_chart_registry(db) -> int:
    """Register a throwaway chart, find it with different words, then delete it."""
    print("\nChart registry: register -> find with other words -> delete")
    fp = f"test-{uuid.uuid4().hex[:8]}"
    vs.register_chart(db, {
        "fingerprint": fp,
        "title": "OTIF trend by market",
        "description": "Monthly On-Time In-Full percentage per market for products supplied by Plant A",
        "role": "vuoropäällikkö",
        "plant": "Plant-A",
        "kpi_ids": ["KPI-020"],
        "spec": {"kpis": ["KPI-020"], "dimensions": ["market_id"], "grain": "month"},
        "owner": "test",
        "status": "test",
    })
    failures = 0
    try:
        found = None
        for _ in range(12):  # the vector index syncs new documents within seconds
            hits = vs.search_charts(db, "toimitusvarmuus markkinoittain kuukausittain", filter={"plant": "Plant-A"}, limit=3)
            found = next((h for h in hits if h["fingerprint"] == fp), None)
            if found:
                break
            time.sleep(2.5)
        if found:
            ok(f"found the test chart with a Finnish paraphrase (score {found['score']:.3f})")
        else:
            fail("test chart not found within 30 s")
            failures += 1
    finally:
        db.chart_registry.delete_one({"fingerprint": fp})
        print("       test chart deleted")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["kpi", "asset", "chart"])
    args = ap.parse_args()

    db = MongoClient(os.environ["MONGODB_URI"])[os.environ.get("MONGODB_DB", "bayer_hackathon")]
    print(f"Embedding model {vs.EMBED_MODEL} ({vs.EMBED_DIM} dims), database {db.name}")
    if not check_indexes(db):
        sys.exit(1)

    failures = 0
    if args.only in (None, "kpi"):
        failures += test_kpis(db)[1]
    if args.only in (None, "asset"):
        failures += test_assets(db)
    if args.only in (None, "chart"):
        failures += test_chart_registry(db)

    print(f"\n{GREEN + 'ALL REQUIRED CHECKS PASSED' if not failures else RED + f'{failures} CHECK(S) FAILED'}{RESET}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
