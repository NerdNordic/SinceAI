"""Deterministic calculation adapter for n8n; no LLM or registry writes."""

from __future__ import annotations

import io
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import config, metrics
from .db import lookups
from .spec import ChartSpec, Filters, Status


class ReplenishmentFilters(Filters):
    model_config = ConfigDict(extra="forbid")
    product_ids: list[str] = Field(default_factory=list, max_length=100)
    market_ids: list[str] = Field(default_factory=list, max_length=100)
    plants: list[str] = Field(default_factory=list, max_length=100)
    statuses: list[Status] = Field(default_factory=list, max_length=5)


class ReplenishmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["Replenishment Reorder-By Date"]
    filters: ReplenishmentFilters = Field(default_factory=ReplenishmentFilters)
    dimensions: list[Literal["product", "market", "plant"]] = Field(default_factory=list, max_length=2)
    title: str = Field(default="Replenishment", max_length=1000)
    chart_type: Literal["bar", "table"] = "bar"


class ReplenishmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    sessionId: UUID
    role: str = Field(max_length=64)
    spec: ReplenishmentSpec


def calculate(body: ReplenishmentIn) -> dict:
    if body.role not in config.ROLES:
        raise HTTPException(400, "Unknown role")
    spec = ChartSpec.model_validate(body.spec.model_dump())
    lookups.cache_clear()
    lk = lookups()
    for requested, allowed in ((spec.filters.product_ids, lk["products"]),
                               (spec.filters.market_ids, lk["markets"]),
                               (spec.filters.plants, lk["plants"])):
        if any(value not in allowed for value in requested):
            raise HTTPException(400, "Unknown product, market or plant filter")
    plant = config.ROLES[body.role]["plant"]
    if plant:
        if any(value != plant for value in spec.filters.plants):
            raise HTTPException(403, "Requested plant is outside the permitted scope")
        spec.filters.plants = [plant]
    # No saved results, chart registration, approval creation or Gemini calls.
    metrics.replenishment_results(refresh=True)
    result = metrics.compute(spec)
    old_chart = result["chart"]
    traces = [{"type": "bar", "name": dataset["label"],
               "x": old_chart["labels"], "y": dataset["data"]}
              for dataset in old_chart["datasets"]]
    raw = metrics.raw_rows(result["source"])
    # Keep the CSV to the same eligible pairs used by the replenishment model.
    pairs = {(r["product_id"], r["market_id"])
             for r in metrics.filter_replenishment(spec) if r["status"] != "NO_SHIPMENTS"}
    if not raw.empty:
        raw = raw[[pair in pairs for pair in zip(raw.product_id, raw.market_id)]]
    buf = io.StringIO()
    raw.to_csv(buf, index=False)
    receipt = {**result["receipt"], "source_row_count": len(raw)}
    return {"request_id": str(body.request_id), "sessionId": str(body.sessionId),
            "title": spec.title, "spec": spec.model_dump(),
            "chart": {"data": traces, "layout": {"title": {"text": spec.title},
                      "yaxis": {"title": {"text": result["unit"]}}}},
            "table": result["rows"], "csv": buf.getvalue(), "receipt": receipt,
            "data_quality_warnings": [
                {"code": "REPLENISHMENT_DATA_QUALITY", "kpi_ids": ["MET-REORDER-BY-001"], "detail": warning}
                for warning in receipt.get("warnings", [])]}
