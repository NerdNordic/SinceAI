"""Offline stub provider implementing the n8n webhook contract with canned demo flows.

Deterministic (no randomness): synthetic factory with lines L1-L3, so the smoke
test and the demo behave identically on every run. Covers the img-as-text steps
2-7: briefing, clarify, fingerprint verdicts REUSE/EXTEND/ANSWER/BUILD,
chart + receipt + raw CSV.
"""

import csv
import datetime as dt
import io

LINES = ["L1", "L2", "L3"]
OEE_BASE = {"L1": 84.0, "L2": 78.5, "L3": 86.0}
OEE_KPI = "KPI-011"

AMBIGUOUS = {"tuotanto", "tilanne", "miten menee", "kaavio", "data", "luvut"}
EXTEND_FILTERS = ("yövuoro", "viikonloppu", "hylk", "perjantai")
ONE_OFF_TOKENS = ("tänään", "nyt", "viime yönä", "viime vuoro", "viimeisin vuoro",
                  "tällä hetkellä")
BUILD_TOKENS = ("energia", "energiankulutus", "hiilijalanjälki", "hiilijalanjalka", "co2",
                "kwh")


def _now():
    return dt.datetime.now()


def _days(n):
    today = _now().date()
    return [today - dt.timedelta(days=i) for i in range(n - 1, -1, -1)]


def _fmt(dtobj, fmt="%d.%m. %H:%M"):
    return dtobj.strftime(fmt)


def _oee(line, day):
    wave = 2.5 * ((day.toordinal() % 7) / 3.0) - 1.5
    weekend = -4.0 if day.weekday() >= 5 else 0.0
    dip = -7.0 if (line == "L2" and day.toordinal() % 14 < 2) else 0.0
    return round(OEE_BASE[line] + wave + weekend + dip, 1)


def _fresh(hour, minute=0, stale=False):
    stamp = _now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {"last_refresh": _fmt(stamp), "state": "stale" if stale else "fresh"}


def _kpi(kpi_id, name, value, unit, target, status, freshness=None):
    return {"id": kpi_id, "name": name, "value": value, "unit": unit,
            "target": target, "status": status, "freshness": freshness or _fresh(6)}


def _csv(rows, cols=("date", "value")):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for row in rows:
        writer.writerow([row.get(c, "") for c in cols])
    return buf.getvalue()


def _chart(chart_type, title, rows, x="date", y="value"):
    return {"spec": {"chart_type": chart_type, "title": title, "x": x, "y": y}, "data": rows}


def _receipt(formula, source, rows, version, freshness):
    return {"formula": formula, "source": source, "source_rows": rows,
            "assumption_version": version, "freshness": freshness}


