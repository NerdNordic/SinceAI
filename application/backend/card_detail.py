"""Drill-down detail behind each briefing card, served for the UI card modal."""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import config
from .briefing import STATUS_FI, URGENT, briefing
from .db import get_db, lookups
from .metrics import ACTUAL, METRICS, replenishment_results

DESCRIPTIONS = {
    "pairs": "Kaikki tehtaan toimitusvastuulla olevat tuote–markkina-parit, joille on meneillään "
             "ennustettua kysyntää. Tila kertoo täydennystarpeen kiireellisyyden.",
    "urgent": "Tuote–markkina-parit, jotka pitää tilata heti: varasto loppumassa (STOCKOUT_RISK) tai "
              "tilaus pitää tehdä viimeistään nyt (ORDER_NOW). Ajat perustuvat suositeltuun "
              "täydennyspolitiikkaan (assumptions.json).",
    "urgent14": "Kiireelliset parit (URGENT): täydennystä pitää ryhtyä valmistelemaan 14 päivän sisällä.",
    "otif": "Toimitusvarmuus (On-Time In-Full): ajallaan ja täysimääräisenä toimitettujen osuus. "
            "Laskettu tehtaan tuote–markkina-parien kuukausikeskiarvona — sama kanoninen määritelmä "
            "kuin chatin toimitusvarmuuskaaviossa, joten luvut eivät voi erota toisistaan.",
    "volume": "Tehtaan tuote–markkina-parien ennustettu viikkokysyntä yhteensä (kpl/vko).",
    "week_orders": "Parit, joille suositeltu tilauspäivä osuu seuraavan 7 päivän sisään.",
    "expedite": "Parit, jotka ovat vielä pelastettavissa lentokuljetuksella: nopeutustilaus on "
                "teknisesti mahdollinen ja se ehtii ennen varaston loppumista.",
    "priority": "Priorisoitavat parit tuotannolle: loppumisriskin (STOCKOUT_RISK, ORDER_NOW) ja "
                "kiireellisyyden (URGENT) perusteella.",
    "requests": "Build-less -mittarin kaikki käsitellyt pyynnöt. Chat-tyyppiset tervehdykset eivät "
                "lasku pyynnöiksi.",
    "new_charts": "Pyyntöjä, jotka johtivat uuden kaavion rakentamiseen (BUILD). Build-less -periaatteen "
                  "mukaan uusi kaavio syntyy vain, kun mitään olemassa olevaa ei voi uudelleenkäyttää.",
    "handled": "Pyyntöjä, jotka hoidettiin ilman uutta kaaviota: REUSE (uudelleenkäyttö), EXTEND "
               "(laajennus) tai ANSWER (vastaus ilman kaaviota).",
    "certify_suggestions": "Kaaviorekisterin ehdotukset sertifioitavaksi: aktiivinen kaavio, jota on "
                           "käyttänyt vähintään kaksi roolia tai jolla on vähintään kolme käyttökertaa.",
    "retire_suggestions": "Kaaviorekisterin poistoehdotukset: kaaviot, jotka ovat olleet käyttämättä "
                          "pidempään kuin elinkaarisääntö sallii (RETIRE_IDLE_MINUTES).",
}

_DECISION_FI = {"REUSE": "uudelleenkäyttö", "EXTEND": "laajennus", "ANSWER": "vastaus ilman kaaviota",
                "BUILD": "uusi kaavio", "CLARIFY": "tarkennuspyyntö", "CHAT": "chat-tervehdys"}


def _d(v) -> str:
    return pd.Timestamp(v).strftime("%d.%m.%Y") if v else "–"


def _expedite(r: dict[str, Any]) -> str:
    exp = r["expedite"]
    if exp and exp["feasible"]:
        return f"{exp['mode']} viimeistään {_d(exp['latest_order_date'])}"
    return ""


def _repl_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"tuote": r["product_name"], "markkina": r["market_name"], "tila": STATUS_FI[r["status"]],
             "tilaa viimeistään": _d(r["reorder_by_recommended"]),
             "loppuu arviolta": _d(r["runout_date_p50"]),
             "päiviä tilaukseen": r["days_to_recommended_order"],
             "kpl/vko": r["weekly_demand_units"], "nopeutus": _expedite(r)} for r in rows]


