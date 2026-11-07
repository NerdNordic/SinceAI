"""Bounded contracts at the untrusted n8n/LLM boundary."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Route = Literal["CLARIFY", "REUSE", "EXTEND", "BUILD", "ANSWER"]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class HistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(max_length=64)
    question: str = Field(default="", max_length=4000)
    sessionId: UUID = Field(default_factory=uuid4)
    request_id: UUID = Field(default_factory=uuid4)
    language: Literal["fi", "en"] = "fi"
    history: list[HistoryEntry] = Field(default_factory=list, max_length=32)
    chart_id: Identifier | None = None

    @model_validator(mode="after")
    def question_or_chart(self):
        self.question = self.question.strip()
        if not self.question and not self.chart_id:
            raise ValueError("A question or chart_id is required")
        self.history = self.history[-8:]
        return self


class WarningIn(BaseModel):
    code: str = Field(max_length=128)
    kpi_ids: list[str] = Field(default_factory=list, max_length=100)
    detail: str = Field(max_length=8000)


class PlotlyFigure(BaseModel):
    data: list[dict[str, Any]] = Field(max_length=200)
    layout: dict[str, Any]

    @model_validator(mode="after")
    def local_data_only(self):
        # This UI renders KPI lines/bars/tables, not remote images, maps or URLs.
        for trace in self.data:
            if trace.get("type", "scatter") not in {"scatter", "bar", "table", "indicator", "pie", "heatmap"}:
                raise ValueError("Unsupported KPI trace type")
        def check(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"source", "src", "href", "url", "images", "mapbox", "geo",
                               "__proto__", "constructor", "prototype"}:
                        raise ValueError("External chart resources are not allowed")
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        check(self.data)
        check(self.layout)
        return self


class KPIResponse(BaseModel):
    # Preserve documented extensions; unknown transport fields are not forwarded.
    type: Literal["clarify", "answer", "chart", "build_request"]
    route: Route
    message: str = Field(max_length=16000)
    request_id: UUID
    sessionId: UUID
    data_quality_warnings: list[WarningIn] = Field(max_length=200)
    suggestions: list[str] = Field(default_factory=list, max_length=100)
    chart_id: Identifier | None = None
    chart_status: Literal["active", "pending_approval", "certified", "retired"] | None = None
    approval_id: Identifier | None = None
    fingerprint: str | None = Field(default=None, max_length=256)
    title: str = Field(default="", max_length=1000)
    reason: str = Field(default="", max_length=16000)
    basis: Any = None
    headline: dict[str, Any] | None = None
    chart: PlotlyFigure | None = None
    compact: StrictBool = False
    table: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)
    csv: str = Field(default="", max_length=4_000_000)
    receipt: dict[str, Any] | None = None
    spec: dict[str, Any] | None = None
    related_assets: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    variants_not_used: list[Any] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def consistent_route(self):
        allowed = {"clarify": {"CLARIFY"}, "answer": {"ANSWER", "REUSE"},
                   "chart": {"REUSE", "EXTEND", "BUILD"}, "build_request": {"BUILD"}}
        if self.route not in allowed[self.type]:
            raise ValueError("Response type and route disagree")
        if self.type == "build_request" and not self.approval_id:
            raise ValueError("Build request must identify its approval")
        if self.type == "chart" and not self.chart_id:
            raise ValueError("Registered chart must identify its chart_id")
        return self


class GovernanceResponse(BaseModel):
    status: Literal["pending", "approved", "rejected"]
    approval_id: Identifier
    chart_id: Identifier | None = None
    message: str = Field(default="", max_length=8000)
