"""Deterministic presentation translations; identifiers and source data stay intact."""

import re
from typing import Literal

Language = Literal["en", "fi"]
LANGUAGES = {"en": "English", "fi": "Finnish"}

# Finnish source strings keep the existing calculation code and API fields stable.
ENGLISH = {
    "Tehtaan johtaja": "Plant director", "Vuoropäällikkö": "Shift supervisor",
    "Tuotantotyöntekijä": "Production worker", "Data Steward": "Data steward",
    "Pyyntöjä": "Requests", "Uusia kaavioita": "New charts",
    "Hoidettu ilman uutta kaaviota": "Handled without a new chart",
    "Sertifiointiehdotuksia": "Certification proposals", "Poistoehdotuksia": "Retirement proposals",
    "Tuote–markkina-pareja": "Product–market pairs", "Loppumisriski / tilaa nyt": "Stockout risk / order now",
    "vs tavoite": "vs target",
    "Kiireelliset (≤ 14 pv)": "Urgent (≤ 14 days)", "Volyymi": "Volume",
    "Tilattava nyt": "Order now", "Tilattava tällä viikolla": "Order this week",
    "Pelastettavissa lentokuljetuksella": "Can be expedited by air",
    "Priorisoitavia tuotteita": "Products to prioritize", "Tehtaan volyymi": "Plant volume",
    "kpl/vko": "units/week", "kpl": "units", "viikkoa": "weeks",
    "päivää tilauspäivään (miinus = myöhässä)": "days until order date (negative = overdue)",
    "loppumisriski": "stockout risk", "tilaa nyt": "order now", "kiireellinen": "urgent",
    "suunnittele": "plan", "kunnossa": "OK", "ei toimituksia": "no shipments",
    "{mode} viimeistään {date}": "{mode} by {date}",
    "Data: kuukausitaso, viimeisin {month}. Varastotilanne {date}. {conflicts} tuote–markkina-parilla varastolähteet ovat ristiriidassa.":
        "Data: monthly, latest {month}. Inventory as of {date}. Inventory sources conflict for {conflicts} product–market pairs.",
    "Nettomyynnin summa (M€) valituilta riveiltä.": "Sum of net sales (M€) over the selected rows.",
    "Nettomyynnin muutos edelliseen kuukauteen (%), laskettuna ryhmän summasta.":
        "Month-over-month change in net sales (%), calculated from group totals.",
    "Toimitettujen kappaleiden summa.": "Sum of shipped units.",
    "Varaston riittävyys viikkoina, rivien keskiarvo.": "Inventory coverage in weeks, averaged over rows.",
    "Ajallaan ja täysimääräisenä toimitettujen osuus (%), rivien keskiarvo.":
        "On-time in-full deliveries (%), averaged over rows.",
    "Nettomyynti miinus ennuste (M€), ryhmän summista.": "Net sales minus forecast (M€), from group totals.",
    "Markkinoille pääsyn kattavuus (%), rivien keskiarvo.": "Market access coverage (%), averaged over rows.",
    "Kysyntäennusteen tarkkuus (%) Supply_Operations-tilannekuvasta, keskiarvo.":
        "Mean demand forecast accuracy (%) from the Supply_Operations snapshot.",
    "Milloin varasto loppuu ja mihin mennessä täydennys on tilattava (tuote × markkina), oletukset assumptions.json.":
        "Stock runout and replenishment order deadlines per product × market, using assumptions.json.",
    "Valinnoilla ei löytynyt rivejä.": "No rows match the selection.",
    "Valitulla tehtaalla ei löytynyt rivejä.": "No rows match the selected plant.",
    "Valinnoilla ei löytynyt dataa.": "No data matches the selection.",
    "Kasvu = viimeisin kuukausi ({month}) vs. edellinen.": "Growth = latest month ({month}) versus the previous month.",
    "{count}/{total} lähderiviä on ennustetyyppisiä (forecast_like), ei toteumaa.":
        "{count}/{total} source rows are forecast-like (forecast_like), rather than actuals.",
    "{count} ennustetyyppistä riviä jätettiin pois (vain toteuma).":
        "{count} forecast-like rows were excluded (actuals only).",
    "Tilannekuva: kuukausihistoriaa ei ole.": "Snapshot: no monthly history is available.",
    "Päiviä suositeltuun tilauspäivään": "Days until recommended order date",
    "Datan laatuliput: {flags}": "Data quality flags: {flags}",
    "Voin näyttää tehtaan luvut ja kaaviot hallituilla määritelmillä: {metrics}. Kysy esimerkiksi, mitä pitää tilata tällä viikolla.":
        "I can show plant figures and charts using governed definitions: {metrics}. For example, ask what needs to be ordered this week.",
    "En löytänyt tähän hallittua mittaria. Voin näyttää: {metrics}.":
        "I could not find a governed metric for this request. I can show: {metrics}.",
    "{count} tuote–markkina-paria. Kiireellisin: {product} → {market}, tilaa viimeistään {date} ({status}).":
        "{count} product–market pairs. Most urgent: {product} → {market}, order by {date} ({status}).",
    "noussut": "increased", "laskenut": "decreased", "pysynyt ennallaan": "unchanged",
    "{label}: {value} {unit} ({month}), {trend} edellisestä ({previous} {unit}, {previous_month}).":
        "{label}: {value} {unit} ({month}), {trend} compared with the previous period ({previous} {unit}, {previous_month}).",
    "Viimeisimmät arvot: {series}.": "Latest values: {series}.",
    "Sama kaavio on jo olemassa: \"{title}\" (omistaja {owner}{created}). {action}":
        "This chart already exists: \"{title}\" (owner {owner}{created}). {action}",
    ", luotu {date}": ", created {date}",
    "Näytetään päivitetyllä datalla.": "Showing updated data.",
    "Näytetään sama kaavio uusilla suodattimilla, uutta kaaviota ei luotu.":
        "Showing the same chart with new filters; no new chart was created.",
    "Kertaluonteinen kysymys: luku lasketaan hallitulla määritelmällä, mutta kaaviota ei tallenneta rekisteriin.":
        "One-off question: the value is computed using a governed definition without saving a chart to the registry.",
    "Vastaavaa kaaviota ei löytynyt rekisteristä. Uusi kaavio rekisteröitiin: omistaja {owner}, kanoninen KPI {kpi}, tarkistus {date}.":
        "No matching chart was found in the registry. A new chart was registered: owner {owner}, canonical KPI {kpi}, review by {date}.",
}

