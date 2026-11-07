"""HTTP API + web UI.

    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import briefing as briefing_mod
from . import card_detail as card_detail_mod
from . import config, dashboards, engine, metrics
from .db import get_db
from .i18n import Language, role_label

app = FastAPI(title="Build Less assistant", version="0.1.0")
STATIC = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AskIn(BaseModel):
    role: str
    question: str
    session_id: str | None = None   # same id = same conversation (follow-up questions)
    language: Language = "en"


class ProposeIn(BaseModel):
    action: str  # retire | certify


class DecisionIn(BaseModel):
    proposal_id: str
    approved: bool
    approver: str = "Data Steward"


class PinIn(BaseModel):
    fingerprint: str


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/roles")
def roles(language: Language = "en"):
    return [{"id": k, **v, "label": role_label(k, language)} for k, v in config.ROLES.items()]


@app.get("/api/briefing/{role}")
def get_briefing(role: str, language: Language = "en"):
    if role not in config.ROLES:
        raise HTTPException(404, "unknown role")
    return briefing_mod.briefing(role, language)


@app.get("/api/briefing/{role}/card/{key}")
def get_card_detail(role: str, key: str):
    if role not in config.ROLES:
        raise HTTPException(404, "unknown role")
    try:
        return card_detail_mod.card_detail(role, key)
    except KeyError:
        raise HTTPException(404, "unknown card")


@app.post("/api/ask")
def ask(body: AskIn):
    if body.role not in config.ROLES:
        raise HTTPException(404, "unknown role")
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    return engine.ask(body.question.strip(), body.role, body.session_id, body.language)


@app.get("/api/conversations/{session_id}")
def conversation(session_id: str):
    conv = get_db().conversations.find_one({"_id": session_id})
    if not conv:
        raise HTTPException(404, "unknown conversation")
    return conv


@app.get("/api/results/{result_id}/raw.csv")
def raw(result_id: str):
    res = get_db().results.find_one({"_id": result_id})
    if not res:
        raise HTTPException(404, "unknown result")
    df = metrics.raw_rows(res["source"])
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=raw_{result_id}.csv"})


@app.get("/api/meter")
def meter():
    return engine.meter()


@app.get("/api/registry")
def registry():
    return engine.registry()


@app.post("/api/registry/{fingerprint}/propose")
def propose(fingerprint: str, body: ProposeIn):
    try:
        return engine.propose(fingerprint, body.action)
    except KeyError:
        raise HTTPException(404, "unknown chart")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/registry/decision")
def decision(body: DecisionIn, x_webhook_secret: str | None = Header(default=None)):
    """Called by the n8n approval playbook (or the UI) with the Data Steward's answer."""
    if config.WEBHOOK_SECRET and x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(401, "bad webhook secret")
    try:
        return engine.decide_proposal(body.proposal_id, body.approved, body.approver)
    except KeyError:
        raise HTTPException(404, "unknown proposal")


@app.get("/api/dashboards/{role}")
def dashboard(role: str, tiles: bool = True):
    """Certified charts of a role as live tiles. tiles=false returns metadata only."""
    if role not in config.ROLES:
        raise HTTPException(404, "unknown role")
    return dashboards.get_dashboard(role, tiles=tiles)


@app.post("/api/dashboards/{role}/charts")
def pin_chart(role: str, body: PinIn):
    """Data steward pins a certified chart to a role's dashboard."""
    if role not in config.ROLES:
        raise HTTPException(404, "unknown role")
    try:
        return dashboards.pin(role, body.fingerprint)
    except KeyError:
        raise HTTPException(404, "unknown chart")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/dashboards/{role}/charts/{fingerprint}")
def unpin_chart(role: str, fingerprint: str):
    if role not in config.ROLES:
        raise HTTPException(404, "unknown role")
    return dashboards.unpin(role, fingerprint)


@app.get("/api/proposals")
def proposals():
    return list(get_db().proposals.find({}, {"_id": 1, "fingerprint": 1, "title": 1, "action": 1, "status": 1,
                                             "decided_by": 1}).sort("created_at", -1))


@app.get("/api/audit")
def audit():
    return engine.audit()


@app.get("/api/health")
def health():
    db = get_db()
    return {"ok": True, "db": db.name, "charts": db.chart_registry.count_documents({}),
            "requests": db.request_log.count_documents({}), "model": config.GEMINI_MODEL}
