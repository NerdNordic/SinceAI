"""Run the golden-question evaluation against the real Gemini model and store the result.

    python -m tools.run_eval                 # 40 questions x 2 repeats, about 6-10 min on the free tier
    python -m tools.run_eval --repeats 1     # faster, no consistency check
    python -m tools.run_eval --only q01 q08  # selected questions

Needs MONGODB_URI and GEMINI_API_KEY (application/.env). The run is saved to MongoDB (eval_runs) and shown
in the Data Steward view under "Laadunvarmistus"; a copy is written to eval/results/latest.json and .md.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend import evaluation

RESULTS = Path(__file__).resolve().parent.parent / "eval" / "results"


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f} %"


def markdown(doc: dict) -> str:
    s = doc["summary"]
    lines = [
        f"# Evaluation run {doc['_id']}",
        "",
        f"Model `{doc['model']}`, prompt `{doc['prompt_version']}`, {doc['repeats']} repeats per question, "
        f"run {doc['started_at']:%Y-%m-%d %H:%M} UTC."
        + ("" if doc.get("complete", True) else f" **Partial run: {doc.get('stopped')}.**"),
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Interpretation accuracy | {s['passed']}/{s['total']} ({_pct(s['accuracy'])}) |",
        f"| Consistency across repeats | {s['consistent']}/{s['total']} ({_pct(s['consistency'])}) |",
        f"| Unsupported questions answered by guessing | {s['unsupported_guessed']}/{s['unsupported_total']} |",
        f"| Errors | {s['errors']} |",
        "",
        "| Category | Passed |",
        "|---|---|",
        *[f"| {k} | {v['passed']}/{v['total']} |" for k, v in s["by_category"].items()],
        "",
        "| Language | Passed |",
        "|---|---|",
        *[f"| {k} | {v['passed']}/{v['total']} |" for k, v in s["by_language"].items()],
        "",
        "| # | Role | Question | Result | Consistent | Problems |",
        "|---|---|---|---|---|---|",
    ]
    for r in doc["results"]:
        lines.append(f"| {r['id']} | {r['role']} | {r['question']} | {'✓' if r['passed'] else '✗'} | "
                     f"{'✓' if r['consistent'] else '✗'} | {'; '.join(r['problems'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--delay", type=float, default=4.0, help="seconds between Gemini calls (free-tier pacing)")
    ap.add_argument("--language", choices=["fi", "en"], default="fi")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-store", action="store_true", help="do not save the run to MongoDB")
    args = ap.parse_args()

    n = len(args.only) if args.only else (args.limit or len(evaluation.load_questions()))
    print(f"Evaluating {n} questions x {args.repeats} repeats (pause {args.delay}s between calls)\n")

    def progress(r: dict) -> None:
        mark = "PASS" if r["passed"] else "FAIL"
        cons = "" if r["consistent"] else "  [inconsistent]"
        print(f"{r['id']} {mark}  {r['question'][:58]:<58}{cons}")
        for p in r["problems"]:
            print(f"        - {p}")

    doc = evaluation.run(repeats=args.repeats, delay=args.delay, language=args.language,
                         limit=args.limit, only=args.only, progress=progress, store=not args.no_store)
    s = doc["summary"]
    if doc["stopped"]:
        done = {r["id"] for r in doc["results"]}
        rest = [q["id"] for q in evaluation.load_questions() if q["id"] not in done and (not args.only or q["id"] in args.only)]
        print(f"\nStopped early ({doc['stopped']}) after {len(doc['results'])}/{doc['planned']} questions.")
        if rest:
            print("Continue later with:  python -m tools.run_eval --only " + " ".join(rest))
    print(f"\nAccuracy     {s['passed']}/{s['total']} ({_pct(s['accuracy'])})")
    print(f"Consistency  {s['consistent']}/{s['total']} ({_pct(s['consistency'])})")
    print(f"Guessed on unsupported questions: {s['unsupported_guessed']}/{s['unsupported_total']}")
    if s["errors"]:
        print(f"Errors: {s['errors']} (see eval/results/latest.md)")

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (RESULTS / "latest.md").write_text(markdown(doc), encoding="utf-8")
    print(f"\nSaved run {doc['_id']}" + ("" if args.no_store else " to MongoDB (Data Steward -> Laadunvarmistus)")
          + f" and {RESULTS / 'latest.md'}")


if __name__ == "__main__":
    main()
