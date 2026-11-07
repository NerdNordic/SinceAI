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
    "Näytä toimitusvarmuus kuukausittain": "Show monthly delivery reliability",
    "Mitkä tilaukset pitää tehdä tällä viikolla?": "Which orders need to be placed this week?",
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
    "Kaikki tehtaan toimitusvastuulla olevat tuote–markkina-parit, joille on meneillään ennustettua kysyntää. Tila kertoo täydennystarpeen kiireellisyyden.":
        "All product–market pairs the plant is responsible for supplying that have ongoing forecast demand. "
        "The status indicates how urgent replenishment is.",
    "Tuote–markkina-parit, jotka pitää tilata heti: varasto loppumassa (STOCKOUT_RISK) tai tilaus pitää tehdä viimeistään nyt (ORDER_NOW). Ajat perustuvat suositeltuun täydennyspolitiikkaan (assumptions.json).":
        "Product–market pairs that must be ordered now: stock is running out (STOCKOUT_RISK) or the order is due now (ORDER_NOW). "
        "Dates follow the recommended replenishment policy (assumptions.json).",
    "Kiireelliset parit (URGENT): täydennystä pitää ryhtyä valmistelemaan 14 päivän sisällä.":
        "Urgent pairs (URGENT): replenishment must start within 14 days.",
    "Toimitusvarmuus (On-Time In-Full): ajallaan ja täysimääräisenä toimitettujen osuus. Laskettu tehtaan tuote–markkina-parien kuukausikeskiarvona — sama kanoninen määritelmä kuin chatin toimitusvarmuuskaaviossa, joten luvut eivät voi erota toisistaan.":
        "Delivery reliability (On-Time In-Full): the share delivered on time and in full. Computed as the monthly mean over the "
        "plant's product–market pairs — the same canonical definition as the chat's On-Time In-Full chart, so the figures cannot disagree.",
    "Tehtaan tuote–markkina-parien ennustettu viikkokysyntä yhteensä (kpl/vko).":
        "Total forecast weekly demand over the plant's product–market pairs (units/week).",
    "Parit, joille suositeltu tilauspäivä osuu seuraavan 7 päivän sisään.":
        "Pairs whose recommended order date falls within the next 7 days.",
    "Parit, jotka ovat vielä pelastettavissa lentokuljetuksella: nopeutustilaus on teknisesti mahdollinen ja se ehtii ennen varaston loppumista.":
        "Pairs that can still be saved by air freight: an expedited order is technically possible and would arrive before the stock runs out.",
    "Priorisoitavat parit tuotannolle: loppumisriskin (STOCKOUT_RISK, ORDER_NOW) ja kiireellisyyden (URGENT) perusteella.":
        "Pairs to prioritize in production, based on stockout risk (STOCKOUT_RISK, ORDER_NOW) and urgency (URGENT).",
    "Build-less -mittarin kaikki käsitellyt pyynnöt. Chat-tyyppiset tervehdykset eivät lasku pyynnöiksi.":
        "All requests handled by the Build-less meter. Chat-type greetings do not count as requests.",
    "Pyyntöjä, jotka johtivat uuden kaavion rakentamiseen (BUILD). Build-less -periaatteen mukaan uusi kaavio syntyy vain, kun mitään olemassa olevaa ei voi uudelleenkäyttää.":
        "Requests that led to building a new chart (BUILD). Under the Build-less principle, a new chart is created only when no existing chart can be reused.",
    "Pyyntöjä, jotka hoidettiin ilman uutta kaaviota: REUSE (uudelleenkäyttö), EXTEND (laajennus) tai ANSWER (vastaus ilman kaaviota).":
        "Requests handled without a new chart: REUSE (reuse), EXTEND (extend) or ANSWER (answer without a chart).",
    "Kaaviorekisterin ehdotukset sertifioitavaksi: aktiivinen kaavio, jota on käyttänyt vähintään kaksi roolia tai jolla on vähintään kolme käyttökertaa.":
        "Chart registry proposals for certification: an active chart used by at least two roles or with at least three uses.",
    "Kaaviorekisterin poistoehdotukset: kaaviot, jotka ovat olleet käyttämättä pidempään kuin elinkaarisääntö sallii (RETIRE_IDLE_MINUTES).":
        "Chart registry retirement proposals: charts unused for longer than the lifecycle rule allows (RETIRE_IDLE_MINUTES).",
    "OTIF % ({plant}, keskiarvo)": "OTIF % ({plant}, mean)",
    "product_market_monthly · {count} riviä · {first} – {last}": "product_market_monthly · {count} rows · {first} – {last}",
    "replenishment (viikkokysyntä tuotteittain)": "replenishment (weekly demand by product)",
    "replenishment · tuote × markkina": "replenishment · product × market",
    "replenishment · tila {statuses}": "replenishment · status {statuses}",
    "replenishment · days-to-order ≤ 7 pv": "replenishment · days-to-order ≤ 7 days",
    "replenishment · nopeutustilaus mahdollinen": "replenishment · expedite possible",
    "request_log · {count} pyyntöä · uudelleenkäyttöaste {rate} %": "request_log · {count} requests · reuse rate {rate} %",
    "chart_registry · ehdotus {which}": "chart_registry · proposal {which}",
    "uudelleenkäyttö": "reuse", "laajennus": "extend", "vastaus ilman kaaviota": "answer without a chart",
    "uusi kaavio": "new chart", "tarkennuspyyntö": "clarification request", "chat-tervehdys": "chat greeting",
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
