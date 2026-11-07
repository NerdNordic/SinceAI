"""Quality evaluation of the interpretation step: golden questions -> chart specifications.

Every question has an expected interpretation (metric, dimensions, filters, or "ask back" / "chat").
Each question is sent to Gemini `repeats` times without the cache, which measures:

  accuracy     first interpretation matches the expectation
  consistency  every repeat gives the same interpretation (same metric, dimensions, filters)
  safety       questions with no governed data end in a clarifying question, never in a guess

Numbers are not part of this evaluation: they are computed in code and covered by the unit tests
(which check them against pandas computed straight from the Excel workbook).
"""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import config
from .db import get_db
from .spec import PROMPT_VERSION, ChartSpec, daily_quota_exhausted, generate_spec

QUESTIONS = Path(__file__).resolve().parent.parent / "eval" / "questions.json"
FILTER_KEYS = ("product_ids", "market_ids", "plants")


def load_questions(path: Path | str | None = None) -> list[dict[str, Any]]:
    return json.loads(Path(path or QUESTIONS).read_text(encoding="utf-8"))["questions"]


def outcome(spec: ChartSpec) -> str:
    if spec.mode == "chat":
        return "chat"
    if not spec.understood or spec.metric == "UNSUPPORTED":
        return "clarify"
    return "data"


def interpretation(spec: ChartSpec) -> dict[str, Any]:
    """The parts of a specification that decide which numbers the user gets (titles and wording excluded)."""
    out = outcome(spec)
    if out != "data":
        return {"outcome": out}
    f = spec.filters
    return {"outcome": "data", "metric": spec.metric, "dimensions": sorted(spec.dimensions),
            "product_ids": sorted(f.product_ids), "market_ids": sorted(f.market_ids), "plants": sorted(f.plants),
            "statuses": sorted(f.statuses), "actuals_only": spec.actuals_only}


def score(q: dict[str, Any], spec: ChartSpec) -> list[str]:
    """Problems found; an empty list means the interpretation is correct."""
    exp = q["expect"]
    got = interpretation(spec)
    want_outcome = exp.get("outcome", "data")
    if got["outcome"] != want_outcome:
        detail = f" ({spec.metric})" if got["outcome"] == "data" else ""
        return [f"outcome {got['outcome']}{detail}, expected {want_outcome}"]
    if want_outcome != "data":
        return []
    problems = []
    if got["metric"] != exp["metric"]:
        problems.append(f"metric {got['metric']}, expected {exp['metric']}")
    if "dimensions" in exp and got["dimensions"] != sorted(exp["dimensions"]):
        problems.append(f"dimensions {got['dimensions']}, expected {sorted(exp['dimensions'])}")
    role = config.ROLES[q["role"]]
    for key in FILTER_KEYS:
        want = sorted(exp.get("filters", {}).get(key, []))
        if key == "plants" and not want and role["plant"]:
            want = [role["plant"]]       # factory roles are scoped to their plant by default
        if key == "market_ids" and not want and role.get("markets"):
            want = sorted(role["markets"])   # market roles are scoped to their market by default
        if got[key] != want:
            problems.append(f"{key} {got[key]}, expected {want}")
    missing = sorted(set(exp.get("statuses_include", [])) - set(got["statuses"]))
    if missing:
        problems.append(f"statuses {got['statuses']} missing {missing}")
    want_actuals = exp.get("actuals_only", False)
    if want_actuals is not None and got["actuals_only"] != want_actuals:
        problems.append(f"actuals_only {got['actuals_only']}, expected {want_actuals}")
    return problems


def _rate(n: int, total: int) -> float | None:
    return round(n / total, 3) if total else None


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    def group(key: str) -> dict[str, dict[str, Any]]:
        g: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in results:
            g[r[key]].append(r)
        return {k: {"passed": sum(x["passed"] for x in v), "total": len(v),
                    "accuracy": _rate(sum(x["passed"] for x in v), len(v))} for k, v in sorted(g.items())}

    total = len(results)
    passed = sum(r["passed"] for r in results)
    consistent = sum(r["consistent"] for r in results)
    unsupported = [r for r in results if r["expect"].get("outcome") == "clarify"]
    guessed = [r for r in unsupported if r["got"].get("outcome") == "data"]
    return {
        "total": total, "passed": passed, "accuracy": _rate(passed, total),
        "consistent": consistent, "consistency": _rate(consistent, total),
        "unsupported_total": len(unsupported), "unsupported_guessed": len(guessed),
        "errors": sum(1 for r in results if r.get("error")),
        "by_category": group("category"), "by_language": group("lang"), "by_role": group("role"),
    }


def run(repeats: int = 2, delay: float = 4.0, language: str = "fi", limit: int | None = None,
        only: list[str] | None = None, progress: Callable[[dict[str, Any]], None] | None = None,
        store: bool = True) -> dict[str, Any]:
    """Ask every golden question `repeats` times (no cache), score it, store the run in MongoDB."""
    questions = load_questions()
    if only:
        questions = [q for q in questions if q["id"] in only]
    if limit:
        questions = questions[:limit]
    started = datetime.now(timezone.utc)
    results = []
    stopped = None
    for q in questions:
        specs: list[ChartSpec] = []
        error = None
        try:
            for i in range(max(1, repeats)):
                try:
                    spec, _ = generate_spec(q["question"], q["role"], [], language, use_cache=False)
                    specs.append(spec)
                except Exception as exc:  # noqa: BLE001 - recorded as a failed question
                    if daily_quota_exhausted(exc):
                        stopped = "Gemini daily quota exhausted"
                    else:
                        error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    break
                finally:
                    if delay:
                        time.sleep(delay)
        except KeyboardInterrupt:
            stopped = "interrupted"
        if stopped:
            break   # the unfinished question is left out; the questions already done are kept
        if specs:
            first = specs[0]
            problems = score(q, first)
            got = {**interpretation(first), "title": first.title,
                   "text": first.reply or first.clarification_question or ""}
            consistent = all(interpretation(s) == interpretation(first) for s in specs[1:]) and not error
        else:
            problems, got, consistent = [error or "no answer"], {"outcome": "error"}, False
        r = {"id": q["id"], "role": q["role"], "lang": q["lang"], "category": q["category"],
             "question": q["question"], "expect": q["expect"], "got": got, "passed": not problems,
             "problems": problems, "consistent": consistent, "repeats": len(specs), "error": error}
        results.append(r)
        if progress:
            progress(r)
    doc = {"_id": uuid.uuid4().hex[:12], "started_at": started, "finished_at": datetime.now(timezone.utc),
           "model": config.GEMINI_MODEL, "prompt_version": PROMPT_VERSION, "language": language,
           "repeats": repeats, "summary": summarize(results), "results": results,
           "complete": stopped is None, "stopped": stopped, "planned": len(questions)}
    if store:
        get_db().eval_runs.insert_one(doc)
    return doc


def latest() -> dict[str, Any] | None:
    return get_db().eval_runs.find_one({}, sort=[("started_at", -1)])


def history(limit: int = 10) -> list[dict[str, Any]]:
    return list(get_db().eval_runs.find({}, {"results": 0}).sort("started_at", -1).limit(limit))
