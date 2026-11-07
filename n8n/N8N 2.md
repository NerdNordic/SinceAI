# n8n: governance-skannaus (MongoDB Atlas)

n8n Cloud lukee kaaviorekisterin suoraan MongoDB Atlasista viiden minuutin välein ja kirjoittaa kantaan ehdotukset kaavioista, jotka kannattaa sertifioida tai poistaa. Data Steward hyväksyy tai hylkää ne sovelluksessa. **Automaatio valvoo, ihminen päättää.**

Backendin ei tarvitse olla n8n:n tavoitettavissa: molemmat käyttävät samaa tietokantaa.

```
Joka 5. minuutti ─► Hae kaaviot ─► Hae odottavat ehdotukset ─► Valitse ehdotettavat ─► Tallenna ehdotus ─► Audit-merkintä ─► Kirjaa audit logiin
                    chart_registry   proposals (pending)          (säännöt, ei tuplia)    proposals           audit_log
```

## Säännöt

| Ehdotus | Ehto | Bayerin sääntö |
|---|---|---|
| Sertifioi | tila `active` ja vähintään 2 roolia tai vähintään 3 käyttökertaa | RULE-005 High reach requires trust |
| Poista | tila `active` tai `certified` eikä käyttöä `RETIRE_IDLE_MINUTES`-aikaan (oletus 30 vrk) | Build less |

Jos kaaviolla on jo odottava ehdotus, uutta ei luoda.

## 1. Päästä n8n Cloud Atlasiin

Atlas: **Security → Network Access → Add IP Address**.
- Turvallisempi tapa: lisää n8n Cloudin IP-osoitteet. Ne löytyvät n8n:n ohjeista hakusanalla "n8n Cloud IP addresses".
- Nopein tapa demoon: **Allow access from anywhere** (`0.0.0.0/0`). Poista sääntö hackathonin jälkeen. Kanta on silti suojattu käyttäjätunnuksella ja salasanalla.

## 2. Tuo flow ja luo MongoDB-tunnus

1. n8n: **Workflows → Create Workflow → ⋯ → Import from File** → `build-less-governance-scan.json`.
2. Avaa node **Hae kaaviot** → **Credential → Create new** (MongoDB):
   - Configuration Type: **Connection String**
   - Connection String: sama `mongodb+srv://...` kuin backendin `.env`-tiedostossa
   - Database: `bayer_hackathon`
3. Valitse sama tunnus myös nodeihin **Hae odottavat ehdotukset**, **Tallenna ehdotus** ja **Kirjaa audit logiin**.
4. **Save**.

## 3. Testaa käsin

1. Luo sovelluksessa sertifioitava kaavio: kysy *Näytä toimitusvarmuus kuukausittain* tehtaan johtajana ja sitten *Miten toimitukset ovat onnistuneet kuukausittain?* vuoropäällikkönä.
2. n8n: **Test workflow**. Noden **Tallenna ehdotus** pitäisi kirjoittaa yksi ehdotus.
3. Sovelluksessa: **Data Steward** → kohdassa **Hyväksyntää odottavat** on uusi sertifiointiehdotus, ja audit logissa näkyy `proposal_created` (lähde n8n) → **Hyväksy**.
4. Kaavion tila on `certified`.
5. Paina **Test workflow** uudelleen. Uutta ehdotusta ei synny.

## 4. Demoa varten

- Kytke flow päälle **Active**-kytkimestä. Se ajetaan viiden minuutin välein. Demossa voit myös painaa **Test workflow**, jolloin ehdotus syntyy heti yleisön nähden.
- Poistoehdotuksen saat näkyviin, kun muutat noden **Valitse ehdotettavat** ensimmäisellä rivillä `RETIRE_IDLE_MINUTES = 43200` arvoksi `5`. Silloin viisi minuuttia käyttämättä ollut kaavio saa poistoehdotuksen. Aseta sama arvo myös backendin `.env`-tiedostoon (`RETIRE_IDLE_MINUTES=5`), jotta sovelluksen ehdotusmerkinnät näyttävät samaa.

## Vianetsintä

| Oire | Syy ja korjaus |
|---|---|
| `connection timed out` / `Server selection timed out` | n8n Cloudin IP ei ole Atlasin Network Accessissa (kohta 1) |
| `Authentication failed` | Väärä käyttäjä tai salasana connection stringissä |
| **Hae kaaviot** ei palauta mitään | Rekisteri on tyhjä tai tietokannan nimi on väärä (`bayer_hackathon`) |
| **Valitse ehdotettavat** ei tuota rivejä | Yhdelläkään kaaviolla ei ole ehdotusta, tai ehdotus odottaa jo. Tämä on normaalia. |
| Sama ehdotus syntyy toistuvasti | Varmista, että **Hae odottavat ehdotukset** ‑noden asetuksissa *Execute Once* ja *Always Output Data* ovat päällä |
| Tallennuksessa puuttuu kenttiä | Tarkista, että **Tallenna ehdotus** ‑noden *Fields*-kentässä on `_id,fingerprint,title,action,status,evidence,created_at,source` |
