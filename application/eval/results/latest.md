# Evaluation run a6b93faf2bee

Model `gemini-3.8-flash`, prompt `v5-clarify-followup`, 2 repeats per question, run 2026-11-07 21:51 UTC.

| Measure | Result |
|---|---|
| Interpretation accuracy | 40/40 (100 %) |
| Consistency across repeats | 39/40 (98 %) |
| Unsupported questions answered by guessing | 0/4 |
| Errors | 0 |

| Category | Passed |
|---|---|
| ei dataa | 4/4 |
| kaupallinen | 7/7 |
| keskustelu | 3/3 |
| talous | 6/6 |
| tuotanto | 20/20 |

| Language | Passed |
|---|---|
| en | 13/13 |
| fi | 27/27 |

| # | Role | Question | Result | Consistent | Problems |
|---|---|---|---|---|---|
| q01 | tehtaan_johtaja | Näytä toimitusvarmuus kuukausittain | ✓ | ✓ |  |
| q02 | vuoropaallikko | Miten toimitukset ovat onnistuneet kuukausittain? | ✓ | ✓ |  |
| q03 | tehtaan_johtaja | How reliable have our deliveries been month by month? | ✓ | ✓ |  |
| q04 | tehtaan_johtaja | Toimitusvarmuus markkinoittain | ✓ | ✓ |  |
| q05 | tehtaan_johtaja | OTIF by market | ✓ | ✓ |  |
| q06 | tehtaan_johtaja | Toimitusvarmuus kuukausittain Plant B:llä | ✓ | ✓ |  |
| q07 | vuoropaallikko | OTIF Ruotsissa kuukausittain | ✓ | ✓ |  |
| q08 | vuoropaallikko | Mitkä tilaukset pitää tehdä tällä viikolla? | ✓ | ✓ |  |
| q09 | vuoropaallikko | Which orders must be placed right now? | ✓ | ✓ |  |
| q10 | tehtaan_johtaja | Mitkä tuotteet ovat loppumisvaarassa? | ✓ | ✓ |  |
| q11 | tuotantotyontekija | Mitä tuotteita priorisoidaan? | ✓ | ✗ |  |
| q12 | tehtaan_johtaja | Milloin Xarelton varasto loppuu Suomessa? | ✓ | ✓ |  |
| q13 | tuotantotyontekija | Paljonko tuotteita lähetettiin kuukausittain? | ✓ | ✓ |  |
| q14 | tehtaan_johtaja | Units shipped per product | ✓ | ✓ |  |
| q15 | tehtaan_johtaja | Toimitetut kappaleet markkinoittain | ✓ | ✓ |  |
| q16 | tehtaan_johtaja | Varaston riittävyys tuotteittain | ✓ | ✓ |  |
| q17 | vuoropaallikko | Weeks of inventory cover by market | ✓ | ✓ |  |
| q18 | tehtaan_johtaja | Varaston riittävyys kuukausittain tuotteittain | ✓ | ✓ |  |
| q19 | tehtaan_johtaja | Kerendian toimitusvarmuus kuukausittain | ✓ | ✓ |  |
| q20 | tuotantotyontekija | How many units of Nubeqa did we ship each month? | ✓ | ✓ |  |
| q21 | country_manager_fi | Nettomyynti kuukausittain | ✓ | ✓ |  |
| q22 | country_manager_fi | Net sales by product | ✓ | ✓ |  |
| q23 | data_steward | Nubeqan myynti Saksassa kuukausittain | ✓ | ✓ |  |
| q24 | data_steward | Myynnin kasvu markkinoittain | ✓ | ✓ |  |
| q25 | country_manager_fi | Sales growth by product | ✓ | ✓ |  |
| q26 | country_manager_fi | Market access -kattavuus tuotteittain | ✓ | ✓ |  |
| q27 | data_steward | How well do patients get access to our products in each country? | ✓ | ✓ |  |
| q28 | finance_controller | Ennustepoikkeama tuotteittain | ✓ | ✓ |  |
| q29 | finance_controller | How far off were we from the forecast by market? | ✓ | ✓ |  |
| q30 | finance_controller | Toteuma vs ennuste kuukausittain | ✓ | ✓ |  |
| q31 | finance_controller | Ennustepoikkeama tuotteittain, vain toteuma | ✓ | ✓ |  |
| q32 | finance_controller | Ennustetarkkuus tuotteittain | ✓ | ✓ |  |
| q33 | finance_controller | Forecast accuracy by market | ✓ | ✓ |  |
| q34 | data_steward | Mikä on budjettipoikkeama? | ✓ | ✓ |  |
| q35 | data_steward | Show gross-to-net rate by market | ✓ | ✓ |  |
| q36 | tehtaan_johtaja | Mikä on linjan 3 käyttöaste tänään? | ✓ | ✓ |  |
| q37 | data_steward | Digitaalinen sitoutuminen kanavittain | ✓ | ✓ |  |
| q38 | tehtaan_johtaja | Mitä osaat? | ✓ | ✓ |  |
| q39 | vuoropaallikko | Kiitos! | ✓ | ✓ |  |
| q40 | tuotantotyontekija | Hi, how can you help me? | ✓ | ✓ |  |
