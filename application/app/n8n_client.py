"""Server-only n8n transport. Redirects, environment proxies and retries are disabled."""

from __future__ import annotations

import json
import logging
import math
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from . import config
from .integration_models import AskIn, GovernanceResponse, KPIResponse

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 8_000_000


def finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def reject_constant(value: str):
    raise ValueError("Non-finite JSON constant")


class UpstreamError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def post_json(url: str, payload: dict) -> dict:
    try:
        parsed = urlsplit(url)
        parsed.port  # Reject malformed ports before passing the URL to HTTPX.
    except ValueError:
        raise UpstreamError(503, "N8N_NOT_CONFIGURED", "Configure a valid HTTPS n8n URL") from None
    timeout = config.N8N_KPI_TIMEOUT_SECONDS
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or not config.N8N_KPI_WEBHOOK_SECRET
            or not math.isfinite(timeout) or not 1 <= timeout <= 120):
        raise UpstreamError(503, "N8N_NOT_CONFIGURED", "Configure an HTTPS n8n URL, credential and timeout (1-120 seconds)")
    request_id = payload.get("request_id", "")
    try:
        # The API routes are synchronous def routes: blocking I/O runs in FastAPI's
        # threadpool, never on the event loop. No automatic replay of write requests.
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=5, pool=5),
                          follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", url, json=payload, headers={
                "X-KPI-Webhook-Secret": config.N8N_KPI_WEBHOOK_SECRET,
                "Accept": "application/json",
            }) as response:
                if not 200 <= response.status_code < 300:
                    status = response.status_code if response.status_code in {400, 403, 404, 409, 429, 503, 504} else 502
                    raise UpstreamError(status, "N8N_REQUEST_FAILED", "n8n could not complete the request")
                if response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                    raise UpstreamError(502, "N8N_INVALID_RESPONSE", "n8n returned a non-JSON response")
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise UpstreamError(502, "N8N_RESPONSE_TOO_LARGE", "n8n response exceeded the size limit")
                    chunks.append(chunk)
                data = json.loads(b"".join(chunks), parse_float=finite_float, parse_constant=reject_constant)
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                if data.get("type") == "error":
                    raise UpstreamError(502, "N8N_REQUEST_FAILED", "n8n reported an application error")
                return data
    except httpx.TimeoutException:
        logger.warning("n8n timeout request_id=%s", request_id)
        raise UpstreamError(504, "N8N_TIMEOUT", "n8n timed out; the request may already have been processed") from None
    except httpx.RequestError:
        logger.warning("n8n unavailable request_id=%s", request_id)
        raise UpstreamError(503, "N8N_UNAVAILABLE", "Cannot reach n8n") from None
    except httpx.InvalidURL:
        raise UpstreamError(503, "N8N_NOT_CONFIGURED", "Configure a valid HTTPS n8n URL") from None
    except (ValueError, UnicodeError, RecursionError):
        raise UpstreamError(502, "N8N_INVALID_RESPONSE", "n8n returned invalid JSON") from None


def ask(body: AskIn, actor: str) -> dict:
    payload = body.model_dump(mode="json", exclude={"question"})
    payload.update(message=body.question, actor=actor)
    # n8n must enforce this server-derived scope, including saved-chart refresh.
    plant = config.ROLES[body.role]["plant"]
    payload["scope"] = {"plants": [plant] if plant else [], "all_plants": plant is None}
    data = post_json(config.N8N_KPI_WEBHOOK_URL, payload)
    try:
        parsed = KPIResponse.model_validate(data)
        if parsed.sessionId != body.sessionId or parsed.request_id != body.request_id:
            raise ValueError("Correlation IDs do not match")
        return parsed.model_dump(mode="json")
    except (ValidationError, ValueError):
        raise UpstreamError(502, "N8N_INVALID_RESPONSE", "n8n response does not match the KPI contract") from None


def govern(payload: dict) -> dict:
    data = post_json(config.N8N_GOVERNANCE_WEBHOOK_URL, payload)
    try:
        parsed = GovernanceResponse.model_validate(data)
        if payload["action"] == "decide":
            expected = "approved" if payload["approved"] else "rejected"
            if parsed.approval_id != payload["approval_id"] or parsed.status != expected:
                raise ValueError("Decision response does not match request")
        elif parsed.chart_id != payload["chart_id"] or parsed.status != "pending":
            raise ValueError("Proposal response does not match request")
        return parsed.model_dump(mode="json")
    except (ValidationError, ValueError):
        raise UpstreamError(502, "N8N_INVALID_RESPONSE", "n8n response does not match the governance contract") from None