def _days_chart(rows: list[dict[str, Any]]) -> dict[str, Any]:
    top = rows[:10]
    return {"type": "bar",
            "labels": [f"{r['product_name']} · {r['market_id']}" for r in top],
            "datasets": [{"label": "Päiviä suositeltuun tilauspäivään",
                          "data": [r["days_to_recommended_order"] for r in top]}]}


def _plant_rows(role: str) -> list[dict[str, Any]]:
    plant = config.ROLES[role]["plant"]
    return [x for x in replenishment_results() if x["supply_source"] == plant and x["status"] != "NO_SHIPMENTS"]


def _otif_detail(role: str) -> dict[str, Any]:
    plant = config.ROLES[role]["plant"]
    pairs = {k for k, v in lookups()["plant"].items() if v == plant}
    df = pd.DataFrame(list(get_db().product_market_monthly.find(
        {}, {"_id": 0, "product_id": 1, "market_id": 1, "month": 1, "otif_pct_syn": 1, "value_type": 1})))
    out = {"chart": {"type": "line", "labels": [], "datasets": []}, "kpi": _otif_kpi(),
           "source": "product_market_monthly"}
    if not df.empty:
        df = df[[(p, m) in pairs for p, m in zip(df.product_id, df.market_id)]]
    if df.empty:
        return out
    df["month"] = pd.to_datetime(df["month"]).dt.strftime("%Y-%m")
    g = df.groupby("month")["otif_pct_syn"].mean().round(2).sort_index()
    fc = df["value_type"] != ACTUAL
    share = (fc.groupby(df["month"]).sum() / df.groupby("month").size()).reindex(g.index).fillna(0.0)
    out["chart"] = {"type": "line", "labels": g.index.tolist(),
                    "datasets": [{"label": f"OTIF % ({plant}, keskiarvo)",
                                  "data": [round(float(v), 2) for v in g],
                                  "forecastShare": [round(float(s), 3) for s in share]}]}
    out["source"] = f"product_market_monthly · {len(df)} riviä · {df['month'].min()} – {df['month'].max()}"
    return out


def _otif_kpi() -> dict[str, Any]:
    m = METRICS["On-Time In-Full"]
    return {"id": m.kpi_id, "name": "On-Time In-Full", "unit": m.unit, "definition": m.definition}


def _volume_detail(role: str) -> dict[str, Any]:
    rows = _plant_rows(role)
    chart: dict[str, Any] = {"type": "bar", "labels": [], "datasets": []}
    table: list[dict[str, Any]] = []
    if rows:
        g = pd.DataFrame([{"tuote": r["product_name"], "kpl": r["weekly_demand_units"]} for r in rows])
        s = g.groupby("tuote")["kpl"].sum().round(0).sort_values(ascending=False)
        chart = {"type": "bar", "labels": s.index.tolist(),
                 "datasets": [{"label": "kpl/vko", "data": [int(v) for v in s]}]}
        table = [{"tuote": t, "kpl/vko": int(v)} for t, v in s.items()]
    return {"chart": chart, "rows": table, "source": "replenishment (viikkokysyntä tuotteittain)"}


def _pairs_detail(role: str) -> dict[str, Any]:
    rows = sorted(_plant_rows(role), key=lambda r: r["days_to_recommended_order"])
    return {"rows": _repl_table(rows), "source": "replenishment · tuote × markkina"}


def _urgent_detail(role: str) -> dict[str, Any]:
    rows = [x for x in _plant_rows(role) if x["status"] in URGENT]
    rows = sorted(rows, key=lambda r: r["days_to_recommended_order"])
    return {"chart": _days_chart(rows), "rows": _repl_table(rows),
            "source": "replenishment · tila STOCKOUT_RISK / ORDER_NOW"}


def _urgent14_detail(role: str) -> dict[str, Any]:
    rows = [x for x in _plant_rows(role) if x["status"] == "URGENT"]
    rows = sorted(rows, key=lambda r: r["days_to_recommended_order"])
    return {"chart": _days_chart(rows), "rows": _repl_table(rows), "source": "replenishment · tila URGENT"}


