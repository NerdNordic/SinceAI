"""Small, deterministic intake gate in front of the existing single-metric engine."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, model_validator

from .i18n import Language

if TYPE_CHECKING:
    from .spec import ChartSpec


class IntakeQuestion(BaseModel):
    id: str = Field(max_length=80)
    field: Literal["metric", "scope", "time", "definition", "usage", "business_decision", "audience", "capability", "routing"]
    text: str = Field(max_length=600)


class RequestBrief(BaseModel):
    original_request: str = Field(default="", max_length=12000)
    business_decision: str | None = None
    audience: str | None = None
    usage: Literal["unknown", "one_off", "recurring"] = "unknown"
    requested_metrics: list[str] = Field(default_factory=list, max_length=24)
    selected_metric: str | None = None
    product_ids: list[str] = Field(default_factory=list, max_length=100)
    market_ids: list[str] = Field(default_factory=list, max_length=100)
    plants: list[str] = Field(default_factory=list, max_length=50)
    scope: Literal["unknown", "default", "explicit", "global", "regional"] = "unknown"
    regions: list[str] = Field(default_factory=list, max_length=20)
    period: Literal["unknown", "all_available", "range", "relative", "latest"] = "unknown"
    start_month: str | None = None
    end_month: str | None = None
    granularity: Literal["unknown", "total", "month", "quarter", "year"] = "unknown"
    comparison: Literal["none", "mom", "yoy", "custom", "unknown"] = "none"
    actual_forecast: Literal["unknown", "all", "actual_only", "forecast_only"] = "unknown"
    unresolved_terms: list[str] = Field(default_factory=list, max_length=24)
    missing_information: list[str] = Field(default_factory=list, max_length=24)
    unsupported: list[str] = Field(default_factory=list, max_length=24)
    questions: list[IntakeQuestion] = Field(default_factory=list, max_length=2)
    mode: Literal["auto", "grill"] = "auto"
    new_asset: bool = False


class Alternative(BaseModel):
    id: str
    label: str
    metric: str | None = None
    all_available: bool = False
    global_scope: bool = False


class SuggestionChanges(BaseModel):
    """Untrusted model-proposed changes; validated before storing and applying."""
    model_config = {"extra": "forbid", "strict": True}
    selected_metric: str | None = None
    usage: Literal["one_off", "recurring"] | None = None
    market_ids: list[str] | None = Field(default=None, max_length=100)
    product_ids: list[str] | None = Field(default=None, max_length=100)
    plants: list[str] | None = Field(default=None, max_length=50)
    business_decision: str | None = Field(default=None, max_length=300)
    audience: str | None = Field(default=None, max_length=300)
    period: Literal["all_available", "range", "relative", "latest"] | None = None
    start_month: str | None = None
    end_month: str | None = None
    granularity: Literal["total", "month", "quarter", "year"] | None = None
    comparison: Literal["none", "mom", "yoy", "custom"] | None = None


class ClarificationSuggestion(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    question_id: str = Field(default="", max_length=80)
    label: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=1, max_length=300)
    changes: SuggestionChanges = Field(default_factory=SuggestionChanges)

    def public(self):
        return self.model_dump(exclude={"changes"})


class ModelClarification(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    question: IntakeQuestion
    suggestions: list[ClarificationSuggestion] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def bind_answers_to_question(self):
        for suggestion in self.suggestions:
            if not suggestion.question_id:
                suggestion.question_id = self.question.id
        return self


class PendingRequest(BaseModel):
    original_request: str
    brief: RequestBrief
    unresolved_questions: list[IntakeQuestion] = Field(default_factory=list)
    latest_questions: list[IntakeQuestion] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    draft_spec: dict = Field(default_factory=dict)
    suggestions: list[ClarificationSuggestion] = Field(default_factory=list, max_length=4)
    suggestion_language: Language | None = None
    outcome: Literal["ASK", "READY", "UNSUPPORTED"] = "ASK"


def message(key: str, language: Language, **values) -> str:
    """App-owned limitations/questions; no extra LLM translation call."""
    en, fi = MESSAGES[key]
    return (fi if language == "fi" else en).format(**values)


MESSAGES = {
    "describe": ("What analytics do you need, and what decision should they support?", "Mitä analytiikkaa tarvitset ja mitä päätöstä sen pitäisi tukea?"),
    "metric": ("Which measure would you like to use?", "Minkä mittarin perusteella haluat tarkastella tilannetta?"),
    "multiple": ("This execution path handles one metric at a time. The full request is retained: {metrics}. Select the first metric or explicitly accept a narrower scope.", "Tämä suorituspolku käsittelee yhden mittarin kerrallaan. Koko pyyntö säilytetään: {metrics}. Valitse ensimmäinen mittari tai hyväksy rajatumpi pyyntö."),
    "unsupported": ("The requested metric or capability is not implemented here: {items}. This is an implementation limitation, not proof that source data is missing.", "Pyydettyä mittaria tai ominaisuutta ei ole toteutettu tässä: {items}. Tämä on toteutuksen rajoitus, ei todiste lähdedatan puuttumisesta."),
    "invalid": ("Unknown or conflicting scope identifiers: {items}. Please correct them; the query has not been broadened.", "Tuntemattomia tai ristiriitaisia rajauksia: {items}. Korjaa ne; hakua ei ole laajennettu."),
    "scope": ("Choose explicit supported product/market IDs or global scope; regional expansion is not implemented.", "Valitse tuote-/markkinatunnukset tai maailmanlaajuinen rajaus; aluelaajennusta ei ole toteutettu."),
    "time": ("Arbitrary periods, forecast-only results, quarterly/yearly aggregation and custom comparisons are not implemented by this path. May I use the supported all-available-data view instead?", "Vapaita ajanjaksoja, pelkkiä ennusteita, neljännes-/vuosikoosteita tai mukautettuja vertailuja ei ole toteutettu tässä. Käytetäänkö tuettua näkymää kaikesta saatavilla olevasta datasta?"),
    "missing_year": ("Year-over-year comparison needs prior-year data; the selected source data does not contain the required history. This path currently computes month-over-month growth only.", "Vuosivertailu tarvitsee edellisvuoden dataa, jota valittu lähdehistoria ei sisällä. Tämä polku laskee vain kuukausikasvun."),
    "definition": ("What do you mean by “{terms}” here? Choose the measure you want to use.", "Mitä tarkoitat ilmauksella ”{terms}”? Valitse mittari, jonka perusteella haluat tarkastella tilannetta."),
    "details": ("What would you like to find out, and what information should we use?", "Mitä haluat selvittää, ja minkä tiedon perusteella?"),
    "usage": ("Would a one-off answer suffice, or is this a recurring analytics need?", "Riittääkö kertavastaus vai onko tarve toistuva?"),
    "decision": ("What business decision will this support?", "Mitä liiketoimintapäätöstä tämä tukee?"),
    "audience": ("Who will use this recurring view?", "Kuka käyttää tätä toistuvaa näkymää?"),
    "all_data": ("Use all available data with the existing metric definition", "Käytä kaikkea saatavilla olevaa dataa nykyisellä mittarimääritelmällä"),
    "global": ("Use global market scope", "Käytä maailmanlaajuista markkinarajausta"),
    "failed": ("Interpretation is temporarily unavailable. Your pending request is unchanged; please retry.", "Tulkinta ei ole juuri nyt käytettävissä. Keskeneräinen pyyntösi säilyi muuttumattomana; yritä uudelleen."),
    "abandoned": ("The pending request was abandoned. You can start a new question.", "Keskeneräinen pyyntö hylättiin. Voit aloittaa uuden kysymyksen."),
    "reuse_verified": ("A registry candidate matches the metric and scope. Consider reusing it before creating another persistent asset.", "Rekisteriehdokas vastaa mittaria ja rajausta. Harkitse sen uudelleenkäyttöä ennen uuden pysyvän kohteen luontia."),
    "reuse_check": ("Retrieved candidates need further scope verification before they can be recommended.", "Löydettyjen ehdokkaiden rajaus on tarkistettava ennen suosittelemista."),
    "reuse_none": ("No suitable candidate was found in the metadata checked; this is not an exhaustive estate search.", "Tarkistetuista metatiedoista ei löytynyt sopivaa ehdokasta; koko raporttikantaa ei ole haettu kattavasti."),
    "reuse_unavailable": ("Existing-asset search was unavailable. We cannot conclude that no suitable report exists.", "Olemassa olevien kohteiden haku ei ollut käytettävissä. Emme voi päätellä, ettei sopivaa raporttia ole."),
}


def normalized(value: str) -> str:
    return re.sub(r"[-–_]", " ", value.casefold()).strip()


@lru_cache(maxsize=1)
def metric_aliases() -> dict[str, list[str]]:
    path = Path(__file__).resolve().parent.parent / "config" / "kpi_aliases.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: [normalized(name), *(normalized(a) for a in aliases)]
            for name, aliases in raw.items() if not name.startswith("_")}


def mentioned_metrics(value: str) -> list[str]:
    value = normalized(value)
    hits = [(m.start(), m.end(), metric) for metric, aliases in metric_aliases().items() for alias in aliases
            for m in re.finditer(rf"\b{re.escape(alias)}\b", value)]
    return list(dict.fromkeys(metric for start, end, metric in sorted(hits, key=lambda h: -(h[1] - h[0]))
                              if not any(left <= start and right >= end and right - left > end - start
                                         for left, right, _ in hits)))


def parse_command(question: str) -> tuple[bool, str]:
    match = re.match(r"^/grill-me(?:\s+(.*))?$", question.strip(), re.I | re.S)
    return (True, (match[1] or "").strip()) if match else (False, question)


def is_replacement(question: str) -> bool:
    return bool(re.match(r"^(?:new request|instead|start over|replace (?:that|the request)|uusi pyyntö|aloita alusta|vaihdetaan aihetta)\b", question.strip(), re.I))


def prepare_brief(brief: RequestBrief, spec: ChartSpec, question: str, pending: PendingRequest | None,
                  mode: Literal["auto", "grill"], replacement: bool = False) -> RequestBrief:
    """Accumulate rather than erase unanswered scope; retain the complete metric wish list."""
    for field in ["business_decision", "audience"]:
        if normalized(getattr(brief, field) or "") in {"", "unknown", "tuntematon"}:
            setattr(brief, field, None)
    old = pending.brief if pending and not replacement else None
    if old:
        for field in RequestBrief.model_fields:
            if field == "questions":
                continue  # Regenerate question wording in the selected response language.
            value = getattr(brief, field)
            if value is None or value == [] or value == "unknown" or value == "":
                setattr(brief, field, getattr(old, field))
        brief.requested_metrics = list(dict.fromkeys([*old.requested_metrics, *brief.requested_metrics]))
        brief.original_request = old.original_request or question
        brief.new_asset = brief.new_asset or old.new_asset
        if old.scope == "global" and brief.scope == "default":
            brief.scope = "global"
        # Unsupported semantics cannot disappear merely because the next model
        # response chooses defaults. Only an explicit alternative below relaxes them.
        for field, blocked in [("period", {"range", "relative", "latest"}), ("comparison", {"yoy", "custom"}),
                               ("actual_forecast", {"forecast_only"}), ("granularity", {"quarter", "year"})]:
            if getattr(old, field) in blocked:
                setattr(brief, field, getattr(old, field))
    else:
        brief.original_request = question
    brief.mode = old.mode if old else mode
    brief.requested_metrics = list(dict.fromkeys([*brief.requested_metrics, *mentioned_metrics(question)]))
    if not brief.requested_metrics and spec.metric != "UNSUPPORTED":
        brief.requested_metrics = [spec.metric]
    # A model cannot approve narrowing on the user's behalf.
    brief.selected_metric = old.selected_metric if old else None
    # Raw deterministic signals supplement model extraction; they never substitute metrics.
    full = normalized(question)
    if re.search(r"\b(global|worldwide|globaal\w*|maailmanlaaj\w*)\b", full):
        brief.scope, brief.market_ids, brief.plants, brief.regions = "global", [], [], []
        if not re.search(r"\b(plant[ -]?[a-z]|external[ -]cmo)\b", full):
            spec.filters.plants = []
    if re.search(r"\b(yoy|year over year|edellisvu\w*|vuosikasvu)\b", full):
        brief.comparison = "yoy"
    if re.search(r"\b20\d{2}(?:[/-]\d{2})?\b", question):
        brief.period = "range"
    if re.search(r"\b(quarter\w*|neljännes\w*)\b", full):
        brief.granularity = "quarter"
    if re.search(r"\b(emea|north america|pohjois amerikka)\b", full):
        brief.scope = "regional"
        brief.regions = brief.regions or [question]
    for term in ["supply risk", "performance", "adoption", "launch readiness", "first sales",
                 "toimitusriski", "suorituskyky", "lanseerausvalmius"]:
        if term in {"performance", "suorituskyky"} and mentioned_metrics(question):
            continue
        if term in full and term not in brief.unresolved_terms:
            brief.unresolved_terms.append(term)
        if term in full and term not in brief.requested_metrics:
            brief.requested_metrics.append(term)
    for capability in ["power bi", "tableau", "pbip"]:
        if capability in full and capability not in brief.unsupported:
            brief.unsupported.append(capability)
    brief.new_asset = brief.new_asset or bool(re.search(r"\b(dashboard|report|raport\w*|kojelauta)\b", full)
                                               and re.search(r"\b(new|build|create|uusi|uuden|luo|rakenna)\b", full))
    if old:
        # Only explicit replies accept a reduced metric scope or a proposed alternative.
        selected = mentioned_metrics(question)
        asked_metric = any(q.field == "metric" or (q.field == "definition" and old.unresolved_terms)
                           for q in pending.latest_questions)
        if (len(selected) == 1 and (selected[0] in old.requested_metrics or asked_metric)
                and not re.search(r"\b(not|don't|ei|älä)\b", full)):
            brief.selected_metric = selected[0]
            brief.unresolved_terms = []
        yes = full in {"yes", "yes please", "ok", "okay", "kyllä", "sopii", "hyväksyn"}
        accepted_time = False
        for alternative in pending.alternatives:
            accepted = (yes and len(pending.alternatives) == 1) or full == normalized(alternative.label)
            if not accepted:
                continue
            if alternative.metric:
                brief.selected_metric = alternative.metric
            if alternative.all_available:
                accepted_time = True
                brief.period, brief.start_month, brief.end_month = "all_available", None, None
                brief.comparison, brief.granularity, brief.actual_forecast = "none", "unknown", "all"
                if spec.metric in {"Demand Forecast Accuracy", "Replenishment Reorder-By Date"}:
                    spec.dimensions = [d for d in spec.dimensions if d != "month"]
            if alternative.global_scope:
                brief.scope, brief.market_ids, brief.plants, brief.regions = "global", [], [], []
                spec.filters.market_ids, spec.filters.plants = [], []
        if not spec.dimensions and brief.granularity != "total" and not accepted_time:
            spec.dimensions = pending.draft_spec.get("dimensions", [])
    if not brief.product_ids:
        brief.product_ids = list(spec.filters.product_ids)
    # Keep explicit product IDs, even when the model accidentally omits them.
    brief.product_ids = list(dict.fromkeys([*brief.product_ids, *re.findall(r"\bP-[A-Z0-9-]+\b", question)]))
    if brief.scope != "global":
        brief.market_ids = brief.market_ids or list(spec.filters.market_ids)
        brief.plants = brief.plants or list(spec.filters.plants)
    elif not re.search(r"\b(plant[ -]?[a-z]|external[ -]cmo)\b", full):
        spec.filters.plants = []
    resolved = {"metric": bool(brief.selected_metric), "definition": bool(brief.selected_metric) and not brief.unresolved_terms,
                "scope": brief.scope in {"explicit", "global"}, "time": brief.period == "all_available",
                "business_decision": bool(brief.business_decision), "audience": bool(brief.audience),
                "usage": brief.usage != "unknown"}
    brief.missing_information = [field for field in brief.missing_information if not resolved.get(field)]
    return brief


def reuse_evidence(spec: ChartSpec, brief: RequestBrief, role: str) -> dict[str, Any]:
    """Read-only, bounded metadata discovery; absence and outages are different outcomes."""
    from .config import ROLES
    from .db import get_db

    metric = brief.selected_metric or (brief.requested_metrics[0] if len(brief.requested_metrics) == 1 else None)
    if not metric:
        return {"status": "not_searched", "candidates": [], "search_failed": False}
    candidates, failed = [], False
    filters = spec.filters.model_dump()
    filters.update(product_ids=brief.product_ids, market_ids=brief.market_ids,
                   plants=[] if brief.scope == "global" else brief.plants or ([ROLES[role]["plant"]] if ROLES[role]["plant"] else []))
    try:
        for row in get_db().chart_registry.find({"spec.metric": metric, "status": {"$in": ["active", "certified"]}}, {"embedding": 0}).limit(5):
            saved = row.get("spec", {})
            suitable = (row.get("filters") == filters and saved.get("dimensions") == spec.dimensions
                        and saved.get("actuals_only", False) == (brief.actual_forecast == "actual_only" or spec.actuals_only)
                        and brief.period in {"unknown", "all_available"} and not brief.regions
                        and brief.comparison in {"none", "mom"} and brief.actual_forecast != "forecast_only"
                        and brief.granularity not in {"quarter", "year"})
            candidates.append({"id": row["fingerprint"], "title": row.get("title", ""), "kind": "registry",
                               "suitability": "verified" if suitable else "needs_verification"})
    except Exception:
        failed = True
    try:
        for row in get_db().analytics_assets.find({"canonical_metrics": metric, "lifecycle_status": "active"},
                                                {"embedding": 0}).limit(3):
            candidates.append({"id": str(row["_id"]), "title": row.get("asset_name", ""), "kind": "catalog",
                               "suitability": "needs_verification"})
    except Exception:
        failed = True
    status = "verified" if any(c["suitability"] == "verified" for c in candidates) else "needs_verification" if candidates else "unavailable" if failed else "none"
    return {"status": status, "candidates": candidates, "search_failed": failed}


def readiness(brief: RequestBrief, spec: ChartSpec, outcome: str, language: Language
              ) -> tuple[str, list[IntakeQuestion], list[str], list[Alternative], list[IntakeQuestion]]:
    """Model READY is advisory. Return material blockers and supported alternatives."""
    from .db import get_db, lookups
    from .metrics import METRICS

    questions, limitations, alternatives = [], [], []

    def block(field, key, **values):
        label = message(key, language, **values)
        limitations.append(label)
        if field not in {q.field for q in questions}:
            questions.append(IntakeQuestion(id=field, field=field, text=label))

    selected = brief.selected_metric
    if len(brief.requested_metrics) > 1 and not selected:
        block("metric", "multiple", metrics=", ".join(brief.requested_metrics))
        alternatives.extend(Alternative(id="metric:" + name, label=name, metric=name) for name in brief.requested_metrics if name in METRICS)
    metric = selected or (brief.requested_metrics[0] if len(brief.requested_metrics) == 1 else spec.metric)
    unsupported = [name for name in brief.requested_metrics if name not in METRICS and name not in brief.unresolved_terms] if not selected else []
    if unsupported or brief.unsupported or outcome == "UNSUPPORTED":
        block("capability", "unsupported", items=", ".join([*unsupported, *brief.unsupported]))
    if metric not in METRICS and not unsupported:
        if brief.unresolved_terms:
            block("metric", "definition", terms=", ".join(brief.unresolved_terms))
        else:
            block("metric", "metric")
    if len(set(spec.dimensions)) > 2:
        block("capability", "unsupported", items="more than two dimensions")
    if spec.filters.statuses and metric != "Replenishment Reorder-By Date":
        block("capability", "unsupported", items="status filter for " + str(metric))
    lk = lookups()
    invalid = ([p for p in [*brief.product_ids, *spec.filters.product_ids] if p not in lk["products"]]
               + [m for m in [*brief.market_ids, *spec.filters.market_ids] if m not in lk["markets"]]
               + [p for p in [*brief.plants, *spec.filters.plants] if p not in lk["plants"]])
    if invalid or (brief.scope == "global" and (spec.filters.market_ids or spec.filters.plants)):
        block("scope", "invalid", items=", ".join(invalid) or "global + filtered markets/plants")
    if brief.scope == "regional" or brief.regions:
        block("scope", "scope")
        alternatives.append(Alternative(id="global", label=message("global", language), global_scope=True))
    if brief.unresolved_terms and not any(q.field == "metric" for q in questions):
        block("definition", "definition", terms=", ".join(brief.unresolved_terms))
    if brief.missing_information:
        material = [field for field in brief.missing_information if field in {"metric", "scope", "time", "definition", "capability"}]
        for field in material:
            if field in {q.field for q in questions}:
                continue
            if field == "metric" and metric in METRICS:
                continue
            if field == "definition" and selected and not brief.unresolved_terms:
                continue
            if field == "definition" and brief.unresolved_terms and any(q.field == "metric" for q in questions):
                continue
            block(field, {"metric": "metric", "scope": "scope", "time": "time"}.get(field, "details"))
    time_limited = brief.period in {"range", "relative"} or brief.granularity in {"quarter", "year"} or brief.actual_forecast == "forecast_only" or brief.comparison == "custom"
    time_limited = time_limited or brief.start_month is not None or brief.end_month is not None
    if brief.comparison == "mom" and metric != "Net Sales Growth":
        time_limited = True
    if brief.comparison == "yoy":
        dates = sorted(str(d)[:7] for d in get_db().product_market_monthly.distinct("month")
                       if re.match(r"^\d{4}-\d{2}", str(d)))
        missing = not dates or not any(str(int(d[:4]) - 1) + d[4:] in dates for d in dates)
        block("time", "missing_year" if missing else "time")
        time_limited = True
    if (metric in {"Demand Forecast Accuracy", "Replenishment Reorder-By Date"} and ("month" in spec.dimensions or brief.granularity == "month")) or (brief.period == "latest" and metric not in {"Demand Forecast Accuracy", "Replenishment Reorder-By Date"}):
        time_limited = True
    if time_limited:
        if not any(q.field == "time" for q in questions):
            block("time", "time")
        alternatives.append(Alternative(id="all_available", label=message("all_data", language), all_available=True))
    if brief.new_asset and brief.usage == "unknown":
        block("usage", "usage")
    if brief.new_asset and brief.usage == "recurring" and not brief.business_decision:
        block("business_decision", "decision")
    if brief.mode == "grill":
        if not brief.business_decision:
            block("business_decision", "decision")
        if brief.usage == "unknown" and not brief.new_asset:
            block("usage", "usage")
        if brief.usage == "recurring" and not brief.audience:
            block("audience", "audience")
    resolved = {"business_decision": bool(brief.business_decision), "audience": bool(brief.audience),
                "usage": brief.usage != "unknown", "metric": bool(selected),
                "definition": bool(selected) and not brief.unresolved_terms}
    if outcome != "READY" or not spec.understood:
        for q in brief.questions:
            if q.field == "definition" and brief.unresolved_terms and any(item.field == "metric" for item in questions):
                continue
            if not resolved.get(q.field) and q.field not in {item.field for item in questions}:
                questions.append(q)
    resolved_selection = selected in METRICS and not brief.unresolved_terms and not brief.unsupported
    if not questions and not brief.questions and (outcome != "READY" or not spec.understood) and not resolved_selection:
        block("definition", "metric")
    for question in questions[:2]:
        if question.text.count("?") > 1:
            question.text = question.text.split("?", 1)[0] + "?"
    return metric, questions[:2], limitations, alternatives, questions
