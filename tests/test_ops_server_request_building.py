"""Boundary tests for how ops_server builds its requests.

These skip where the mcp package is absent (a Windows dev checkout) and run in
the proot guest, which has it.

The interesting surface here is small but load-bearing: _query splices model-
supplied values straight into a URL query string, and the MCP layer does not
enforce the inputSchema — a model may send any type for any field.
"""

import pytest

pytest.importorskip("mcp", reason="mcp is only installed in the guest")

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from mcp_servers.ops_server import _attention_params, _config  # noqa: E402


def built_url(params: dict) -> str:
    """The URL httpx actually sends for these parameters."""
    return str(httpx.Request('GET', 'https://ops.test/api/agent/ops/attention',
                             params=params).url)


# --------------------------------------------------- _attention_params ----

def test_no_arguments_asks_only_for_the_detail_mode():
    assert _attention_params("structural", {}) == {"detail": "structural"}


@pytest.mark.parametrize("hostile", [
    "New&limit=999",
    "New&detail=full",
])
def test_a_status_cannot_inject_another_parameter(hostile):
    """A status containing & must not become a second query parameter.

    `detail=full` is the one that matters: the structural lane asking for the
    full projection would arm its own gate and lose the ability to propose,
    which is the exact failure this module exists to prevent.
    """
    url = built_url(_attention_params("structural", {"status": hostile}))
    assert url.count("&") == 1, f"status injected extra parameters: {url}"
    assert "detail=full" not in url


def test_a_status_cannot_truncate_the_url():
    """A # starts a fragment, so everything after it never reaches the server."""
    url = built_url(_attention_params("structural", {"status": "New#x", "limit": 5}))
    assert "#" not in url, f"status introduced a fragment: {url}"
    assert "limit=5" in url, f"the fragment swallowed a later parameter: {url}"


@pytest.mark.parametrize("value,encoded", [
    # httpx form-encodes a space as '+', which URLSearchParams on the other end
    # decodes back to a space. Both spellings are correct; this pins the actual one.
    ("In Progress", "In+Progress"),
    ("100%", "100%25"),
    ("a&b", "a%26b"),
    ("a#b", "a%23b"),
    ("a=b", "a%3Db"),
])
def test_reserved_characters_are_encoded(value, encoded):
    assert encoded in built_url(_attention_params("structural", {"status": value}))


def test_a_boolean_limit_is_ignored():
    """bool is a subclass of int, so isinstance(True, int) passes.

    httpx renders True as "true", which the web app rejects with 400 — and a 400
    raises OpsApiError, arming the gate and ending a run that had done nothing
    wrong. `type(limit) is int` is what excludes it.
    """
    assert "limit" not in _attention_params("structural", {"limit": True})
    assert "limit" not in _attention_params("structural", {"limit": False})


@pytest.mark.parametrize("limit,expected_present", [
    (0, False),
    (-1, False),
    (1, True),
    (10_000_000, True),
])
def test_limit_boundaries(limit, expected_present):
    assert ("limit" in _attention_params("structural", {"limit": limit})) is expected_present


def test_a_non_integer_limit_is_ignored():
    assert "limit" not in _attention_params("structural", {"limit": "20"})


def test_a_blank_status_is_omitted_rather_than_sent_empty():
    assert "status" not in _attention_params("structural", {"status": "   "})


# ------------------------------------------------------------ _config ----

@pytest.mark.parametrize("env,expected", [
    ({}, None),
    ({"OPS_API_BASE_URL": "https://x.test"}, None),
    ({"OPS_AGENT_TOKEN": "t"}, None),
    ({"OPS_API_BASE_URL": "  ", "OPS_AGENT_TOKEN": "t"}, None),
    ({"OPS_API_BASE_URL": "https://x.test", "OPS_AGENT_TOKEN": "   "}, None),
])
def test_config_is_none_unless_both_values_are_present(monkeypatch, env, expected):
    monkeypatch.delenv("OPS_API_BASE_URL", raising=False)
    monkeypatch.delenv("OPS_AGENT_TOKEN", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert _config() is expected


def test_config_strips_one_trailing_slash_only(monkeypatch):
    """Paths are joined as f"{base_url}{path}" with path starting in '/'.

    A base URL of "https://x.test//" leaves a double slash in every request.
    """
    monkeypatch.setenv("OPS_API_BASE_URL", "https://x.test//")
    monkeypatch.setenv("OPS_AGENT_TOKEN", "t")
    base_url, _ = _config()
    assert not base_url.endswith("/"), f"base URL keeps a trailing slash: {base_url}"