def _week_orders_detail(role: str) -> dict[str, Any]:
    rows = [x for x in _plant_rows(role) if x["days_to_recommended_order"] <= 7]
    rows = sorted(rows, key=lambda r: r["days_to_recommended_order"])
    return {"chart": _days_chart(rows), "rows": _repl_table(rows),
            "source": "replenishment · days-to-order ≤ 7 pv"}


def _expedite_detail(role: str) -> dict[str, Any]:
    rows = [x for x in _plant_rows(role) if x["expedite"] and x["expedite"]["feasible"]]
    rows = sorted(rows, key=lambda r: r["days_to_recommended_order"])
    return {"rows": _repl_table(rows), "source": "replenishment · nopeutustilaus mahdollinen"}


def _priority_detail(role: str) -> dict[str, Any]:
    rows = [x for x in _plant_rows(role) if x["status"] in URGENT or x["status"] == "URGENT"]
    rows = sorted(rows, key=lambda r: r["days_to_recommended_order"])
    return {"chart": _days_chart(rows), "rows": _repl_table(rows),
            "source": "replenishment · STOCKOUT_RISK, ORDER_NOW, URGENT"}


def _meter_table() -> list[dict[str, Any]]:
    from .engine import DECISIONS, meter

    m = meter()
    return [{"päätös": _DECISION_FI[d], "pyyntöjä": m["by_decision"][d]} for d in DECISIONS]


def _requests_detail(role: str) -> dict[str, Any]:
    from .engine import meter

    m = meter()
    by_role = [{"rooli": config.ROLES[r]["label"], "pyyntöjä": sum(c.values())}
               for r, c in m["by_role"].items()]
    src = "request_log"
    if m["reuse_rate"] is not None:
        src = f"request_log · {m['requests']} pyyntöä · uudelleenkäyttöaste {m['reuse_rate'] * 100:.0f} %"
    return {"rows": _meter_table() + by_role, "source": src}


def _new_charts_detail(role: str) -> dict[str, Any]:
    from .engine import registry

    reg = registry()
    return {"rows": [{"kaavio": c["title"], "omistaja": c.get("owner") or "–", "käyttöjä": c.get("use_count", 0),
                      "rooleja": len(c.get("used_by_roles", [])), "tila": c["status"]} for c in reg],
            "source": "chart_registry"}


def _handled_detail(role: str) -> dict[str, Any]:
    return {"rows": _meter_table(), "source": "request_log · REUSE + EXTEND + ANSWER"}


def _suggestion_detail(which: str) -> dict[str, Any]:
    from .engine import registry

    reg = [c for c in registry() if c["suggestion"] == which]
    return {"rows": [{"kaavio": c["title"], "omistaja": c.get("owner") or "–", "käyttöjä": c.get("use_count", 0),
                      "rooleja": len(c.get("used_by_roles", [])), "tila": c["status"],
                      "viimeksi käytetty": _d(c.get("last_used_at"))} for c in reg],
            "source": f"chart_registry · ehdotus {which}"}


def _certify_detail(role: str) -> dict[str, Any]:
    return _suggestion_detail("certify")


def _retire_detail(role: str) -> dict[str, Any]:
    return _suggestion_detail("retire")


_BUILDERS = {
    "pairs": _pairs_detail, "urgent": _urgent_detail, "urgent14": _urgent14_detail,
    "otif": _otif_detail, "volume": _volume_detail, "week_orders": _week_orders_detail,
    "expedite": _expedite_detail, "priority": _priority_detail, "requests": _requests_detail,
    "new_charts": _new_charts_detail, "handled": _handled_detail,
    "certify_suggestions": _certify_detail, "retire_suggestions": _retire_detail,
}


def card_detail(role: str, key: str) -> dict[str, Any]:
    """Modal payload for a briefing card: summary + description + drill-down data."""
    if role not in config.ROLES:
        raise ValueError(role)
    b = briefing(role)
    card = next((c for c in b["cards"] if c["key"] == key), None)
    if card is None:
        raise KeyError(key)
    out: dict[str, Any] = {"key": key}
    out.update({k: card.get(k) for k in ("label", "value", "unit", "tone", "target",
                                        "lower_is_better", "ask_hint")})
    out["description"] = DESCRIPTIONS.get(key, "")
    builder = _BUILDERS.get(key)
    if builder:
        out.update(builder(role))
    return out