METRIC_FI = {
    "Net Sales": "Nettomyynti", "Net Sales Growth": "Nettomyynnin kasvu",
    "Units Shipped": "Toimitetut kappaleet", "Inventory Coverage": "Varaston riittävyys",
    "On-Time In-Full": "Toimitusvarmuus", "Forecast Variance": "Ennustepoikkeama",
    "Market Access Coverage": "Markkinoille pääsyn kattavuus",
    "Demand Forecast Accuracy": "Kysyntäennusteen tarkkuus",
    "Replenishment Reorder-By Date": "Täydennyksen tilauspäivä",
}

FLAG_LABELS = {
    "FEW_ACTUAL_MONTHS": ("Few months of actuals", "Vähän toteumakuukausia"),
    "STALE_ACTUALS": ("Stale actuals", "Vanhentunut toteuma"),
    "NEVER_SHIPPED": ("Never shipped", "Ei aiempia toimituksia"),
    "ZERO_SHIPMENT_MONTH": ("Month with no shipments", "Kuukausi ilman toimituksia"),
    "VOLATILE_SHIPMENTS": ("Volatile shipments", "Vaihteleva toimitusmäärä"),
    "INVENTORY_SOURCE_CONFLICT": ("Conflicting inventory sources", "Ristiriitaiset varastolähteet"),
    "LATEST_MONTH_FORECAST_LIKE": ("Latest month is forecast-like", "Viimeisin kuukausi on ennustetyyppinen"),
    "ZERO_INVENTORY": ("Zero inventory", "Tyhjä varasto"),
}


def flag_label(code: str, language: Language) -> str:
    labels = FLAG_LABELS.get(code)
    return f"{labels[language == 'fi']} ({code})" if labels else code


def transport_label(mode: str, language: Language) -> str:
    labels = {"air": "lentokuljetus", "road": "maantiekuljetus", "sea": "merikuljetus"}
    return labels.get(mode, mode) if language == "fi" else mode


def text(source: str, language: Language = "en", **values: object) -> str:
    template = ENGLISH.get(source, source) if language == "en" else source
    return template.format(**values) if values else template


def metric_label(name: str, language: Language) -> str:
    return METRIC_FI.get(name, name) if language == "fi" else name


def role_label(role: str, language: Language) -> str:
    from .config import ROLES

    return text(ROLES[role]["label"], language)


def calculation_steps(steps: list[str], language: Language) -> list[str]:
    """Translate explanatory words without changing formulas, identifiers or values."""
    if language == "en":
        return steps
    words = {"months": "kuukautta", "units/week": "kpl/viikko", "units": "kpl", "wk": "vk",
             "cover": "riittävyys", "production": "tuotanto", "transport": "kuljetus",
             "mean": "keskiarvo", "safety": "varmuus", "air": "lento", "road": "maantie", "sea": "meri"}
    pattern = r"\b(" + "|".join(re.escape(k) for k in words) + r")\b"
    return [re.sub(pattern, lambda m: words[m[0]], step) for step in steps]
