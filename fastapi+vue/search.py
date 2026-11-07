"""Try the vector search from the command line.

    python search.py kpi "toimitusvarmuus"
    python search.py kpi "net sales" --all-variants
    python search.py asset "Nubeqa sales growth and market access by country"
    python search.py chart "OTIF trend by market"
"""

import argparse
import os

from pymongo import MongoClient

import vector_store as vs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", choices=["kpi", "asset", "chart"])
    ap.add_argument("text")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--all-variants", action="store_true", help="kpi: include non-canonical variants")
    args = ap.parse_args()

    db = MongoClient(os.environ["MONGODB_URI"])[os.environ.get("MONGODB_DB", "bayer_hackathon")]
    if args.target == "kpi":
        hits = vs.search_kpis(db, args.text, canonical_only=not args.all_variants, limit=args.limit)
        for h in hits:
            print(f"{h['score']:.3f}  {h['_id']}  {h['kpi_name']:<34} {h['definition_status']:<20} -> {h['canonical_metric']}")
    elif args.target == "asset":
        for h in vs.search_assets(db, args.text, limit=args.limit):
            print(f"{h['score']:.3f}  {h['_id']}  {h['asset_name']:<40} {', '.join(h['canonical_metrics'])}")
    else:
        hits = vs.search_charts(db, args.text, limit=args.limit)
        for h in hits:
            print(f"{h['score']:.3f}  {h['fingerprint']}  {h['title']}")
        if not hits:
            print("no charts found (chart_registry stays empty until the bot registers charts)")


if __name__ == "__main__":
    main()
