"""HTTP API for the Streamlit dashboard and n8n calculation callbacks.

    uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import io
import logging
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictBool, model_validator
from pymongo.errors import PyMongoError

from . import briefing as briefing_mod
from . import config, engine, integration_store, metrics, n8n_client, replenishment_api
from .db import get_db
from .integration_models import AskIn, Identifier
from .security import effective_role, require_app_access, require_secret, require_steward

app = FastAPI(title="Build Less assistant", version="0.2.0", dependencies=[Depends(require_app_access)])
logger = logging.getLogger(__name__)


def integrated() -> bool:
    if config.KPI_BACKEND not in {"local", "n8n"}:
        raise HTTPException(503, "KPI_BACKEND must be local or n8n")
    if config.APP_AUTH_MODE == "proxy" and config.KPI_BACKEND != "n8n":
        raise HTTPException(503, "Public deployments require the scoped n8n backend")
    return config.KPI_BACKEND == "n8n"


@app.exception_handler(n8n_client.UpstreamError)
async def upstream_error(request: Request, exc: n8n_client.UpstreamError):
    return JSONResponse(status_code=exc.status, content={
        "type": "error", "code": exc.code, "message": exc.message,
        "request_id": getattr(request.state, "request_id", None),
        "sessionId": getattr(request.state, "session_id", None), "data_quality_warnings": [],
    })


@app.exception_handler(PyMongoError)
async def database_error(request: Request, exc: PyMongoError):
    logger.warning("Database operation failed error_type=%s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database is temporarily unavailable"})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error("API operation failed error_type=%s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "The operation could not be completed"})


class ProposeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str  # retire | certify; validated by the selected backend


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: Identifier | None = None
    approval_id: Identifier | None = None
    approved: StrictBool
    approver: str = "Data Steward"

    @model_validator(mode="after")
    def identifier_required(self):
        if bool(self.proposal_id) == bool(self.approval_id):
            raise ValueError("Supply exactly one of proposal_id or approval_id")
        return self


@app.get("/")
def index():
    return {"service": "SinceAI API", "frontend": "Streamlit", "docs": "/docs"}


@app.get("/api/roles")
def roles(request: Request):
    trusted = getattr(request.state, "role", None)
    return [{"id": k, **v} for k, v in config.ROLES.items() if not trusted or k == trusted]


@app.get("/api/settings")
def settings():
    return {"backend": "n8n" if integrated() else "local", "auth_mode": config.APP_AUTH_MODE}


@app.get("/api/briefing/{role}")
def get_briefing(role: str, request: Request):
    integrated()
    return briefing_mod.briefing(effective_role(request, role))


@app.post("/api/ask")
def ask(body: AskIn, request: Request):
    body.role = effective_role(request, body.role)
    request.state.request_id = str(body.request_id)
    request.state.session_id = str(body.sessionId)
    if integrated():
        return n8n_client.ask(body, request.state.actor)
    if body.chart_id:
        raise HTTPException(400, "Saved chart refresh requires KPI_BACKEND=n8n")
    return engine.ask(body.question, body.role)


@app.get("/api/results/{result_id}/raw.csv")
def raw(result_id: str):
    if integrated():
        raise HTTPException(404, "Integrated results provide CSV in the chat response")
    res = get_db().results.find_one({"_id": result_id})
    if not res:
        raise HTTPException(404, "unknown result")
    df = metrics.raw_rows(res["source"])
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=raw_{result_id}.csv"})


@app.get("/api/meter")
def meter(request: Request, role: str | None = None):
    selected = effective_role(request, role)
    return integration_store.meter(selected) if integrated() else engine.meter()


@app.get("/api/registry")
def registry(request: Request):
    require_steward(request)
    return integration_store.registry() if integrated() else engine.registry()


@app.post("/api/registry/{fingerprint}/propose")
def propose(fingerprint: Identifier, body: ProposeIn, request: Request):
    require_steward(request)
    if integrated():
        if body.action not in {"certify", "retire"}:
            raise HTTPException(400, "action must be retire or certify")
        request.state.request_id = str(uuid4())
        return n8n_client.govern({"action": "propose", "chart_id": fingerprint,
                                 "proposal_action": body.action, "role": "data_steward",
                                 "actor": request.state.actor, "request_id": request.state.request_id})
    try:
        return engine.propose(fingerprint, body.action)
    except KeyError:
        raise HTTPException(404, "unknown chart")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/registry/decision")
def decision(body: DecisionIn, request: Request, x_webhook_secret: str | None = Header(default=None)):
    """Called by the n8n approval playbook (or the UI) with the Data Steward's answer."""
    require_steward(request)
    if integrated():
        if x_webhook_secret:
            raise HTTPException(409, "Legacy callbacks cannot decide n8n-owned approvals")
        if not body.approval_id:
            raise HTTPException(400, "approval_id is required in n8n mode")
        request.state.request_id = str(uuid4())
        return n8n_client.govern({"action": "decide", "approval_id": body.approval_id,
                                 "approved": body.approved, "role": "data_steward",
                                 "actor": request.state.actor, "request_id": request.state.request_id})
    if not body.proposal_id:
        raise HTTPException(400, "proposal_id is required in local mode")
    require_secret(config.WEBHOOK_SECRET, x_webhook_secret)
    try:
        return engine.decide_proposal(body.proposal_id, body.approved, request.state.actor)
    except KeyError:
        raise HTTPException(404, "unknown proposal")


@app.get("/api/proposals")
def proposals(request: Request):
    require_steward(request)
    if integrated():
        return integration_store.approvals()
    return list(get_db().proposals.find({}, {"_id": 1, "fingerprint": 1, "title": 1, "action": 1, "status": 1,
                                             "decided_by": 1}).sort("created_at", -1))


@app.get("/api/audit")
def audit(request: Request):
    require_steward(request)
    return integration_store.audit() if integrated() else engine.audit()


@app.post("/api/internal/replenishment")
def replenishment(body: replenishment_api.ReplenishmentIn,
                  x_replenishment_secret: str | None = Header(default=None)):
    require_secret(config.N8N_REPLENISHMENT_SECRET, x_replenishment_secret)
    return replenishment_api.calculate(body)


@app.get("/api/health")
def health():
    mode = "n8n" if integrated() else "local"
    if not config.MONGODB_URI:
        return JSONResponse(status_code=503, content={"ok": False, "backend": mode,
                                                     "detail": "MONGODB_URI is not configured"})
    db = get_db()
    db.command("ping")
    return {"ok": True, "backend": mode}
