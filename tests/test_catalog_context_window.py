"""Catalog-reported context windows, and how they meet the local served ceiling.

A gateway such as 9router reports each model's window as
``capabilities.contextWindow``. That value must be read, and on a local
endpoint it must replace the ODYSSEUS_LOCAL_SERVED_CONTEXT ceiling, which
stands in only for servers (Ollama) whose catalog reports no window.
"""

import httpx
import pytest

from src import endpoint_resolver, model_context

URL = "http://localhost:20128/v1"


# -- reading the window from one catalog entry ---------------------------------
def test_reads_nested_capabilities_context_window():
    entry = {"id": "cc/claude-opus-5", "capabilities": {"contextWindow": 1000000}}
    assert model_context._model_ctx_from_entry(entry) == 1000000


def test_reads_top_level_camelcase_window():
    assert model_context._model_ctx_from_entry({"id": "m", "contextWindow": 262144}) == 262144


def test_snake_case_field_still_wins_over_capabilities():
    entry = {"id": "m", "context_length": 32768, "capabilities": {"contextWindow": 999999}}
    assert model_context._model_ctx_from_entry(entry) == 32768


def test_boolean_is_not_a_window():
    assert model_context._model_ctx_from_entry({"id": "m", "capabilities": {"contextWindow": True}}) is None


def test_no_window_reported_returns_none():
    assert model_context._model_ctx_from_entry({"id": "m", "capabilities": {"tools": True}}) is None


# -- a local endpoint under the served ceiling ----------------------------------
@pytest.fixture
def local_server(monkeypatch):
    """A loopback endpoint with no /slots, no /api/show, and a swappable catalog."""
    monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url)
    monkeypatch.setattr(model_context, "_configured_endpoint_kind", lambda url: "auto")
    monkeypatch.setenv(model_context.LOCAL_SERVED_CONTEXT_ENV, "8192")
    model_context._context_cache.clear()
    model_context._catalog_reported_windows.clear()
    state = {"catalog": []}

    def fake_get(url, timeout=None, **kwargs):
        request = httpx.Request("GET", url)
        if url.endswith("/models"):
            return httpx.Response(200, json={"data": state["catalog"]}, request=request)
        return httpx.Response(404, request=request)

    def fake_post(url, json=None, timeout=None, **kwargs):
        return httpx.Response(404, request=httpx.Request("POST", url))

    monkeypatch.setattr(model_context.httpx, "get", fake_get)
    monkeypatch.setattr(model_context.httpx, "post", fake_post)
    return state


def test_catalog_reported_window_replaces_the_env_ceiling(local_server):
    local_server["catalog"] = [
        {"id": "cc/claude-opus-5", "capabilities": {"contextWindow": 1000000}},
    ]
    assert model_context.get_context_length(URL, "cc/claude-opus-5") == 1000000


def test_model_without_a_reported_window_keeps_the_env_ceiling(local_server):
    # Ollama's catalog lists models with no window: the ceiling must still apply.
    local_server["catalog"] = [{"id": "qwen3.6:35b-a3b"}]
    assert model_context.get_context_length(URL, "qwen3.6:35b-a3b") <= 8192


def test_a_stale_report_does_not_outlive_its_query(local_server):
    local_server["catalog"] = [
        {"id": "cc/claude-opus-5", "capabilities": {"contextWindow": 1000000}},
    ]
    assert model_context.get_context_length(URL, "cc/claude-opus-5") == 1000000
    # The server stops reporting the window: the next query falls back to the ceiling.
    local_server["catalog"] = [{"id": "cc/claude-opus-5"}]
    assert model_context.get_context_length(URL, "cc/claude-opus-5") <= 8192


def test_a_stubbed_query_keeps_the_old_ceiling(monkeypatch):
    # Callers that stub _query_context_length never read a catalog, so nothing
    # is recorded and the env ceiling applies exactly as before.
    monkeypatch.setattr(model_context, "_configured_endpoint_kind", lambda url: "auto")
    monkeypatch.setenv(model_context.LOCAL_SERVED_CONTEXT_ENV, "8192")
    model_context._catalog_reported_windows.clear()
    monkeypatch.setattr(model_context, "_query_context_length", lambda url, model: (131072, True))
    assert model_context.get_context_length(URL, "anything") == 8192
