"""Evaluate question -> ChartSpec accuracy against real Gemini, twice.

    python -m tools.eval_spec                          # all cases, 2 passes
    python -m tools.eval_spec --only otif              # cases whose id contains 'otif'
    python -m tools.eval_spec --passes 1               # single pass, no reproducibility
    python -m tools.eval_spec --no-hints               # prompt without vector-search hints
    python -m tools.eval_spec --validate                # dataset validation only, no Gemini calls
    python -m tools.eval_spec --report ../ignore/eval_report.json

Runs the production question-understanding path from backend.spec without the
MongoDB llm_cache: KPI hints -> prompt -> Gemini (temperature 0) -> sanitize.
The second pass therefore measures real reproducibility. Nothing is written to
MongoDB. Needs MONGODB_URI and GEMINI_API_KEY, like the app.

Accuracy is reported per pass over the core fields (metric, dimensions,
filters) and separately over extras (chart_type, intent, actuals_only, mode,
understood). Expected values are post-sanitize. Exit codes: 0 run completed
(mismatches are measurements, not failures), 1 a Gemini call failed after
retries, 2 configuration or dataset error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend import config, db as dbmod, spec as specmod

DATASET = Path(__file__).resolve().parent / "eval_dataset.json"
RESET, GREEN, RED, YELLOW = "\033[0m", "\033[32m", "\033[31m", "\033[33m"

LANGUAGES = {"en", "fi"}
DIMENSIONS = {"month", "market", "product", "plant"}
CHART_TYPES = {"line", "bar", "table"}
INTENTS = {"recurring", "one_off"}
MODES = {"data", "chat"}
STATUSES = {"STOCKOUT_RISK", "ORDER_NOW", "URGENT", "PLAN", "OK"}
FILTER_KEYS = ("product_ids", "market_ids", "plants", "statuses")


def ok(msg: str) -> None:
    print(f"  {GREEN}PASS{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}WARN{RESET} {msg}")


def die(msg: str) -> None:
    print(f"{RED}ERROR{RESET} {msg}")
    sys.exit(2)


def _pct(n: int, total: int) -> str:
    return f"{n}/{total} ({100.0 * n / total:.1f}%)" if total else "0/0"


# --------------------------------------------------------------------------- dataset

def _check_filters(value: Any, lk: dict, ctx: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{ctx}: filters must be an object")
        return
    allowed = {"product_ids": set(lk["products"]), "market_ids": set(lk["markets"]),
               "plants": set(lk["plants"]), "statuses": STATUSES}
    for key, ids in value.items():
        if key not in allowed:
            errors.append(f"{ctx}: unknown filter key '{key}'")
        elif not isinstance(ids, list):
            errors.append(f"{ctx}: filters.{key} must be a list")
        else:
            bad = sorted(set(ids) - allowed[key])
            if bad:
                errors.append(f"{ctx}: filters.{key} has unknown values {bad}")


def load_and_validate(path: Path) -> list[dict[str, Any]]:
    from backend.metrics import METRICS

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"cannot read dataset {path}: {exc}")
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        die(f"dataset {path} has no cases")

    lk = dbmod.lookups()
    metrics = set(METRICS) | {"UNSUPPORTED"}
    errors: list[str] = []
    ids: set[str] = set()
    for i, c in enumerate(cases):
        ctx = f"case {i + 1} ({c.get('id', '?')})"
        for field in ("id", "question", "language", "role", "expected"):
            if field not in c:
                errors.append(f"{ctx}: missing field '{field}'")
        if not str(c.get("question", "")).strip():
            errors.append(f"{ctx}: empty question")
        if c.get("id") in ids:
            errors.append(f"{ctx}: duplicate id '{c.get('id')}'")
        ids.add(c.get("id", ""))
        if c.get("language") not in LANGUAGES:
            errors.append(f"{ctx}: language must be one of {sorted(LANGUAGES)}")
        if c.get("role") not in config.ROLES:
            errors.append(f"{ctx}: unknown role '{c.get('role')}'")

        exp = c.get("expected")
        if not isinstance(exp, dict):
            errors.append(f"{ctx}: 'expected' must be an object")
            continue
        metric = exp.get("metric")
        if metric not in metrics:
            errors.append(f"{ctx}: unknown metric '{metric}'")
        dims = exp.get("dimensions")
        if not isinstance(dims, list) or not set(dims) <= DIMENSIONS:
            errors.append(f"{ctx}: dimensions must be a list from {sorted(DIMENSIONS)}")
        if metric == "Demand Forecast Accuracy" and "month" in (dims or []):
            errors.append(f"{ctx}: sanitize drops 'month' for Demand Forecast Accuracy; write post-sanitize dimensions")
        flt = exp.get("filters")
        if not isinstance(flt, dict) or not flt:
            errors.append(f"{ctx}: expected.filters object is required")
        else:
            _check_filters(flt, lk, ctx, errors)
            if metric != "Replenishment Reorder-By Date" and flt.get("statuses"):
                errors.append(f"{ctx}: sanitize clears statuses unless the metric is Replenishment Reorder-By Date")
            if config.ROLES.get(c.get("role", ""), {}).get("plant") and "plants" not in flt:
                errors.append(f"{ctx}: role '{c.get('role')}' defaults to its plant; add filters.plants to the expectations")
        for field, allowed in (("chart_type", CHART_TYPES), ("intent", INTENTS), ("mode", MODES)):
            if field in exp and exp[field] not in allowed:
                errors.append(f"{ctx}: {field} must be one of {sorted(allowed)}")
        for field in ("actuals_only", "understood"):
            if field in exp and not isinstance(exp[field], bool):
                errors.append(f"{ctx}: {field} must be a boolean")

        for h in c.get("history") or []:
            hctx = f"{ctx} history"
            if not isinstance(h, dict) or "q" not in h or not isinstance(h.get("spec"), dict):
                errors.append(f"{hctx}: each entry needs 'q' and 'spec'")
                continue
            s = h["spec"]
            if s.get("metric") not in metrics:
                errors.append(f"{hctx}: unknown metric '{s.get('metric')}'")
            if not set(s.get("dimensions", [])) <= DIMENSIONS:
                errors.append(f"{hctx}: dimensions must be from {sorted(DIMENSIONS)}")
            _check_filters(s.get("filters", {}), lk, hctx, errors)

    if errors:
        for e in errors:
            fail(e)
        die(f"dataset has {len(errors)} validation error(s)")
    return cases


# --------------------------------------------------------------------------- run and compare

def run_case(case: dict[str, Any], use_hints: bool) -> tuple[specmod.ChartSpec, list[str]]:
    question, role, language = case["question"], case["role"], case["language"]
    hints = specmod._kpi_hints(question) if use_hints else []
    prompt = specmod._prompt(question, role, hints, case.get("history") or [], language)
    raw = specmod._call_gemini(prompt, language)
    return specmod._sanitize(raw, role, language), hints


def check(spec: specmod.ChartSpec, expected: dict[str, Any]) -> dict[str, Any]:
    """Return {field: None when it matches, else (expected, got)} for every expected field."""
    out: dict[str, Any] = {}
    if "metric" in expected:
        out["metric"] = None if spec.metric == expected["metric"] else (expected["metric"], spec.metric)
    if "dimensions" in expected:
        want, got = set(expected["dimensions"]), set(spec.dimensions)
        out["dimensions"] = None if want == got else (sorted(want), sorted(spec.dimensions))
    for key in FILTER_KEYS:
        if key in expected.get("filters", {}):
            want, got = set(expected["filters"][key]), set(getattr(spec.filters, key))
            out[f"filters.{key}"] = None if want == got else (sorted(want), sorted(getattr(spec.filters, key)))
    for field in ("chart_type", "intent", "mode"):
        if field in expected:
            got = getattr(spec, field)
            out[field] = None if got == expected[field] else (expected[field], got)
    for field in ("actuals_only", "understood"):
        if field in expected:
            got = getattr(spec, field)
            out[field] = None if got is expected[field] else (expected[field], got)
    return out


def core_fields(expected: dict[str, Any]) -> list[str]:
    fields = ["metric", "dimensions"]
    fields += [f"filters.{k}" for k in FILTER_KEYS if k in expected.get("filters", {})]
    return fields


def signature(spec: specmod.ChartSpec) -> dict[str, Any]:
    """Semantic spec fields; free text (title, reply, clarification) is compared separately."""
    f = spec.filters
    return {
        "metric": spec.metric, "mode": spec.mode, "understood": spec.understood,
        "dimensions": sorted(spec.dimensions), "chart_type": spec.chart_type,
        "intent": spec.intent, "actuals_only": spec.actuals_only,
        "filters": {k: sorted(getattr(f, k)) for k in FILTER_KEYS},
    }


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=DATASET, help="evaluation dataset JSON (default: tools/eval_dataset.json)")
    ap.add_argument("--passes", type=int, default=2, help="run every case this many times (default 2; reproducibility compares first and last pass)")
    ap.add_argument("--only", help="run only cases whose id contains this substring")
    ap.add_argument("--no-hints", action="store_true", help="do not fetch KPI vector-search hints")
    ap.add_argument("--report", type=Path, help="write a JSON result report to this path")
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds to pause between Gemini calls (default 0.5)")
    ap.add_argument("--validate", action="store_true", help="validate the dataset and exit; no Gemini calls")
    args = ap.parse_args()
    if args.passes < 1:
        die("--passes must be at least 1")

    if not config.MONGODB_URI:
        die("Set MONGODB_URI (application/.env)")
    try:
        dbmod.lookups()
    except Exception as exc:  # noqa: BLE001
        die(f"MongoDB is not reachable: {exc}")
    if not args.validate and not os.environ.get("GEMINI_API_KEY"):
        die("Set GEMINI_API_KEY (application/.env)")

    cases = load_and_validate(args.dataset)
    if args.only:
        cases = [c for c in cases if args.only.lower() in c["id"].lower()]
        if not cases:
            die(f"--only '{args.only}' matches no case id")
    if args.validate:
        ok(f"dataset {args.dataset.name}: {len(cases)} case(s) valid")
        return

    n = len(cases)
    print(f"Model {config.GEMINI_MODEL}, prompt {specmod.PROMPT_VERSION}, {n} case(s), "
          f"{args.passes} pass(es), hints {'off' if args.no_hints else 'on'}")
    if config.DEMO_PLANT != "Plant-A":
        warn(f"DEMO_PLANT is '{config.DEMO_PLANT}'; dataset expectations assume Plant-A")

    started = time.monotonic()
    runs: list[list[dict[str, Any]]] = []
    call_errors = 0
    for p in range(1, args.passes + 1):
        print(f"\nPass {p}/{args.passes}")
        results: list[dict[str, Any]] = []
        for i, case in enumerate(cases, 1):
            try:
                spec, hints = run_case(case, use_hints=not args.no_hints)
            except Exception as exc:  # noqa: BLE001
                call_errors += 1
                fail(f"[{i}/{n}] {case['id']}: Gemini call failed: {exc}")
                results.append({"case": case, "spec": None, "hints": [], "fields": {},
                                "core_ok": False, "extras_ok": True, "error": str(exc)})
                time.sleep(args.sleep)
                continue
            fields = check(spec, case["expected"])
            core = core_fields(case["expected"])
            core_ok = all(fields.get(f) is None for f in core)
            extras_ok = all(fields[f] is None for f in fields if f not in core)
            results.append({"case": case, "spec": spec, "hints": hints, "fields": fields,
                            "core_ok": core_ok, "extras_ok": extras_ok, "error": None})
            bad_core = [f for f in core if fields.get(f) is not None]
            bad_extra = [f for f in fields if f not in core and fields[f] is not None]
            mark = f"{GREEN}PASS{RESET}" if core_ok and extras_ok else (
                f"{RED}FAIL{RESET}" if not core_ok else f"{YELLOW}PASS{RESET}")
            detail = f" core: {', '.join(bad_core)}" if bad_core else ""
            detail += f" extras: {', '.join(bad_extra)}" if bad_extra else ""
            print(f"  {mark} [{i}/{n}] {case['id']} ({case['language']}){detail}")
            time.sleep(args.sleep)
        runs.append(results)

    repro: list[bool | None] = [None] * n
    title_diffs = 0
    if args.passes >= 2:
        first, last = runs[0], runs[-1]
        for i in range(n):
            if first[i]["spec"] is None or last[i]["spec"] is None:
                repro[i] = False
                continue
            repro[i] = signature(first[i]["spec"]) == signature(last[i]["spec"])
            if first[i]["spec"].title != last[i]["spec"].title:
                title_diffs += 1

    print("\nMismatch details")
    shown = False
    for p, results in enumerate(runs, 1):
        for r in results:
            bad = {f: v for f, v in r["fields"].items() if v is not None}
            if not bad:
                continue
            shown = True
            hint_note = "" if r["hints"] or args.no_hints else "  (no KPI hints)"
            print(f"  {r['case']['id']} (pass {p}){hint_note}")
            for f, (want, got) in bad.items():
                print(f"    {f}: expected {want!r} got {got!r}")
    if args.passes >= 2:
        for i, case in enumerate(cases):
            if repro[i] is True:
                continue
            shown = True
            print(f"  {case['id']}: not reproducible (pass 1 vs pass {args.passes})")
            s1 = runs[0][i]["spec"]
            s2 = runs[-1][i]["spec"]
            if s1 is not None and s2 is not None:
                sig1, sig2 = signature(s1), signature(s2)
                for f in sig1:
                    if sig1[f] != sig2[f]:
                        print(f"    {f}: {sig1[f]!r} -> {sig2[f]!r}")
    if not shown:
        print("  (none)")

    def extras_total() -> int:
        return sum(1 for c in cases if any(f in c["expected"] for f in
                                           ("chart_type", "intent", "mode", "actuals_only", "understood")))

    print("\nSummary")
    print("Core accuracy (metric + dimensions + filters):")
    for p, results in enumerate(runs, 1):
        good = sum(1 for r in results if r["core_ok"])
        print(f"  pass {p}: {_pct(good, n)}")
    first = runs[0]
    field_stats = {}
    for key in ["metric", "dimensions"] + [f"filters.{k}" for k in FILTER_KEYS]:
        checked = [r for r in first if key in r["fields"]]
        if checked:
            field_stats[key] = sum(1 for r in checked if r["fields"][key] is None)
            print(f"  {key}: {_pct(field_stats[key], len(checked))} (pass 1)")
    filt_ok = sum(1 for r in first if all(r["fields"].get(f"filters.{k}") is None
                                          for k in FILTER_KEYS if f"filters.{k}" in r["fields"]))
    print(f"  filters (all four): {_pct(filt_ok, n)} (pass 1)")
    et = extras_total()
    if et:
        print(f"Extras: {_pct(sum(1 for r in first if r['extras_ok']), et)} of cases with extras (pass 1)")
    if args.passes >= 2:
        print(f"Reproducibility (semantic fields): {_pct(sum(1 for x in repro if x), n)} "
              f"between pass 1 and pass {args.passes}")
        print(f"  titles differed on {title_diffs} case(s) (informational)")
    for lang in sorted(LANGUAGES):
        idx = [i for i, c in enumerate(cases) if c["language"] == lang]
        if idx:
            good = sum(1 for i in idx if first[i]["core_ok"])
            print(f"By language (pass 1 core): {lang} {_pct(good, len(idx))}")
    groups: dict[str, list[bool]] = {}
    for i, c in enumerate(cases):
        groups.setdefault(c["expected"]["metric"], []).append(first[i]["core_ok"])
    print("By metric (pass 1 core):")
    for m in sorted(groups):
        v = groups[m]
        print(f"  {m}: {sum(v)}/{len(v)}")
    with_hints = sum(1 for r in first if r["hints"])
    if args.no_hints:
        print("Hints: disabled (--no-hints)")
    elif with_hints:
        print(f"Hints: KPI hints found for {with_hints}/{n} questions")
    else:
        warn("no question produced KPI hints; Atlas vector search may be unavailable "
             "(results reflect the no-hints prompt path)")
    print(f"Runtime: {time.monotonic() - started:.0f} s, {n * args.passes} generate calls "
          f"(+ {0 if args.no_hints else n * args.passes} embed calls)")

    if args.report:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": config.GEMINI_MODEL,
            "prompt_version": specmod.PROMPT_VERSION,
            "hints": not args.no_hints,
            "cases": [
                {"id": c["id"], "question": c["question"], "language": c["language"], "role": c["role"],
                 "expected": c["expected"], "hints": first[i]["hints"], "reproducible": repro[i],
                 "runs": [{"pass": p + 1, "core_ok": r["core_ok"], "extras_ok": r["extras_ok"],
                           "error": r["error"],
                           "fields": {f: (None if v is None else [v[0], v[1]]) for f, v in r["fields"].items()},
                           "spec": r["spec"].model_dump() if r["spec"] else None}
                          for p, r in enumerate([run[i] for run in runs])]}
                for i, c in enumerate(cases)
            ],
            "summary": {
                "n_cases": n,
                "core_accuracy": [sum(1 for r in results if r["core_ok"]) for results in runs],
                "extras_accuracy": sum(1 for r in first if r["extras_ok"]),
                "extras_total": et,
                "reproducible": sum(1 for x in repro if x) if args.passes >= 2 else None,
                "title_diffs": title_diffs,
                "runtime_s": round(time.monotonic() - started),
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nReport written to {args.report}")

    if call_errors:
        print(f"\n{call_errors} Gemini call(s) failed after retries")
        sys.exit(1)


if __name__ == "__main__":
    main()
