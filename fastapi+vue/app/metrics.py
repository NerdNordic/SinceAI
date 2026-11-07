"""Governed metrics: the only place numbers are computed. The LLM never calculates.

Each metric is tied to a canonical KPI from the catalogue (or to the registered replenishment metric)
and every result carries a receipt: KPI, definition, source rows, filters, warnings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import config
from .db import get_db, lookups
from .spec import ChartSpec
from .i18n import Language, calculation_steps, flag_label, metric_label, text, transport_label

ACTUAL = "actual_like_synthetic"
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Metric:
    kpi_id: str
    unit: str
    kind: str                 # sum | mean | growth | variance | snapshot | replenishment
    field: str = ""
    definition: str = ""
    description: str = ""     # for the LLM prompt


METRICS: dict[str, Metric] = {
    "Net Sales": Metric("KPI-001", "M€", "sum", "net_sales_m_eur_syn",
                        "Nettomyynnin summa (M€) valituilta riveiltä.", "net sales / revenue in M€"),
    "Net Sales Growth": Metric("KPI-004", "%", "growth", "net_sales_m_eur_syn",
                               "Nettomyynnin muutos edelliseen kuukauteen (%), laskettuna ryhmän summasta.",
                               "month-over-month growth of net sales"),
    "Units Shipped": Metric("KPI-014", "kpl", "sum", "units_shipped_syn",
                            "Toimitettujen kappaleiden summa.", "shipped units / volume / production output proxy"),
    "Inventory Coverage": Metric("KPI-016", "viikkoa", "mean", "inventory_weeks_syn",
                                 "Varaston riittävyys viikkoina, rivien keskiarvo.", "weeks of inventory cover"),
    "On-Time In-Full": Metric("KPI-020", "%", "mean", "otif_pct_syn",
                              "Ajallaan ja täysimääräisenä toimitettujen osuus (%), rivien keskiarvo.",
                              "OTIF, delivery reliability"),
    "Forecast Variance": Metric("KPI-042", "M€", "variance", "net_sales_m_eur_syn",
                                "Nettomyynti miinus ennuste (M€), ryhmän summista.", "actual minus forecast in M€"),
    "Market Access Coverage": Metric("KPI-027", "%", "mean", "market_access_coverage_pct_syn",
                                     "Markkinoille pääsyn kattavuus (%), rivien keskiarvo.", "market access coverage %"),
    "Demand Forecast Accuracy": Metric("KPI-006", "%", "snapshot", "forecast_accuracy_pct_syn",
                                       "Kysyntäennusteen tarkkuus (%) Supply_Operations-tilannekuvasta, keskiarvo.",
                                       "forecast accuracy (latest snapshot, no monthly history)"),
    "Replenishment Reorder-By Date": Metric("MET-REORDER-BY-001", "päivää tilauspäivään (miinus = myöhässä)", "replenishment", "",
                                            "Milloin varasto loppuu ja mihin mennessä täydennys on tilattava "
                                            "(tuote × markkina), oletukset assumptions.json.",
                                            "runout date and reorder-by date per product x market, stockout risk"),
}

DIM_FIELD = {"month": "month", "market": "market_id", "product": "product_id", "plant": "plant"}


# --------------------------------------------------------------------------- helpers

def _label(dim: str, value: Any) -> str:
    lk = lookups()
    if dim == "product":
        return lk["products"].get(value, value)
    if dim == "market":
        return lk["markets"].get(value, value)
    return str(value)


def _base_query(spec: ChartSpec) -> dict[str, Any]:
    q: dict[str, Any] = {}
    if spec.filters.product_ids:
        q["product_id"] = {"$in": spec.filters.product_ids}
    if spec.filters.market_ids:
        q["market_id"] = {"$in": spec.filters.market_ids}
    return q


def _with_plant(df: pd.DataFrame, spec: ChartSpec) -> pd.DataFrame:
    plant = lookups()["plant"]
    df = df.copy()
    df["plant"] = [plant.get((p, m)) for p, m in zip(df["product_id"], df["market_id"])]
    if spec.filters.plants:
        df = df[df["plant"].isin(spec.filters.plants)]
    return df


def _kpi_receipt(kpi_id: str) -> dict[str, Any]:
    k = lookups()["kpis"].get(kpi_id)
    if not k:
        return {"id": kpi_id}
    return {"id": kpi_id, "name": k["kpi_name"], "definition_status": k["definition_status"],
            "approval_status": k["approval_status"], "unit": k["unit"]}


def _chart(df: pd.DataFrame, dims: list[str], value: str, chart_type: str, metric_name: str) -> dict[str, Any]:
    """Shape rows for the UI: labels + datasets. Limits to the 8 largest series."""
    if df.empty:
        return {"type": chart_type, "labels": [], "datasets": []}
    others = [d for d in dims if d != "month"]
    if "month" in dims:
        labels = sorted(df["month"].unique().tolist())
        if others:
            df = df.assign(_series=df[others].apply(lambda r: " · ".join(_label(d, r[d]) for d in others), axis=1))
            top = df.groupby("_series")[value].mean().abs().sort_values(ascending=False).head(8).index.tolist()
            datasets = []
            for s in top:
                part = df[df["_series"] == s].set_index("month")[value]
                datasets.append({"label": s, "data": [None if pd.isna(part.get(mo)) else round(float(part.get(mo)), 2) for mo in labels]})
        else:
            part = df.set_index("month")[value]
            datasets = [{"label": metric_name, "data": [round(float(part.get(mo)), 2) for mo in labels]}]
        return {"type": "line" if chart_type == "line" else chart_type, "labels": labels, "datasets": datasets}
    df = df.sort_values(value, ascending=False).head(20)
    labels = [" · ".join(_label(d, r[d]) for d in dims) or metric_name for _, r in df.iterrows()]
    return {"type": "bar" if chart_type == "line" else chart_type, "labels": labels,
            "datasets": [{"label": metric_name, "data": [round(float(v), 2) for v in df[value]]}]}


def _readable_rows(df: pd.DataFrame, dims: list[str], value: str) -> list[dict[str, Any]]:
    out = []
    for _, r in df.iterrows():
        row = {d: _label(d, r[d]) for d in dims}
        row["arvo"] = None if pd.isna(r[value]) else round(float(r[value]), 2)
        out.append(row)
    return out


# --------------------------------------------------------------------------- monthly metrics

def _compute_monthly(spec: ChartSpec, m: Metric, language: Language) -> dict[str, Any]:
    db = get_db()
    base = _base_query(spec)
    query = dict(base)
    if spec.actuals_only:
        query["value_type"] = ACTUAL
    fields = {"_id": 0, "product_id": 1, "market_id": 1, "month": 1, "value_type": 1, m.field: 1, "forecast_m_eur_syn": 1}
    df = pd.DataFrame(list(db.product_market_monthly.find(query, fields)))
    warnings: list[str] = []
    if df.empty:
        return _empty(spec, m, query, text("Valinnoilla ei löytynyt rivejä.", language), language)
    df = _with_plant(df, spec)
    if df.empty:
        return _empty(spec, m, query, text("Valitulla tehtaalla ei löytynyt rivejä.", language), language)
    df["month"] = pd.to_datetime(df["month"]).dt.strftime("%Y-%m")

    dims = [d for d in spec.dimensions if d in DIM_FIELD]
    cols = [DIM_FIELD[d] for d in dims]
    renamed = {DIM_FIELD[d]: d for d in dims}

    if m.kind in ("sum", "mean"):
        g = df.groupby(cols)[m.field].agg(m.kind).reset_index() if cols else pd.DataFrame({m.field: [df[m.field].agg(m.kind)]})
        g = g.rename(columns={**renamed, m.field: "value"})
    elif m.kind == "variance":
        agg = df.groupby(cols)[[m.field, "forecast_m_eur_syn"]].sum().reset_index() if cols else df[[m.field, "forecast_m_eur_syn"]].sum().to_frame().T
        agg["value"] = agg[m.field] - agg["forecast_m_eur_syn"]
        g = agg.rename(columns=renamed)[[*dims, "value"]]
    elif m.kind == "growth":
        others = [c for c in cols if c != "month"]
        monthly = df.groupby([*others, "month"])[m.field].sum().reset_index().sort_values("month")
        if others:
            monthly["value"] = monthly.groupby(others)[m.field].pct_change() * 100
        else:
            monthly["value"] = monthly[m.field].pct_change() * 100
        if "month" in cols:
            g = monthly.dropna(subset=["value"])
        else:
            g = monthly.dropna(subset=["value"]).groupby(others, as_index=False).tail(1) if others else monthly.dropna(subset=["value"]).tail(1)
            warnings.append(text("Kasvu = viimeisin kuukausi ({month}) vs. edellinen.", language, month=g["month"].max() if not g.empty else "-"))
        g = g.rename(columns=renamed)[[*dims, "value"]]
    else:
        raise ValueError(m.kind)

    forecast_rows = int((df["value_type"] != ACTUAL).sum())
    if forecast_rows and not spec.actuals_only:
        warnings.append(text("{count}/{total} lähderiviä on ennustetyyppisiä (forecast_like), ei toteumaa.",
                             language, count=forecast_rows, total=len(df)))
    if spec.actuals_only:
        excluded_q = {**base, "value_type": {"$ne": ACTUAL}}
        ex = pd.DataFrame(list(db.product_market_monthly.find(excluded_q, {"_id": 0, "product_id": 1, "market_id": 1})))
        n_ex = len(_with_plant(ex, spec)) if not ex.empty else 0
        if n_ex:
            warnings.append(text("{count} ennustetyyppistä riviä jätettiin pois (vain toteuma).", language, count=n_ex))

    return {
        "metric": spec.metric, "unit": text(m.unit, language),
        "chart": _chart(g, dims, "value", spec.chart_type, metric_label(spec.metric, language)),
        "rows": _readable_rows(g, dims, "value"),
        "receipt": {
            "kpi": _kpi_receipt(m.kpi_id),
            "definition": text(m.definition, language),
            "source": {"collection": "product_market_monthly", "sheet": "Product_Market_Monthly",
                       "rows_used": int(len(df)), "forecast_like_rows": forecast_rows,
                       "months": f"{df['month'].min()} – {df['month'].max()}"},
            "filters": spec.filters.model_dump(), "dimensions": dims,
            "actuals_only": spec.actuals_only,
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "warnings": warnings,
        },
        "source": {"collection": "product_market_monthly", "query": base, "plants": spec.filters.plants,
                   "actuals_only": spec.actuals_only},
    }


def _compute_snapshot(spec: ChartSpec, m: Metric, language: Language) -> dict[str, Any]:
    db = get_db()
    base = _base_query(spec)
    df = pd.DataFrame(list(db.supply_operations.find(base, {"_id": 0})))
    if df.empty:
        return _empty(spec, m, base, text("Valinnoilla ei löytynyt rivejä.", language), language)
    df = df[df["supply_source"].isin(spec.filters.plants)] if spec.filters.plants else df
    df = df.rename(columns={"supply_source": "plant"})
    dims = [d for d in spec.dimensions if d in ("market", "product", "plant")]
    cols = [DIM_FIELD[d] for d in dims]
    g = (df.groupby(cols)[m.field].mean().reset_index() if cols else pd.DataFrame({m.field: [df[m.field].mean()]}))
    g = g.rename(columns={**{DIM_FIELD[d]: d for d in dims}, m.field: "value"})
    warnings = [text("Tilannekuva: kuukausihistoriaa ei ole.", language)] if "month" in spec.dimensions else []
    return {
        "metric": spec.metric, "unit": text(m.unit, language),
        "chart": _chart(g, dims, "value", "bar", metric_label(spec.metric, language)),
        "rows": _readable_rows(g, dims, "value"),
        "receipt": {"kpi": _kpi_receipt(m.kpi_id), "definition": text(m.definition, language),
                    "source": {"collection": "supply_operations", "sheet": "Supply_Operations", "rows_used": int(len(df))},
                    "filters": spec.filters.model_dump(), "dimensions": dims,
                    "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "warnings": warnings},
        "source": {"collection": "supply_operations", "query": base, "plants": spec.filters.plants},
    }


def _empty(spec: ChartSpec, m: Metric, query: dict, note: str, language: Language) -> dict[str, Any]:
    return {"metric": spec.metric, "unit": text(m.unit, language), "chart": {"type": spec.chart_type, "labels": [], "datasets": []},
            "rows": [], "receipt": {"kpi": _kpi_receipt(m.kpi_id), "definition": text(m.definition, language), "warnings": [note],
                                    "filters": spec.filters.model_dump()},
            "source": {"collection": "product_market_monthly", "query": query, "plants": spec.filters.plants}}


# --------------------------------------------------------------------------- replenishment

_repl_cache: dict[tuple, list[dict]] = {}


def replenishment_results() -> list[dict[str, Any]]:
    """Runout / reorder-by dates for every product x market, computed from MongoDB data."""
    from reorder.data import DataPack
    from reorder.model import Assumptions, compute_all

    db = get_db()
    key = (id(db), config.today())
    if key not in _repl_cache:
        strip = {"_id": 0, "_source": 0, "embedding": 0}
        monthly = pd.DataFrame(list(db.product_market_monthly.find({}, strip)))
        monthly["month"] = pd.to_datetime(monthly["month"])
        monthly = monthly.sort_values(["product_id", "market_id", "month"]).reset_index(drop=True)
        pack = DataPack(
            monthly=monthly,
            supply=pd.DataFrame(list(db.supply_operations.find({}, strip))),
            products=pd.DataFrame(list(db.products.find({}, strip))),
            markets=pd.DataFrame(list(db.markets.find({}, strip))),
            kpis=pd.DataFrame(list(db.kpi_catalog.find({}, strip))),
            source_file=f"MongoDB {db.name}",
        )
        _repl_cache[key] = compute_all(pack, Assumptions.load(ROOT / "assumptions.json"), today=config.today())
    return _repl_cache[key]


def filter_replenishment(spec: ChartSpec) -> list[dict[str, Any]]:
    f = spec.filters
    rows = replenishment_results()
    if f.plants:
        rows = [r for r in rows if r["supply_source"] in f.plants]
    if f.product_ids:
        rows = [r for r in rows if r["product_id"] in f.product_ids]
    if f.market_ids:
        rows = [r for r in rows if r["market_id"] in f.market_ids]
    if f.statuses:
        rows = [r for r in rows if r["status"] in f.statuses]
    return rows


def _compute_replenishment(spec: ChartSpec, m: Metric, language: Language) -> dict[str, Any]:
    rows = [r for r in filter_replenishment(spec) if r["status"] != "NO_SHIPMENTS"]
    table = [{
        "tuote": r["product_name"], "markkina": r["market_name"], "tehdas": r["supply_source"], "tila": r["status"],
        "tilaa_viimeistaan": r["reorder_by_recommended"], "viimeinen_mahdollinen": r["reorder_by_latest"],
        "loppuu_arviolta": r["runout_date_p50"], "riittavyys_vk": r["cover_weeks"], "kpl_viikossa": r["weekly_demand_units"],
        "nopeutus": (text("{mode} viimeistään {date}", language, mode=transport_label(r["expedite"]["mode"], language), date=r["expedite"]["latest_order_date"])
                     if r["expedite"] and r["expedite"]["feasible"] else ""),
    } for r in rows]
    top = rows[:20]
    flags = sorted({f for r in rows for f in r["flags"]})
    return {
        "metric": spec.metric, "unit": text(m.unit, language),
        "chart": {"type": "bar", "labels": [f"{r['product_name']} · {r['market_id']}" for r in top],
                  "datasets": [{"label": text("Päiviä suositeltuun tilauspäivään", language), "data": [r["days_to_recommended_order"] for r in top]}]},
        "rows": table,
        "receipt": {
            "kpi": {"id": m.kpi_id, "name": spec.metric, "definition_status": "registered metric",
                    "depends_on": ["KPI-016", "KPI-020", "KPI-006", "KPI-014"]},
            "definition": text(m.definition, language),
            "source": {"collection": "product_market_monthly + supply_operations", "rows_used": len(rows)},
            "assumptions": rows[0]["receipt"]["assumptions_fingerprint"] if rows else None,
            "example_steps": calculation_steps(rows[0]["receipt"]["steps"], language) if rows else [],
            "filters": spec.filters.model_dump(),
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "warnings": [text("Datan laatuliput: {flags}", language,
                              flags=", ".join(flag_label(f, language) for f in flags))] if flags else [],
        },
        "source": {"collection": "replenishment", "query": _base_query(spec), "plants": spec.filters.plants,
                   "statuses": spec.filters.statuses},
    }


# --------------------------------------------------------------------------- entry points

def compute(spec: ChartSpec, language: Language = "en") -> dict[str, Any]:
    m = METRICS[spec.metric]
    if m.kind == "replenishment":
        return _compute_replenishment(spec, m, language)
    if m.kind == "snapshot":
        return _compute_snapshot(spec, m, language)
    return _compute_monthly(spec, m, language)


def raw_rows(source: dict[str, Any]) -> pd.DataFrame:
    """The exact source rows behind a result, with their sheet and Excel row number."""
    db = get_db()
    plant = lookups()["plant"]
    coll = source["collection"]
    query = source.get("query", {})
    names = ["product_market_monthly", "supply_operations"] if coll == "replenishment" else [coll]
    frames = []
    for name in names:
        docs = list(db[name].find(query, {"_id": 0, "embedding": 0}))
        df = pd.DataFrame(docs)
        if df.empty:
            continue
        if "plant" not in df:
            df["plant"] = [plant.get((p, m)) for p, m in zip(df["product_id"], df["market_id"])]
        if source.get("plants"):
            df = df[df["plant"].isin(source["plants"])]
        src = df.pop("_source") if "_source" in df else None
        if src is not None:
            df.insert(0, "excel_row", [s.get("row") for s in src])
            df.insert(0, "sheet", [s.get("sheet") for s in src])
        if source.get("actuals_only") and "value_type" in df:
            df["used"] = df["value_type"] == ACTUAL
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def metric_catalog_for_prompt() -> str:
    lines = []
    for name, m in METRICS.items():
        lines.append(f"- {name} ({m.kpi_id}, {m.unit}): {m.description}")
    return "\n".join(lines)
