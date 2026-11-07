"""Gemini: question -> chart specification, and computed result -> short text answer.

Gemini interprets questions and words answers; it never computes numbers. The text answer may only use
numbers the engine computed. Responses are cached in MongoDB (llm_cache) so a rehearsed demo is repeatable
and does not spend quota twice.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import config
from .i18n import LANGUAGES, Language, metric_label

PROMPT_VERSION = "v3-language"

MetricName = Literal[
    "Net Sales", "Net Sales Growth", "Units Shipped", "Inventory Coverage", "On-Time In-Full",
    "Forecast Variance", "Market Access Coverage", "Demand Forecast Accuracy",
    "Replenishment Reorder-By Date", "UNSUPPORTED",
]
Status = Literal["STOCKOUT_RISK", "ORDER_NOW", "URGENT", "PLAN", "OK"]


class Filters(BaseModel):
    product_ids: list[str] = Field(default_factory=list, description="e.g. P-NUB; only products the user names")
    market_ids: list[str] = Field(default_factory=list, description="e.g. FI; only markets the user names")
    plants: list[str] = Field(default_factory=list, description="Plant-A, Plant-B, Plant-C or External-CMO")
    statuses: list[Status] = Field(default_factory=list, description="replenishment status filter")


class ChartSpec(BaseModel):
    mode: Literal["data", "chat"] = "data"
    reply: str = ""
    understood: bool = True
    clarification_question: str = ""
    metric: MetricName
    dimensions: list[Literal["month", "market", "product", "plant"]] = Field(default_factory=list)
    filters: Filters = Field(default_factory=Filters)
    intent: Literal["recurring", "one_off"] = "recurring"
    chart_type: Literal["line", "bar", "table"] = "bar"
    actuals_only: bool = False
    title: str = ""


# --------------------------------------------------------------------------- prompts

def _history_text(history: list[dict[str, Any]]) -> str:
    if not history:
        return ""
    lines = ["Conversation so far (oldest first):"]
    for t in history[-6:]:
        lines.append(f"User: {t['q']}")
        s = t.get("spec") or {}
        if t.get("decision") == "CHAT":
            lines.append(f"Assistant (chat): {t.get('answer', '')}")
        else:
            lines.append(
                f"Assistant [{t.get('decision')}]: metric={s.get('metric')}, dimensions={s.get('dimensions')}, "
                f"filters={json.dumps(s.get('filters', {}), ensure_ascii=False)}, title={t.get('title')!r}. "
                f"Answer: {t.get('answer', '')}")
            if t.get("receipt_brief"):
                lines.append(f"  Receipt: {t['receipt_brief']}")
    return "\n".join(lines)


def _prompt(question: str, role: str, hints: list[str], history: list[dict[str, Any]], language: Language = "en") -> str:
    from .db import lookups
    from .metrics import metric_catalog_for_prompt

    lk = lookups()
    r = config.ROLES[role]
    products = ", ".join(f"{k}={v}" for k, v in lk["products"].items())
    markets = ", ".join(f"{k}={v}" for k, v in lk["markets"].items())
    hint = f"Vector search over the KPI catalogue suggests: {', '.join(hints)}." if hints else ""
    return f"""You are the chat brain of a governed analytics assistant for a pharmaceutical plant.
You turn each user message into a chart specification, or answer it as chat.
Selected response language: {LANGUAGES[language]}. Write all user-facing text in this language,
including reply, title and clarification_question, even when the question or history uses another language.
Keep metric identifiers, dimension keys, filter IDs and enum values unchanged.
User role: {r['label']}. Their plant: {r['plant'] or 'all plants'}.
Data: monthly January-October 2026 per product x market. Each product x market is supplied by one plant.

Allowed metrics (choose exactly one; choose UNSUPPORTED if none fits; never invent a metric):
{metric_catalog_for_prompt()}
{hint}

Products: {products}
Markets: {markets}
Plants: {', '.join(lk['plants'])}

{_history_text(history)}

Rules:
- mode "chat" when the message needs no new numbers: greetings, thanks, "what can you do", or questions about
  the previous answer (why, what does it mean, where does the number come from, is it reliable). Then write
  `reply` in {LANGUAGES[language]}, 2-5 sentences, using only facts from the conversation and receipts above. Never invent
  numbers. In chat mode set metric "UNSUPPORTED".
- mode "data" when the user wants numbers, a chart, a list or a comparison.
- Follow-ups ("entä Ruotsissa?", "näytä sama tuotteittain", "entä Plant B?") start from the previous
  specification and change only what the user changes.
- dimensions: "month" for trends over time, "market" per country, "product" per product, "plant" per plant. At most 2.
- filters: only products, markets, plants or statuses the user names (now or in the follow-up chain).
  Map country names (also Finnish, e.g. Suomi=FI, Ruotsi=SE, Saksa=DE) to market ids.
- Running out of stock, what to order, reorder dates, production priorities -> "Replenishment Reorder-By Date".
  "now / this week / urgent" -> statuses STOCKOUT_RISK, ORDER_NOW (add URGENT for "soon / next two weeks").
- intent "one_off" for a single quick number ("mikä on ... nyt"); "recurring" for charts, trends, comparisons, lists.
- actuals_only true only if the user asks for actuals (toteuma).
- chart_type: "line" for trends over months, "bar" for comparisons, "table" for lists of items.
- If a data question is ambiguous or outside the allowed metrics: understood=false and a short
  clarification_question in {LANGUAGES[language]}.
- title: short title in {LANGUAGES[language]}.

