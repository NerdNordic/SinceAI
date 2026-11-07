"""Morning briefing per role: latest period, exceptions and freshness."""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import config
from .db import get_db, lookups
from .metrics import ACTUAL, replenishment_results

URGENT = ("STOCKOUT_RISK", "ORDER_NOW")
STATUS_FI = {"STOCKOUT_RISK": "loppumisriski", "ORDER_NOW": "tilaa nyt", "URGENT": "kiireellinen",
             "PLAN": "suunnittele", "OK": "kunnossa", "NO_SHIPMENTS": "ei toimituksia"}

ASK_HINTS = {
    "otif": "Näytä toimitusvarmuus kuukausittain",
    "urgent": "Mitkä tilaukset pitää tehdä tällä viikolla?",
}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _fi(v):
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    return str(v).replace(".", ",")


def _with_targets(cards):
    for c in cards:
        t = config.CARD_TARGETS.get(c["key"])
        if t and c.get("value") is not None:
            c["target"] = t["target"]
            c["lower_is_better"] = t["lower_is_better"]
        if c["key"] in ASK_HINTS:
            c["ask_hint"] = ASK_HINTS[c["key"]]
    return cards


def _dev_message(card):
    unit = f" {card['unit']}" if card.get("unit") else ""
    return f"{card['label']}: {_fi(card['value'])}{unit} vs tavoite {_fi(card['target'])}{unit}."


def _deviations(cards):
    """Deviations derived from target breaches, sorted high -> low severity."""
    devs = []
    for c in cards:
        t = config.CARD_TARGETS.get(c["key"])
        if not t or c.get("value") is None or "target" not in c:
            continue
        within = c["value"] <= t["target"] if t["lower_is_better"] else c["value"] >= t["target"]
        if not within:
            devs.append({"severity": t["severity"], "card_key": c["key"],
                         "message": _dev_message(c)})
    return sorted(devs, key=lambda d: _SEVERITY_ORDER[d["severity"]])


def _plant_otif(plant: str) -> tuple[float | None, str | None]:
    """Mean OTIF of the plant's product x markets in the latest month.
    Same definition as the On-Time In-Full chart (all rows), so briefing and chat never disagree."""
    pairs = {k for k, v in lookups()["plant"].items() if v == plant}
    df = pd.DataFrame(list(get_db().product_market_monthly.find({},
                                                                {"_id": 0, "product_id": 1, "market_id": 1, "month": 1, "otif_pct_syn": 1})))
    if df.empty:
        return None, None
    df = df[[(p, m) in pairs for p, m in zip(df.product_id, df.market_id)]]
    if df.empty:
        return None, None
    latest = df["month"].max()
    return round(float(df[df["month"] == latest]["otif_pct_syn"].mean()), 1), pd.Timestamp(latest).strftime("%Y-%m")


def _item(r: dict[str, Any]) -> dict[str, Any]:
    exp = r["expedite"]
    return {"product": r["product_name"], "market": r["market_name"], "status": r["status"],
            "status_fi": STATUS_FI[r["status"]], "reorder_by": r["reorder_by_recommended"],
            "runout": r["runout_date_p50"], "weekly_units": r["weekly_demand_units"],
            "expedite": f"{exp['mode']} viimeistään {exp['latest_order_date']}" if exp and exp["feasible"] else None}


def briefing(role: str) -> dict[str, Any]:
    if role not in config.ROLES:
        raise ValueError(role)
    r = config.ROLES[role]
    if role == "data_steward":
        from .engine import meter, registry

        reg = registry()
        m = meter()
        return {"role": r["label"], "cards": [
            {"key": "requests", "label": "Pyyntöjä", "value": m["requests"]},
            {"key": "new_charts", "label": "Uusia kaavioita", "value": m["new_charts"]},
            {"key": "handled", "label": "Hoidettu ilman uutta kaaviota", "value": m["handled_without_new_chart"]},
            {"key": "certify_suggestions", "label": "Sertifiointiehdotuksia",
             "value": sum(1 for c in reg if c["suggestion"] == "certify")},
            {"key": "retire_suggestions", "label": "Poistoehdotuksia",
             "value": sum(1 for c in reg if c["suggestion"] == "retire")},
        ], "items": [], "freshness": None, "deviations": []}

    plant = r["plant"]
    rows = [x for x in replenishment_results() if x["supply_source"] == plant and x["status"] != "NO_SHIPMENTS"]
    urgent = [x for x in rows if x["status"] in URGENT]
    this_week = [x for x in rows if x["days_to_recommended_order"] <= 7]
    otif, otif_month = _plant_otif(plant)
    weekly = round(sum(x["weekly_demand_units"] for x in rows))
    expeditable = [x for x in rows if x["expedite"] and x["expedite"]["feasible"]]
    conflicts = sum(1 for x in rows if "INVENTORY_SOURCE_CONFLICT" in x["flags"])
    freshness = (f"Data: kuukausitaso, viimeisin {otif_month}. Varastotilanne {rows[0]['as_of'] if rows else '-'}. "
                 f"{conflicts} tuote–markkina-parilla varastolähteet ovat ristiriidassa.")

    if role == "tehtaan_johtaja":
        cards = [
            {"key": "pairs", "label": "Tuote–markkina-pareja", "value": len(rows)},
            {"key": "urgent", "label": "Loppumisriski / tilaa nyt", "value": len(urgent),
             "tone": "critical" if urgent else None},
            {"key": "urgent14", "label": "Kiireelliset (≤ 14 pv)",
             "value": sum(1 for x in rows if x["status"] == "URGENT"), "tone": "warning"},
            {"key": "otif", "label": f"OTIF {otif_month}", "value": otif, "unit": "%"},
            {"key": "volume", "label": "Volyymi", "value": weekly, "unit": "kpl/vko"},
        ]
        items = [_item(x) for x in rows[:5]]
    elif role == "vuoropaallikko":
        cards = [
            {"key": "urgent", "label": "Tilattava nyt", "value": len(urgent),
             "tone": "critical" if urgent else None},
            {"key": "week_orders", "label": "Tilattava tällä viikolla", "value": len(this_week), "tone": "warning"},
            {"key": "expedite", "label": "Pelastettavissa lentokuljetuksella", "value": len(expeditable)},
        ]
        items = [_item(x) for x in (urgent + [x for x in this_week if x not in urgent])[:8]]
    else:  # tuotantotyontekija
        cards = [
            {"key": "priority", "label": "Priorisoitavia tuotteita",
             "value": len(urgent) + sum(1 for x in rows if x["status"] == "URGENT")},
            {"key": "volume", "label": "Tehtaan volyymi", "value": weekly, "unit": "kpl/vko"},
        ]
        items = [_item(x) for x in rows[:5]]
    cards = _with_targets(cards)
    return {"role": r["label"], "plant": plant, "cards": cards, "items": items,
            "freshness": freshness, "deviations": _deviations(cards)}
