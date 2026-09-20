"""Both authentication layers stay on the configured operations host."""
import asyncio

import httpx
import pytest

from src import ops_hub


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("bypass", ["", "test-vercel-secret"])
def test_agent_requests_keep_bearer_and_optional_vercel_header(monkeypatch, method, bypass):
    monkeypatch.setenv("OPS_API_BASE_URL", "https://dev.bilweekend.iq")
    monkeypatch.setenv("OPS_AGENT_TOKEN", "test-agent-secret")
    monkeypatch.setenv("VERCEL_AUTOMATION_BYPASS_SECRET", bypass)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(ops_hub.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    result = asyncio.run(ops_hub._get("/api/agent/ops/attention") if method == "GET"
                         else ops_hub._post("/api/agent/ops/itineraries", {}))
    assert result["ok"]
    assert len(requests) == 1
    assert requests[0].url.host == "dev.bilweekend.iq"
    assert requests[0].headers["Authorization"] == "Bearer test-agent-secret"
    assert requests[0].headers.get("x-vercel-protection-bypass", "") == bypass


def test_redirect_does_not_forward_secrets(monkeypatch):
    monkeypatch.setenv("OPS_API_BASE_URL", "https://dev.bilweekend.iq")
    monkeypatch.setenv("OPS_AGENT_TOKEN", "test-agent-secret")
    monkeypatch.setenv("VERCEL_AUTOMATION_BYPASS_SECRET", "test-vercel-secret")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://other.example/"})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(ops_hub.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    result = asyncio.run(ops_hub._post("/api/agent/ops/itineraries", {}))
    assert not result["ok"]
    assert result["status_code"] == 307
    assert len(requests) == 1