def get_briefing(role):
    as_of = _fmt(_now(), "%d.%m.%Y %H:%M")
    if role == "director":
        return {
            "role": role, "as_of": as_of,
            "kpis": [
                _kpi("KPI-011", "OEE, tehdas", 81.9, "%", 85.0, "deviation"),
                _kpi("KPI-003", "Tuotanto vs suunnitelma", 97.6, "%", 100.0, "deviation"),
                _kpi("KPI-009", "Aikataulunmukaisuus (OTD)", 96.2, "%", 98.0, "ok"),
                _kpi("KPI-014", "Työturvallisuusindeksi (TRI 30 pv)", 2, "tapaus", 1,
                     "deviation", _fresh(5, 30)),
                _kpi("KPI-012", "Poissaoloprosentti", 4.1, "%", 5.0, "ok"),
            ],
            "deviations": [
                {"kpi_id": "KPI-011", "severity": "high",
                 "message": "OEE 81,9 % vs tavoite 85,0 % — L2 aloitti viikon alussa, "
                            "eri suuruinen heitto."},
                {"kpi_id": "KPI-014", "severity": "medium",
                 "message": "2 kirjattua turvallisuuspoikkeamaa viimeisen 30 päivän "
                            "ajalta (tavoite 1)."},
                {"kpi_id": "KPI-003", "severity": "low",
                 "message": "Tuotanto 97,6 % suunnitelmasta; alijäämä L2:n kuormasta."},
            ],
        }
    if role == "shift_supervisor":
        return {
            "role": role, "as_of": as_of,
            "kpis": [
                _kpi("KPI-003", "Vuoron tuotanto", 12340, "kpl", 13000, "deviation"),
                _kpi("KPI-011", "OEE L1", _oee("L1", _now().date()), "%", 80.0, "ok"),
                _kpi("KPI-011", "OEE L2", _oee("L2", _now().date()), "%", 80.0, "deviation"),
                _kpi("KPI-011", "OEE L3", _oee("L3", _now().date()), "%", 80.0, "ok"),
                _kpi("KPI-007", "Hylkysprosentti", 2.8, "%", 3.0, "ok"),
                _kpi("KPI-013", "Käytettävyys", 88.1, "%", 90.0, "ok", _fresh(4, 0, True)),
            ],
            "deviations": [
                {"kpi_id": "KPI-003", "severity": "medium",
                 "message": "Vuoron tuotanto 12 340 kpl vs tavoite 13 000 kpl "
                            "(−660 kpl, L2:veto)."},
                {"kpi_id": "KPI-011", "severity": "high",
                 "message": "L2:n OEE 42 min seisokin takia alle tavoitteen "
                            "(pesu-ohjelman häiriö 02:10)."},
                {"kpi_id": "KPI-013", "severity": "low",
                 "message": "Käytettävyysdatan viimeisin lataus 04:00 — yövuoron "
                            "loppuluku puuttuu vielä."},
            ],
        }
    return {
        "role": role, "as_of": as_of,
        "kpis": [
            _kpi("KPI-003", "Päivän tavoite (L2)", 3400, "kpl", 3400, "ok"),
            _kpi("KPI-003", "Valmistunut", 2980, "kpl", 3400, "deviation"),
            _kpi("KPI-007", "Hylkäykset", 41, "kpl", 60, "ok"),
            _kpi("KPI-014", "Turvallisuusmuistutukset", 0, "kpl", 0, "ok"),
        ],
        "deviations": [
            {"kpi_id": "KPI-003", "severity": "low",
             "message": "Valmistettu 2 980 / 3 400 kpl — tavoitteessa pysymiseen "
                        "0,5 h lisänopeus rivillä."},
        ],
    }


def ask(role, question, history=None):
    q = (question or "").lower().strip().rstrip("?").strip()
    if any(token in q for token in BUILD_TOKENS):
        return _build_energy(q)
    if q in AMBIGUOUS or len(q) < 4:
        return _clarify_default()
    if "oee" in q:
        if any(f in q for f in EXTEND_FILTERS):
            return _extend_oee(q)
        return _reuse_oee()
    if any(t in q for t in ONE_OFF_TOKENS):
        return _answer_last_night()
    if "tuotanto" in q or "määrä" in q or "kpl" in q:
        if "linj" in q:
            return _extend_production()
        return _reuse_production()
    return _clarify_default()


def _clarify_default():
    return {
        "type": "clarify",
        "question": "Tarkennetaan, jotta vastaus on kanoninen: mitä mittaria tarkoitat?",
        "suggestions": [
            {"kpi_id": OEE_KPI, "label": "OEE (kanoninen, %)"},
            {"kpi_id": "KPI-003", "label": "Tuotantomäärä (kpl)"},
            {"kpi_id": "KPI-007", "label": "Hylkysprosentti (%)"},
        ],
    }


def _reuse_oee():
    rows = [{"date": d.isoformat(), "value": round(sum(_oee(l, d) for l in LINES) / 3, 1)}
            for d in _days(14)]
    return {
        "type": "reuse",
        "text": ("Tämä kysymys vastaa jo olemassa olevaa kaaviota: uudelleenkäytetään "
                 "**CH-012** päivitetyllä datalla — uutta kaaviota ei luoda."),
        "matched_chart": {"id": "CH-012", "title": "OEE viikkokaavio (tehdas)"},
        "chart": _chart("line", "OEE 14 päivän kehitys (L1–L3 ka)", rows),
        "receipt": _receipt("OEE = käytettävyys × suorituskyky × laatu "
                            f"({OEE_KPI}, kanoninen määritelmä v1.2)",
                            "MongoDB Atlas: production.shifts", 412, "v1.2",
                            f"Päivitetty tänään {_fmt(_now(), '%H:%M')} (automaattilataus)"),
        "csv": _csv(rows),
    }


def _extend_oee(q):
    rows = [{"date": d.isoformat(), "value": round(_oee("L2", d) - 3.0, 1)} for d in _days(14)]
    return {
        "type": "extend",
        "text": ("Olemassa olevaa kaaviota **CH-012** laajennettiin uudella suodattimella "
                 "(yövuoro, L2) — sama kanoninen KPI, ei uutta kaaviota."),
        "matched_chart": {"id": "CH-012", "title": "OEE viikkokaavio (tehdas)"},
        "chart": _chart("line", "OEE L2 yövuorot, 14 pv", rows),
        "receipt": _receipt(f"OEE {OEE_KPI} + suodatin: shift = 'yö', linja = 'L2'",
                            "MongoDB Atlas: production.shifts", 96, "v1.2 + suodatin",
                            "Laskettu kyselyhetkellä Atlasista (suora kysely)"),
        "csv": _csv(rows),
    }


