"""Settings from environment variables."""

import os
from datetime import date

MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DB = os.environ.get("MONGODB_DB", "bayer_hackathon")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")          # approval playbook webhook in n8n
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")            # shared secret for n8n -> backend callbacks
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
DEMO_PLANT = os.environ.get("DEMO_PLANT", "Plant-A")
REVIEW_DAYS = int(os.environ.get("REVIEW_DAYS", "90"))

# Explicit opt-in: never fall back to local writes after an n8n timeout.
KPI_BACKEND = os.environ.get("KPI_BACKEND", "local")
N8N_KPI_WEBHOOK_URL = os.environ.get("N8N_KPI_WEBHOOK_URL", "")
N8N_GOVERNANCE_WEBHOOK_URL = os.environ.get("N8N_GOVERNANCE_WEBHOOK_URL", "")
N8N_KPI_WEBHOOK_SECRET = os.environ.get("N8N_KPI_WEBHOOK_SECRET", "")
N8N_KPI_TIMEOUT_SECONDS = float(os.environ.get("N8N_KPI_TIMEOUT_SECONDS", "90"))
N8N_REPLENISHMENT_SECRET = os.environ.get("N8N_REPLENISHMENT_SECRET", "")

# Local mode permits the existing role selector only from loopback. A public
# deployment requires an authenticated reverse proxy that replaces these headers.
APP_AUTH_MODE = os.environ.get("APP_AUTH_MODE", "local")
APP_PROXY_SECRET = os.environ.get("APP_PROXY_SECRET", "")
SINCEAI_API_URL = os.environ.get("SINCEAI_API_URL", "http://127.0.0.1:8000")


def today() -> date:
    v = os.environ.get("TODAY")
    return date.fromisoformat(v) if v else date.today()


ROLES = {
    "tehtaan_johtaja": {"label": "Tehtaan johtaja", "plant": DEMO_PLANT},
    "vuoropaallikko": {"label": "Vuoropäällikkö", "plant": DEMO_PLANT},
    "tuotantotyontekija": {"label": "Tuotantotyöntekijä", "plant": DEMO_PLANT},
    "data_steward": {"label": "Data Steward", "plant": None},
}
