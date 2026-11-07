"""Server-side HTTP client and trusted identity for the Streamlit dashboard."""

from __future__ import annotations

import json
import secrets
from urllib.parse import urlsplit

import httpx

from . import config

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
MAX_RESPONSE_BYTES = 10_000_000


class DashboardError(Exception):
    """A safe user-facing error, without connection details or credentials."""


def identity_headers(headers: dict, server_address: str) -> dict[str, str]:
    """Validate the trusted UI boundary before opening any backend connection."""
    supplied = {key.lower(): value for key, value in headers.items()}
    if config.APP_AUTH_MODE == "local":
        # Session IPs can be spoofed behind proxies. Enforce the listener setting
        # instead; the local profile must never be exposed through a tunnel/proxy.
        host = urlsplit("//" + supplied.get("host", "localhost")).hostname
        if server_address not in LOOPBACK_HOSTS or host not in LOOPBACK_HOSTS:
            raise DashboardError("Local demo requires a loopback listener. Configure proxy authentication for hosting.")
        return {}
    if config.APP_AUTH_MODE != "proxy":
        raise DashboardError("APP_AUTH_MODE must be local or proxy")
    credential = supplied.get("x-sinceai-proxy-secret", "")
    if not config.APP_PROXY_SECRET or not secrets.compare_digest(
            config.APP_PROXY_SECRET.encode(), credential.encode()):
        raise DashboardError("An authenticated proxy connection is required")
    role = supplied.get("x-sinceai-role", "")
    actor = supplied.get("x-sinceai-user", "")
    if role not in config.ROLES or not actor.strip() or len(actor) > 200:
        raise DashboardError("Authenticated user identity is missing or invalid")
    # No cookies, arbitrary browser headers or caller-chosen destinations pass on.
    return {"X-SinceAI-Proxy-Secret": config.APP_PROXY_SECRET,
            "X-SinceAI-Role": role, "X-SinceAI-User": actor}


class DashboardClient:
    def __init__(self, headers: dict[str, str]):
        try:
            parsed = urlsplit(config.SINCEAI_API_URL)
            parsed.port
        except ValueError:
            raise DashboardError("SINCEAI_API_URL is invalid") from None
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}
                or not (parsed.scheme == "https" or
                        (parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS))):
            raise DashboardError("Configure SINCEAI_API_URL as a loopback HTTP or HTTPS API origin")
        self.headers = headers

    def request(self, path: str, body: dict | None = None, *, csv: bool = False):
        if not path.startswith("/api/") or path.startswith("//"):
            raise DashboardError("Invalid API path")
        try:
            with httpx.Client(base_url=config.SINCEAI_API_URL, headers=self.headers,
                              timeout=httpx.Timeout(130, connect=5, pool=5),
                              follow_redirects=False, trust_env=False) as client:
                with client.stream("GET" if body is None else "POST", path, json=body) as response:
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise DashboardError("API response exceeded the size limit")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if csv and response.is_success and media_type == "text/csv":
                        return content.decode("utf-8")
                    if media_type != "application/json":
                        raise DashboardError("The API returned an unexpected response")
                    data = json.loads(content)
                    if not response.is_success or (isinstance(data, dict) and data.get("type") == "error"):
                        detail = data.get("message", data.get("detail")) if isinstance(data, dict) else None
                        raise DashboardError(detail if isinstance(detail, str) else "The API rejected the request")
                    if csv or not isinstance(data, (dict, list)):
                        raise DashboardError("The API returned an unexpected response")
                    return data
        except httpx.TimeoutException:
            raise DashboardError("The API timed out. The request may already have been processed; do not automatically resend it.") from None
        except httpx.RequestError:
            raise DashboardError("Cannot reach the API. Check that FastAPI is running.") from None
        except (ValueError, UnicodeError):
            raise DashboardError("The API returned invalid data") from None