def _reuse_production():
    rows = [{"date": d.isoformat(), "value": 12340 + (d.toordinal() % 5) * 90 - 140}
            for d in _days(14)]
    return {
        "type": "reuse",
        "text": ("Tuotantomääräkysymykseen vastaa olemassa oleva kaavio — uudelleenkäytetään "
                 "**CH-007** päivitetyllä datalla."),
        "matched_chart": {"id": "CH-007", "title": "Päivittäinen tuotantomäärä (tehdas)"},
        "chart": _chart("bar", "Päivittäinen tuotantomäärä, 14 pv", rows),
        "receipt": _receipt("SUM(valmistunut_kpl) GROUP BY tuotantopäivä",
                            "MongoDB Atlas: production.shifts", 418, "v1.1",
                            f"Päivitetty tänään {_fmt(_now(), '%H:%M')}"),
        "csv": _csv(rows),
    }


def _extend_production():
    rows = [{"date": d.isoformat(),
             "value": {"L1": 4120, "L2": 3540, "L3": 4680}[l]}
            for d in _days(7) for l in LINES]
    for r in rows:
        r["value"] = r["value"] + (dt.date.fromisoformat(r["date"]).toordinal() % 4) * 40
    return {
        "type": "extend",
        "text": ("Kaaviota **CH-007** laajennettiin linjakohtaisella jaottelulla — "
                 "sama kanoninen mittari uudella dimensiotasolla."),
        "matched_chart": {"id": "CH-007", "title": "Päivittäinen tuotantomäärä (tehdas)"},
        "chart": _chart("bar", "Tuotantomäärä linjoittain, 7 pv", rows, x="date"),
        "receipt": _receipt("SUM(valmistunut_kpl) GROUP BY tuotantopäivä, linja",
                            "MongoDB Atlas: production.shifts", 147, "v1.1 + dimensio 'linja'",
                            f"Päivitetty tänään {_fmt(_now(), '%H:%M')}"),
        "csv": _csv(rows),
    }


def _answer_last_night():
    rows = [{"date": l, "value": v} for l, v in
            (("L1", 4120), ("L2", 3540), ("L3", 4680))]
    return {
        "type": "answer",
        "text": ("Viime yönä valmistui **12 340 kpl** (L1 4 120, L2 3 540, L3 4 680). "
                 "Kertakysymys: luku ja minikaavio, ei tallenneta kaaviorekisteriin."),
        "matched_chart": None,
        "chart": _chart("bar", "Viime yön tuotanto linjoittain", rows, x="date"),
        "receipt": _receipt("SUM(valmistunut_kpl) WHERE shift = viimeisin yövuoro, "
                            "GROUP BY linja",
                            "MongoDB Atlas: production.shifts (suora kysely)", 3, "ad-hoc",
                            "Laskettu kyselyhetkellä — ei tallennettu"),
        "csv": _csv(rows),
    }


def _build_energy(q):
    rows = [{"date": d.isoformat(),
             "value": round(34.0 + 3.5 * ((d.toordinal() % 7) / 3.0) - (d.weekday() >= 5) * 2.0, 1)}
            for d in _days(7)]
    return {
        "type": "build",
        "text": ("Ei olemassa olevaa kaaviota eikä kanonista mittaria energiankulutukselle. "
                 "Ehdotan uutta hallittua mittaria **Energiankulutus (kWh/tonni)** — "
                 "pyyntö kirjataan Data stewardille hyväksyttäväksi (build-less -mittari: "
                 "uusi kaavio vain, kun mitään ei voi uudelleenkäyttää)."),
        "matched_chart": None,
        "chart": _chart("line", "Energiankulutus kWh/tonni, 7 pv (luonnos)", rows),
        "receipt": _receipt("SUM(kWh_mittari) / SUM(tuotanto_t) — EI VIELÄ KANONINEN, "
                            "odottaa Data stewardin hyväksyntää",
                            "MongoDB Atlas: energy.meters (raakadata)", 21, "luonnos v0.1",
                            "Päivitetty tänään 05:40 (energiamittarien lataus)"),
        "csv": _csv(rows),
    }
