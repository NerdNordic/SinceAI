"""Replenishment forecast: runout date and reorder-by date per product x market.

Level of detail: finished goods per product x market. The data pack has no raw
materials, bill of materials, production capacity or lead times, so:

  * stock (units)      = inventory cover (weeks) x weekly demand
  * weekly demand      = mean of the most recent actual-like monthly shipments / weeks per month
  * lead time          = production/QA release (by supply source) + transport (by mode)  [assumption]
  * effective LT       = LT + (1 - OTIF) x late-delivery penalty                          [assumption]
  * safety stock (wks) = z(service level) x sigma_rel x sqrt(weeks_per_month x LT_eff)
                         where sigma_rel = mape_to_sigma x (1 - forecast accuracy)
  * runout (P50)       = as_of + cover
  * runout (early)     = as_of + cover / (1 + z_q x sigma_rel x sqrt(weeks_per_month / cover))
  * reorder recommended = as_of + (cover - LT_eff - safety stock)
  * reorder latest      = as_of + (cover - LT_eff)          (no safety margin, ~50 % stockout risk)
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd

from .data import ACTUAL, DataPack

CANONICAL_KPIS = {
    "inventory_cover": "KPI-016",   # Inventory Coverage (weeks)
    "otif": "KPI-020",              # On-Time In-Full (%)
    "forecast_accuracy": "KPI-006", # Demand Forecast Accuracy (%)
    "units_shipped": "KPI-014",     # Units Shipped (units)
}

STATUS_ORDER = ["STOCKOUT_RISK", "ORDER_NOW", "URGENT", "PLAN", "OK", "NO_SHIPMENTS"]


# --------------------------------------------------------------------------- assumptions

@dataclass
class Assumptions:
    raw: dict[str, Any]
    path: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Assumptions":
        path = Path(path)
        return cls(json.loads(path.read_text(encoding="utf-8")), str(path))

    def with_overrides(self, overrides: dict[str, Any]) -> "Assumptions":
        """Return a copy with nested overrides applied, e.g. {"safety_stock": {"service_level": 0.98}}."""
        merged = json.loads(json.dumps(self.raw))
        _deep_merge(merged, overrides)
        return Assumptions(merged, self.path)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.raw, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]


def _deep_merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# --------------------------------------------------------------------------- helpers

def _d(as_of: date, weeks: float) -> date:
    return as_of + timedelta(days=round(weeks * 7))


def _row_ref(row: pd.Series, fields: list[str]) -> dict[str, Any]:
    ref = {
        "sheet": "Product_Market_Monthly",
        "product_id": row["product_id"],
        "market_id": row["market_id"],
        "month": row["month"].strftime("%Y-%m"),
        "value_type": row["value_type"],
    }
    for f in fields:
        v = row[f]
        ref[f] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    return ref


def default_as_of(data: DataPack) -> date:
    """End of the latest month present in the data."""
    latest = data.latest_month
    return (latest + pd.offsets.MonthEnd(0)).date()


# --------------------------------------------------------------------------- core

def _demand(history: pd.DataFrame, a: Assumptions) -> dict[str, Any]:
    cfg = a["demand"]
    wpm = a["weeks_per_month"]
    flags: list[str] = []

    actual = history[history["value_type"] == ACTUAL]
    window = actual.tail(cfg["window_actual_months"])
    basis = "actual_like rows"
    if len(window) < cfg["min_actual_months"]:
        window = history.tail(cfg["window_actual_months"])
        basis = "all rows (too few actual-like months)"
        flags.append("FEW_ACTUAL_MONTHS")

    latest_month = history["month"].max()
    if len(actual):
        gap = (latest_month.year - actual["month"].max().year) * 12 + latest_month.month - actual["month"].max().month
        if gap >= cfg["stale_actuals_after_months"]:
            flags.append("STALE_ACTUALS")

    monthly_mean = float(window["units_shipped_syn"].mean())
    if (history["units_shipped_syn"] == 0).all():
        flags.append("NEVER_SHIPPED")
    elif (window["units_shipped_syn"] == 0).any():
        flags.append("ZERO_SHIPMENT_MONTH")

    vol = actual.tail(cfg["volatility_window_actual_months"])["units_shipped_syn"]
    cv = float(vol.std(ddof=1) / vol.mean()) if len(vol) >= 2 and vol.mean() > 0 else None
    if cv is not None and cv > cfg["volatile_cv_threshold"]:
        flags.append("VOLATILE_SHIPMENTS")

    return {
        "monthly_units": monthly_mean,
        "weekly_units": monthly_mean / wpm,
        "basis": basis,
        "rows": [_row_ref(r, ["units_shipped_syn"]) for _, r in window.iterrows()],
        "history_cv": cv,
        "flags": flags,
    }


def _inventory(history: pd.DataFrame, supply_row: pd.Series, a: Assumptions) -> dict[str, Any]:
    cfg = a["inventory"]
    flags: list[str] = []
    latest = history.iloc[-1]
    so_weeks = float(supply_row["inventory_weeks_syn"])
    pmm_weeks = float(latest["inventory_weeks_syn"])

    if cfg["primary_source"] == "supply_operations":
        primary, alternate = so_weeks, pmm_weeks
        primary_ref = {"sheet": "Supply_Operations", "field": "inventory_weeks_syn", "value": so_weeks}
        alternate_ref = _row_ref(latest, ["inventory_weeks_syn"])
    elif cfg["primary_source"] == "product_market_monthly":
        primary, alternate = pmm_weeks, so_weeks
        primary_ref = _row_ref(latest, ["inventory_weeks_syn"])
        alternate_ref = {"sheet": "Supply_Operations", "field": "inventory_weeks_syn", "value": so_weeks}
    else:
        raise ValueError(f"Unknown inventory.primary_source: {cfg['primary_source']}")

    diff = abs(so_weeks - pmm_weeks)
    if diff >= cfg["conflict_threshold_weeks"]:
        flags.append("INVENTORY_SOURCE_CONFLICT")
    if latest["value_type"] != ACTUAL:
        flags.append("LATEST_MONTH_FORECAST_LIKE")
    if primary <= 0:
        flags.append("ZERO_INVENTORY")

    return {
        "cover_weeks": primary,
        "alternate_cover_weeks": alternate,
        "source_difference_weeks": diff,
        "primary_ref": primary_ref,
        "alternate_ref": alternate_ref,
        "flags": flags,
    }


def _lead_time(supply_row: pd.Series, a: Assumptions, mode: str | None = None) -> dict[str, float]:
    lt = a["lead_time_weeks"]
    source = supply_row["supply_source"]
    mode = mode or supply_row["primary_mode"]
    if source not in lt["production_release"]:
        raise KeyError(f"No production_release lead time for supply source {source!r}")
    if mode not in lt["transport"]:
        raise KeyError(f"No transport lead time for mode {mode!r}")
    production = float(lt["production_release"][source])
    transport = float(lt["transport"][mode])
    otif = float(supply_row["otif_pct_syn"]) / 100.0
    penalty = (1.0 - otif) * float(a["reliability"]["late_delivery_penalty_weeks"])
    return {
        "production_release_weeks": production,
        "transport_weeks": transport,
        "transport_mode": mode,
        "late_delivery_buffer_weeks": penalty,
        "effective_weeks": production + transport + penalty,
    }


def _safety(supply_row: pd.Series, lt_eff: float, a: Assumptions) -> dict[str, float]:
    cfg = a["safety_stock"]
    fa = float(supply_row["forecast_accuracy_pct_syn"]) / 100.0
    sigma_rel = cfg["mape_to_sigma"] * max(0.0, 1.0 - fa)
    z = NormalDist().inv_cdf(cfg["service_level"])
    weeks = z * sigma_rel * math.sqrt(a["weeks_per_month"] * max(lt_eff, 0.0))
    return {"z": z, "sigma_rel_month": sigma_rel, "safety_weeks": weeks, "forecast_accuracy": fa}


def _status(today: date, rec: date, latest: date, cfg: dict[str, int], no_demand: bool) -> str:
    if no_demand:
        return "NO_SHIPMENTS"
    if latest < today:
        return "STOCKOUT_RISK"
    if rec < today:
        return "ORDER_NOW"
    days = (rec - today).days
    if days <= cfg["urgent"]:
        return "URGENT"
    if days <= cfg["plan"]:
        return "PLAN"
    return "OK"


def compute_one(
    data: DataPack,
    supply_row: pd.Series,
    a: Assumptions,
    as_of: date,
    today: date,
) -> dict[str, Any]:
    p, m = supply_row["product_id"], supply_row["market_id"]
    history = data.monthly[(data.monthly.product_id == p) & (data.monthly.market_id == m)]
    if history.empty:
        raise ValueError(f"No Product_Market_Monthly rows for {p} x {m}")

    demand = _demand(history, a)
    inv = _inventory(history, supply_row, a)
    lt = _lead_time(supply_row, a)
    ss = _safety(supply_row, lt["effective_weeks"], a)
    wpm = a["weeks_per_month"]

    cover = inv["cover_weeks"]
    no_demand = demand["weekly_units"] <= 0

    runout_p50 = _d(as_of, cover)
    if cover > 0:
        zq = NormalDist().inv_cdf(a["safety_stock"]["early_runout_quantile"])
        early_weeks = cover / (1 + zq * ss["sigma_rel_month"] * math.sqrt(wpm / cover))
    else:
        early_weeks = 0.0
    runout_early = _d(as_of, early_weeks)

    reorder_latest_w = cover - lt["effective_weeks"]
    reorder_rec_w = reorder_latest_w - ss["safety_weeks"]
    reorder_latest = _d(as_of, reorder_latest_w)
    reorder_rec = _d(as_of, reorder_rec_w)

    alt_cover = inv["alternate_cover_weeks"]
    alt_reorder_rec = _d(as_of, alt_cover - lt["effective_weeks"] - ss["safety_weeks"])

    status = _status(today, reorder_rec, reorder_latest, a["status_thresholds_days"], no_demand)

    expedite = None
    if status == "STOCKOUT_RISK":
        exp_mode = a["lead_time_weeks"]["expedite_mode"]
        exp_lt = _lead_time(supply_row, a, mode=exp_mode)
        exp_latest = _d(as_of, cover - exp_lt["effective_weeks"])
        expedite = {
            "mode": exp_mode,
            "effective_lead_time_weeks": round(exp_lt["effective_weeks"], 2),
            "latest_order_date": exp_latest.isoformat(),
            "feasible": exp_latest >= today and exp_mode != supply_row["primary_mode"],
        }

    flags = sorted(set(demand["flags"] + inv["flags"]))
    stock_units = cover * demand["weekly_units"]

    product = data.products.set_index("product_id").loc[p]
    market = data.markets.set_index("market_id").loc[m]

    return {
        "product_id": p,
        "product_name": product["product_name"],
        "therapeutic_area": product["therapeutic_area"],
        "market_id": m,
        "market_name": market["market_name"],
        "region": market["region"],
        "supply_source": supply_row["supply_source"],
        "primary_mode": supply_row["primary_mode"],
        "risk_status_in_source": supply_row["risk_status"],
        "as_of": as_of.isoformat(),
        "today": today.isoformat(),
        "status": status,
        "days_to_recommended_order": (reorder_rec - today).days,
        "cover_weeks": round(cover, 2),
        "stock_units_est": round(stock_units),
        "weekly_demand_units": round(demand["weekly_units"], 1),
        "runout_date_p50": runout_p50.isoformat(),
        "runout_date_early": runout_early.isoformat(),
        "reorder_by_recommended": reorder_rec.isoformat(),
        "reorder_by_latest": reorder_latest.isoformat(),
        "lead_time_effective_weeks": round(lt["effective_weeks"], 2),
        "safety_stock_weeks": round(ss["safety_weeks"], 2),
        "service_level": a["safety_stock"]["service_level"],
        "alternate_cover_weeks": round(alt_cover, 2),
        "alternate_reorder_by_recommended": alt_reorder_rec.isoformat(),
        "source_difference_weeks": round(inv["source_difference_weeks"], 2),
        "flags": flags,
        "expedite": expedite,
        "receipt": {
            "canonical_kpis": CANONICAL_KPIS,
            "data_file": data.source_file,
            "assumptions_version": a["version"],
            "assumptions_status": a["status"],
            "assumptions_fingerprint": a.fingerprint,
            "inputs": {
                "inventory_primary": inv["primary_ref"],
                "inventory_alternate": inv["alternate_ref"],
                "demand_basis": demand["basis"],
                "demand_rows": demand["rows"],
                "supply_operations": {
                    "sheet": "Supply_Operations",
                    "product_id": p,
                    "market_id": m,
                    "supply_source": supply_row["supply_source"],
                    "primary_mode": supply_row["primary_mode"],
                    "otif_pct_syn": float(supply_row["otif_pct_syn"]),
                    "forecast_accuracy_pct_syn": float(supply_row["forecast_accuracy_pct_syn"]),
                    "risk_status": supply_row["risk_status"],
                },
            },
            "steps": [
                f"weekly_demand = mean({len(demand['rows'])} months units_shipped) / {wpm} = {demand['weekly_units']:.1f} units/week",
                f"stock_units ≈ cover {cover:.2f} wk × {demand['weekly_units']:.1f} = {stock_units:,.0f} units",
                f"LT_eff = production {lt['production_release_weeks']} + transport({lt['transport_mode']}) {lt['transport_weeks']} "
                f"+ (1 - OTIF {supply_row['otif_pct_syn']}%) × {a['reliability']['late_delivery_penalty_weeks']} = {lt['effective_weeks']:.2f} wk",
                f"sigma_rel = {a['safety_stock']['mape_to_sigma']} × (1 - FA {ss['forecast_accuracy']:.3f}) = {ss['sigma_rel_month']:.3f}",
                f"safety = z {ss['z']:.3f} × {ss['sigma_rel_month']:.3f} × sqrt({wpm} × {lt['effective_weeks']:.2f}) = {ss['safety_weeks']:.2f} wk",
                f"runout_p50 = {as_of} + {cover:.2f} wk = {runout_p50}",
                f"runout_early (q={a['safety_stock']['early_runout_quantile']}) = {as_of} + {early_weeks:.2f} wk = {runout_early}",
                f"reorder_latest = {as_of} + ({cover:.2f} - {lt['effective_weeks']:.2f}) wk = {reorder_latest}",
                f"reorder_recommended = reorder_latest - {ss['safety_weeks']:.2f} wk = {reorder_rec}",
            ],
            "history_cv": None if demand["history_cv"] is None else round(demand["history_cv"], 3),
        },
    }


def compute_all(
    data: DataPack,
    a: Assumptions,
    as_of: date | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    as_of = as_of or default_as_of(data)
    today = today or date.today()
    results = [compute_one(data, row, a, as_of, today) for _, row in data.supply.iterrows()]
    rank = {s: i for i, s in enumerate(STATUS_ORDER)}
    results.sort(key=lambda r: (rank[r["status"]], r["reorder_by_recommended"]))
    return results


def flatten(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in results:
        flat = {k: v for k, v in r.items() if k not in ("receipt", "expedite", "flags")}
        flat["flags"] = ";".join(r["flags"])
        flat["expedite_feasible"] = None if r["expedite"] is None else r["expedite"]["feasible"]
        flat["expedite_latest_order_date"] = None if r["expedite"] is None else r["expedite"]["latest_order_date"]
        flat["assumptions_fingerprint"] = r["receipt"]["assumptions_fingerprint"]
        rows.append(flat)
    return pd.DataFrame(rows)


def plant_summary(results: list[dict[str, Any]]) -> pd.DataFrame:
    df = flatten(results)
    counts = pd.crosstab(df["supply_source"], df["status"]).reindex(columns=STATUS_ORDER, fill_value=0)
    agg = df.groupby("supply_source").agg(
        product_markets=("product_id", "size"),
        weekly_demand_units=("weekly_demand_units", "sum"),
        earliest_recommended_order=("reorder_by_recommended", "min"),
        inventory_source_conflicts=("flags", lambda s: s.str.contains("INVENTORY_SOURCE_CONFLICT").sum()),
    )
    agg["weekly_demand_units"] = agg["weekly_demand_units"].round(0)
    return agg.join(counts).reset_index()


def metric_definition(a: Assumptions, data: DataPack, as_of: date) -> dict[str, Any]:
    """Governed registration record for the new metric, ready for the catalogue / context broker."""
    kpis = data.kpis.set_index("kpi_id")
    depends = []
    for role, kid in CANONICAL_KPIS.items():
        k = kpis.loc[kid]
        depends.append({
            "role": role,
            "kpi_id": kid,
            "kpi_name": k["kpi_name"],
            "definition_status": k["definition_status"],
            "approval_status": k["approval_status"],
        })
    return {
        "metric_id": "MET-REORDER-BY-001",
        "name": "Replenishment Reorder-By Date",
        "question_answered": "By when must replenishment be ordered so that a product x market does not stock out?",
        "unit": "date",
        "grain": "product x market",
        "outputs": ["runout_date_p50", "runout_date_early", "reorder_by_recommended", "reorder_by_latest", "status"],
        "formula": __doc__.strip().split("\n\n", 1)[1],
        "depends_on_canonical_kpis": depends,
        "lineage": ["Product_Market_Monthly", "Supply_Operations", "Products", "Markets"],
        "assumptions": {
            "version": a["version"],
            "fingerprint": a.fingerprint,
            "status": a["status"],
            "owner": a["owner"],
            "review_by": a["review_by"],
        },
        "lifecycle": {
            "status": "proposed",
            "owner": a["owner"],
            "created": as_of.isoformat(),
            "review_by": a["review_by"],
            "reuse_rule": "Same question for another market, product or plant is answered by filtering this metric, not by creating a new report.",
        },
        "justification": "No KPI in KPI_Catalog defines a reorder-by or runout date; Inventory Coverage (KPI-016) reports weeks of cover only. The new metric is built on top of the canonical KPIs instead of redefining them.",
        "synthetic": True,
    }