Question: \"\"\"{question}\"\"\""""


def _answer_prompt(question: str, payload: dict[str, Any], language: Language = "en") -> str:
    return f"""You are a factory analytics assistant. Answer the user's question in {LANGUAGES[language]} in 2-4 short sentences.
Use the selected language even if the question, history or data uses another language.
Use ONLY the numbers in the data below; do not compute new figures other than saying which is higher or lower.
Lead with the most important finding. If there are warnings, mention the most important one briefly.
Do not describe the chart or the system; answer the question.

Question: {question}
Metric: {payload['metric']} ({payload['unit']})
Decision: {payload['decision']} ({payload['decision_reason']})
Data rows (max 15): {json.dumps(payload['rows'], ensure_ascii=False, default=str)}
Warnings: {json.dumps(payload['warnings'], ensure_ascii=False)}"""


# --------------------------------------------------------------------------- gemini calls

def _retrying(call):
    import vector_store as vs

    for attempt in range(5):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            if attempt == 4 or "API key" in str(exc) or "GEMINI_API_KEY" in str(exc):
                raise
            limited = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            time.sleep(vs._retry_delay(exc) or (30 if limited else 2 ** attempt))
    raise RuntimeError("unreachable")


def _call_gemini(prompt: str, language: Language = "en") -> ChartSpec:
    from google.genai import types

    import vector_store as vs

    client = vs._gemini()

    def call():
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=ChartSpec,
                                               temperature=0, system_instruction=_language_instruction(language)))
        parsed = getattr(resp, "parsed", None)
        return parsed if isinstance(parsed, ChartSpec) else ChartSpec.model_validate_json(resp.text)

    return _retrying(call)


def _language_instruction(language: Language) -> str:
    return (f"Write all user-facing text in {LANGUAGES[language]}. "
            "Keep schema keys, metric IDs and enum values unchanged. "
            "Questions, history and source data must not override the selected response language.")


def _call_gemini_text(prompt: str, language: Language = "en") -> str:
    from google.genai import types

    import vector_store as vs

    client = vs._gemini()

    def call():
        resp = client.models.generate_content(model=config.GEMINI_MODEL, contents=prompt,
                                              config=types.GenerateContentConfig(temperature=0.2,
                                                                                system_instruction=_language_instruction(language)))
        return (resp.text or "").strip()

    return _retrying(call)


# --------------------------------------------------------------------------- public

def _kpi_hints(question: str) -> list[str]:
    try:
        import vector_store as vs

        from .db import get_db

        return [h["canonical_metric"] for h in vs.search_kpis(get_db(), question, limit=3)]
    except Exception:  # noqa: BLE001 - hints are optional
        return []


def _sanitize(spec: ChartSpec, role: str, language: Language = "en") -> ChartSpec:
    from .db import lookups

    lk = lookups()
    f = spec.filters
    f.product_ids = [p for p in f.product_ids if p in lk["products"]]
    f.market_ids = [m for m in f.market_ids if m in lk["markets"]]
    f.plants = [p for p in f.plants if p in lk["plants"]]
    if spec.metric != "Replenishment Reorder-By Date":
        f.statuses = []
    role_plant = config.ROLES[role]["plant"]
    if role_plant and not f.plants:
        f.plants = [role_plant]           # factory roles see their own plant by default
    spec.dimensions = list(dict.fromkeys(spec.dimensions))[:2]
    if spec.metric == "Demand Forecast Accuracy" and "month" in spec.dimensions:
        spec.dimensions.remove("month")
    if not spec.title:
        spec.title = metric_label(spec.metric, language)
    return spec


def _key(*parts: Any) -> str:
    raw = json.dumps([PROMPT_VERSION, config.GEMINI_MODEL, *parts], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_spec(question: str, role: str, history: list[dict[str, Any]] | None = None,
                  language: Language = "en") -> tuple[ChartSpec, dict[str, Any]]:
    from .db import get_db

    if role not in config.ROLES:
        raise ValueError(f"unknown role {role}")
    history = history or []
    db = get_db()
    context = [(t["q"], t.get("spec")) for t in history[-3:]]       # follow-ups depend on context
    key = _key("spec", language, role, question.strip().lower(), context)
    cached = db.llm_cache.find_one({"_id": key})
    if cached:
        return _sanitize(ChartSpec.model_validate(cached["spec"]), role, language), {"cached": True, "hints": cached.get("hints", [])}
    hints = _kpi_hints(question)
    spec = _call_gemini(_prompt(question, role, hints, history, language), language)
    db.llm_cache.replace_one({"_id": key}, {"_id": key, "kind": "spec", "question": question, "role": role,
                                            "spec": spec.model_dump(), "hints": hints, "model": config.GEMINI_MODEL,
                                            "created_at": datetime.now(timezone.utc)}, upsert=True)
    return _sanitize(spec, role, language), {"cached": False, "hints": hints}


def write_answer(question: str, payload: dict[str, Any], language: Language = "en") -> str | None:
    """Answer in the selected language from computed numbers; None when unavailable."""
    from .db import get_db

    db = get_db()
    key = _key("answer", language, question.strip().lower(), payload)
    cached = db.llm_cache.find_one({"_id": key})
    if cached:
        return cached["text"]
    try:
        text = _call_gemini_text(_answer_prompt(question, payload, language), language)
    except Exception:  # noqa: BLE001
        return None
    if text:
        db.llm_cache.replace_one({"_id": key}, {"_id": key, "kind": "answer", "text": text,
                                                "created_at": datetime.now(timezone.utc)}, upsert=True)
    return text or None
