# Käynnistysohje (Mac ja Windows)

Ohjeilla sovellus käynnistyy nykyisellä koodilla. Ympäristömuuttujat ladataan automaattisesti `.env`-tiedostosta käynnistyksen yhteydessä (python-dotenv), erillistä latausta ei tarvita.

Varmista ensin, että `.env`-tiedostossa on rivi:

```
GEMINI_MODEL=gemini-3.8-flash
```

## Mac (Terminal)

Ensimmäisellä kerralla:

```bash
cd fastapi+vue
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Joka käynnistyksellä:

```bash
cd fastapi+vue
source .venv/bin/activate
python -m uvicorn app.main:app --port 8000
```

## Windows (PowerShell)

Ensimmäisellä kerralla:

```powershell
cd fastapi+vue
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Jos `Activate.ps1` ei suostu käynnistymään, aja kerran tämä ja yritä uudelleen:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Joka käynnistyksellä:

```powershell
cd fastapi+vue
.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --port 8000
```

## Molemmilla

- Avaa selaimessa **http://localhost:8000**.
- Käytä aina `python -m uvicorn` eikä pelkkää `uvicorn`, muuten käynnistyy väärä Python-asennus.
