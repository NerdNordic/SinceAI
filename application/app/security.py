"""Application identity and service credentials; no secrets are sent to the UI."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from . import config


def require_secret(expected: str, supplied: str | None) -> None:
    if not expected:
        raise HTTPException(503, "Required authentication credential is not configured")
    if not supplied or not secrets.compare_digest(expected.encode(), supplied.encode()):
        raise HTTPException(401, "Invalid service credential")


def require_app_access(request: Request) -> None:
    # These two service routes use their own authentication and disclose no UI data.
    if request.url.path in {"/api/health", "/api/internal/replenishment"}:
        return
    # Preserve the original approval callback, but fail closed if unconfigured.
    if (request.url.path == "/api/registry/decision"
            and request.headers.get("x-webhook-secret")):
        require_secret(config.WEBHOOK_SECRET, request.headers["x-webhook-secret"])
        request.state.actor = "n8n approval callback"
        request.state.role = "data_steward"
        return
    if config.APP_AUTH_MODE == "local":
        host = request.client.host if request.client else ""
        test_client = host == "testclient"  # Starlette's in-process transport only.
        if not test_client and (host not in {"127.0.0.1", "::1"}
                                or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}):
            raise HTTPException(403, "Local demo access requires loopback; configure proxy authentication")
        request.state.role = None
        request.state.actor = "Local demo"
    elif config.APP_AUTH_MODE == "proxy":
        require_secret(config.APP_PROXY_SECRET, request.headers.get("x-sinceai-proxy-secret"))
        role = request.headers.get("x-sinceai-role", "")
        actor = request.headers.get("x-sinceai-user", "")
        if role not in config.ROLES or not actor.strip() or len(actor) > 200:
            raise HTTPException(403, "Authenticated proxy identity is missing or invalid")
        request.state.role = role
        request.state.actor = actor
    else:
        raise HTTPException(503, "APP_AUTH_MODE must be local or proxy")
    # JSON endpoints need no cross-origin browser writes. Also block localhost
    # CSRF/DNS-rebinding attempts rather than treating loopback as user identity.
    origin = request.headers.get("origin")
    if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
        parsed = urlsplit(origin)
        if (parsed.scheme, parsed.netloc) != (request.url.scheme, request.url.netloc):
            raise HTTPException(403, "Cross-origin writes are not allowed")


def effective_role(request: Request, requested: str | None = None) -> str:
    trusted = getattr(request.state, "role", None)
    if trusted and requested and requested != trusted:
        raise HTTPException(403, "Role does not match authenticated identity")
    role = trusted or requested or "data_steward"
    if role not in config.ROLES:
        raise HTTPException(400, "Unknown role")
    return role


def require_steward(request: Request) -> None:
    if effective_role(request) != "data_steward":
        raise HTTPException(403, "Data steward access required")
