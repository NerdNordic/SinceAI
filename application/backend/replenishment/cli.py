"""Command line: compute the replenishment forecast and write CSV/JSON outputs.

    python -m backend.replenishment.cli --xlsx Bayer_...Builder_Data_Pack.xlsx --out output --today 2026-11-06
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .data import load_data_pack
from .model import Assumptions, compute_all, default_as_of, flatten, metric_definition, plant_summary

HERE = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", required=True, help="Path to the builder data pack .xlsx")
    ap.add_argument("--assumptions", default=str(HERE / "config" / "assumptions.json"))
    ap.add_argument("--out", default=str(HERE / "output"))
    ap.add_argument("--as-of", type=date.fromisoformat, help="Inventory snapshot date (default: end of latest month in data)")
    ap.add_argument("--today", type=date.fromisoformat, help="Date statuses are evaluated against (default: system date)")
    args = ap.parse_args(argv)

    data = load_data_pack(args.xlsx)
    a = Assumptions.load(args.assumptions)
    as_of = args.as_of or default_as_of(data)
    today = args.today or date.today()
    results = compute_all(data, a, as_of=as_of, today=today)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    flatten(results).to_csv(out / "reorder_forecast.csv", index=False)
    (out / "reorder_forecast.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    plant_summary(results).to_csv(out / "plant_summary.csv", index=False)
    (out / "metric_definition.json").write_text(
        json.dumps(metric_definition(a, data, as_of), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    status = flatten(results)["status"].value_counts().to_dict()
    print(f"as_of={as_of} today={today} assumptions={a['version']} ({a.fingerprint})")
    print(f"{len(results)} product x market rows -> {status}")
    print(f"wrote {out}/reorder_forecast.csv, reorder_forecast.json, plant_summary.csv, metric_definition.json")


if __name__ == "__main__":
    main()
