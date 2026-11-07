"""Question -> chart specification with Gemini structured output.

Gemini only interprets the question; it never sees or produces numbers. Responses are cached in
MongoDB (llm_cache) so a demo run is repeatable and does not hit rate limits twice.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import config

PROMPT_VERSION = "v1"

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
    understood: bool = True
    clarification_question: str = ""
    metric: MetricName
    dimensions: list[Literal["month", "market", "product", "plant"]] = Field(default_factory=list)
    filters: Filters = Field(default_factory=Filters)
    intent: Literal["recurring", "one_off"] = "recurring"
    chart_type: Literal["line", "bar", "table"] = "bar"
    actuals_only: bool = False
    title: str = ""


def _prompt(question: str, role: str, hints: list[str]) -> str:
    from .db import lookups
    from .metrics import metric_catalog_for_prompt

    lk = lookups()
    r = config.ROLES[role]
    products = ", ".join(f"{k}={v}" for k, v in lk["products"].items())
    markets = ", ".join(f"{k}={v}" for k, v in lk["markets"].items())
    hint = f"Vector search over the KPI catalogue suggests: {', '.join(hints)}." if hints else ""
    return f"""You turn a user's question into a chart specification for a governed analytics assistant.
User role: {r['label']}. Their plant: {r['plant'] or 'all plants'}.
Data: monthly January-October 2026 per product x market. Each product x market is supplied by one plant.

Allowed metrics (choose exactly one; choose UNSUPPORTED if none fits; never invent a metric):
{metric_catalog_for_prompt()}
{hint}

Products: {products}
Markets: {markets}
Plants: {', '.join(lk['plants'])}

Rules:
- dimensions: "month" for trends over time, "market" per country, "product" per product, "plant" per plant. At most 2.
- filters: only products, markets, plants or statuses the user explicitly names. Map country names (also Finnish, e.g. Suomi=FI, Ruotsi=SE, Saksa=DE) to market ids.
- Running out of stock, what to order, reorder dates, production priorities -> "Replenishment Reorder-By Date".
  "now / this week / urgent" -> statuses STOCKOUT_RISK, ORDER_NOW (add URGENT for "soon / next two weeks").
- intent "one_off" for a single quick number ("mikä on ... nyt"); "recurring" for charts, trends, comparisons, lists to follow.
- actuals_only true only if the user asks for actuals (toteuma).
- chart_type: "line" for trends over months, "bar" for comparisons, "table" for lists of items.
- If the question is ambiguous or outside the allowed metrics: understood=false and a short clarification_question in Finnish.
- title: short title in Finnish.

Question: \"\"\"{question}\"\"\""""


def _kpi_hints(question: str) -> list[str]:
    try:
        import vector_store as vs

        from .db import get_db

        return [h["canonical_metric"] for h in vs.search_kpis(get_db(), question, limit=3)]
    except Exception:  # noqa: BLE001 - hints are optional
        return []


def _call_gemini(prompt: str) -> ChartSpec:
    from google.genai import types

    import vector_store as vs

    client = vs._gemini()
    for attempt in range(5):
        try:
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=ChartSpec, temperature=0),
            )
            parsed = getattr(resp, "parsed", None)
            return parsed if isinstance(parsed, ChartSpec) else ChartSpec.model_validate_json(resp.text)
        except Exception as exc:  # noqa: BLE001
            if attempt == 4:
                raise
            limited = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            time.sleep(vs._retry_delay(exc) or (30 if limited else 2 ** attempt))
    raise RuntimeError("unreachable")


def _sanitize(spec: ChartSpec, role: str) -> ChartSpec:
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
        spec.title = spec.metric
    return spec


def generate_spec(question: str, role: str) -> tuple[ChartSpec, dict[str, Any]]:
    from .db import get_db

    if role not in config.ROLES:
        raise ValueError(f"unknown role {role}")
    db = get_db()
    key = hashlib.sha256(f"{PROMPT_VERSION}|{config.GEMINI_MODEL}|{role}|{question.strip().lower()}".encode()).hexdigest()
    cached = db.llm_cache.find_one({"_id": key})
    if cached:
        return _sanitize(ChartSpec.model_validate(cached["spec"]), role), {"cached": True, "hints": cached.get("hints", [])}
    hints = _kpi_hints(question)
    spec = _call_gemini(_prompt(question, role, hints))
    db.llm_cache.replace_one(
        {"_id": key},
        {"_id": key, "question": question, "role": role, "spec": spec.model_dump(), "hints": hints,
         "model": config.GEMINI_MODEL, "created_at": datetime.now(timezone.utc)},
        upsert=True,
    )
    return _sanitize(spec, role), {"cached": False, "hints": hints}
