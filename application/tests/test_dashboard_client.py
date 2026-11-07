"""Identity and transport checks for server-side dashboard calls."""

import httpx
import pytest

from app import config, dashboard_client
from app.dashboard_client import DashboardClient, DashboardError, identity_headers

RealClient = httpx.Client


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setattr(config, "APP_AUTH_MODE", "local")
    monkeypatch.setattr(config, "SINCEAI_API_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(config, "APP_PROXY_SECRET", "trusted-proxy-secret")


def test_local_profile_requires_loopback_listener_and_host():
    assert identity_headers({"host": "localhost:8501"}, "127.0.0.1") == {}
    with pytest.raises(DashboardError):
        identity_headers({"host": "localhost:8501"}, "0.0.0.0")
    with pytest.raises(DashboardError):
        identity_headers({"host": "attacker.example"}, "127.0.0.1")


def test_proxy_identity_forwards_only_verified_headers(monkeypatch):
    monkeypatch.setattr(config, "APP_AUTH_MODE", "proxy")
    headers = {"X-SinceAI-Proxy-Secret": "trusted-proxy-secret", "X-SinceAI-Role": "data_steward",
               "X-SinceAI-User": "Steward", "Cookie": "do-not-forward", "Authorization": "ignore"}
    assert identity_headers(headers, "0.0.0.0") == {key: value for key, value in headers.items() if key.startswith("X-SinceAI")}
    with pytest.raises(DashboardError):
        identity_headers({**headers, "X-SinceAI-Proxy-Secret": "wrong"}, "0.0.0.0")
    with pytest.raises(DashboardError):
        identity_headers({**headers, "X-SinceAI-Role": "root"}, "0.0.0.0")


@pytest.mark.parametrize("url", ["https://user:pass@example.com", "http://remote.example", "https://[bad",
                                 "https://example.com/path", "https://example.com?url=bad"])
def test_unsafe_api_origins_rejected(monkeypatch, url):
    monkeypatch.setattr(config, "SINCEAI_API_URL", url)
    with pytest.raises(DashboardError):
        DashboardClient({})


def test_request_credentials_timeout_csv_and_no_redirects(monkeypatch):
    calls = []
    def receive(request):
        calls.append(request)
        if request.url.path.endswith("raw.csv"):
            return httpx.Response(200, text="value\n95\n", headers={"content-type": "text/csv"})
        return httpx.Response(200, json={"ok": True})
    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert kwargs["timeout"].read == 130
        return RealClient(transport=httpx.MockTransport(receive), **kwargs)
    monkeypatch.setattr(dashboard_client.httpx, "Client", factory)
    client = DashboardClient({"X-SinceAI-Proxy-Secret": "trusted-proxy-secret"})
    assert client.request("/api/ask", {"question": "OTIF"}) == {"ok": True}
    assert client.request("/api/results/test/raw.csv", csv=True) == "value\n95\n"
    assert len(calls) == 2 and calls[0].headers["X-SinceAI-Proxy-Secret"] == "trusted-proxy-secret"


def test_timeout_is_not_retried_and_does_not_expose_transport_details(monkeypatch):
    calls = []
    def receive(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret transport information", request=request)
    monkeypatch.setattr(dashboard_client.httpx, "Client", lambda **kwargs: RealClient(
        transport=httpx.MockTransport(receive), **kwargs))
    with pytest.raises(DashboardError, match="may already have been processed") as error:
        DashboardClient({}).request("/api/ask", {"question": "OTIF"})
    assert "secret transport" not in str(error.value) and len(calls) == 1
