"""
tests/test_layer_access.py

An itinerary layer must reach only the endpoint the owner named for it.

The defect these guard against is silent and expensive. `resolve_endpoint` in
Odysseus reads `{prefix}_endpoint_id`, and an unset prefix reaches the utility
role, then the default role. `default_model` is `gemma4:31b-cloud`, which the
local Ollama relays to a hosted service. A layer that used that chain would
send a customer's conversation screenshots off the machine, and nothing in the
run record or on the page would say so.

So these tests assert a refusal where Odysseus would give a fallback.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import layer_access  # noqa: E402
from services.itinerary.layer_access import (  # noqa: E402
    LAYER_BRIEF,
    LAYER_RANK,
    LAYER_READ,
    LAYER_REVIEW,
    LAYERS,
    MASTER_SWITCH,
    access_report,
    layer_switch,
    master_enabled,
    resolve_layer,
)

CLOUD = "gemma4:31b-cloud"


@pytest.fixture
def settings(monkeypatch):
    """Drive the resolver from a dictionary the test owns."""
    held = {}

    def fake_load():
        return dict(held)

    monkeypatch.setattr(layer_access, "_settings", fake_load)
    return held


def _never_resolves(monkeypatch):
    """Any endpoint id resolves, so a refusal can only come from this module."""
    import src.endpoint_resolver as resolver

    monkeypatch.setattr(resolver, "resolve_endpoint_by_id",
                        lambda *a, **k: ("http://box:11434/v1", "qwen3.8:27b", {}))
    import src.settings as settings_module
    monkeypatch.setattr(settings_module, "get_user_setting",
                        lambda key, owner, default="": default)


# ── the master switch ────────────────────────────────────────────────────────

def test_the_master_switch_is_off_by_default(settings):
    assert master_enabled() is False


def test_no_layer_runs_while_the_master_switch_is_off(settings, monkeypatch):
    _never_resolves(monkeypatch)
    settings.update({f"{layer}_enabled": True for layer in LAYERS})
    settings.update({f"{layer}_endpoint_id": "ep-1" for layer in LAYERS})
    settings.update({f"{layer}_model": "qwen3.8:27b" for layer in LAYERS})

    for layer in LAYERS:
        access = resolve_layer(layer)
        assert access.may_run is False
        assert MASTER_SWITCH in access.refusal


# ── the per-layer switch ─────────────────────────────────────────────────────

def test_a_layer_runs_while_another_layer_is_off(settings, monkeypatch):
    """A reader may run with a ranker off. That is what makes a layer
    measurable on its own (spec item 22.2)."""
    _never_resolves(monkeypatch)
    settings[MASTER_SWITCH] = True
    settings[layer_switch(LAYER_READ)] = True
    settings[f"{LAYER_READ}_endpoint_id"] = "ep-1"
    settings[f"{LAYER_READ}_model"] = "qwen3.8:27b"

    assert resolve_layer(LAYER_READ).may_run is True
    assert resolve_layer(LAYER_RANK).may_run is False
    assert layer_switch(LAYER_RANK) in resolve_layer(LAYER_RANK).refusal


# ── the fallback that must not happen ────────────────────────────────────────

def test_an_unset_layer_refuses_rather_than_reaching_the_default_model(
        settings, monkeypatch):
    """
    The whole point of this module.

    Odysseus would answer this configuration with `default_model`. A layer must
    answer with a refusal instead (invariant 3.2).
    """
    _never_resolves(monkeypatch)
    settings.update({
        MASTER_SWITCH: True,
        layer_switch(LAYER_BRIEF): True,
        # The Odysseus chain: utility, then default. Both are set, and neither
        # may be read.
        "utility_endpoint_id": "ep-cloud", "utility_model": CLOUD,
        "default_endpoint_id": "ep-cloud", "default_model": CLOUD,
    })
    access = resolve_layer(LAYER_BRIEF)

    assert access.may_run is False
    assert access.model == ""
    assert CLOUD not in access.refusal
    assert f"{LAYER_BRIEF}_endpoint_id" in access.refusal


def test_a_layer_with_an_endpoint_but_no_model_refuses(settings, monkeypatch):
    _never_resolves(monkeypatch)
    settings.update({MASTER_SWITCH: True, layer_switch(LAYER_REVIEW): True,
                     f"{LAYER_REVIEW}_endpoint_id": "ep-1"})
    assert resolve_layer(LAYER_REVIEW).may_run is False


def test_an_endpoint_that_does_not_resolve_refuses_and_names_it(
        settings, monkeypatch):
    import src.endpoint_resolver as resolver
    import src.settings as settings_module

    monkeypatch.setattr(resolver, "resolve_endpoint_by_id", lambda *a, **k: None)
    monkeypatch.setattr(settings_module, "get_user_setting",
                        lambda key, owner, default="": default)
    settings.update({MASTER_SWITCH: True, layer_switch(LAYER_RANK): True,
                     f"{LAYER_RANK}_endpoint_id": "ep-gone",
                     f"{LAYER_RANK}_model": "qwen3.8:27b"})
    access = resolve_layer(LAYER_RANK)

    assert access.may_run is False
    assert "ep-gone" in access.refusal


# ── what a caller may read ───────────────────────────────────────────────────

def test_where_names_the_host_and_model_and_no_secret(settings, monkeypatch):
    _never_resolves(monkeypatch)
    settings.update({MASTER_SWITCH: True, layer_switch(LAYER_READ): True,
                     f"{LAYER_READ}_endpoint_id": "ep-1",
                     f"{LAYER_READ}_model": "qwen3.8:27b"})
    assert resolve_layer(LAYER_READ).where == "box:11434 qwen3.8:27b"


def test_an_unknown_layer_is_a_caller_bug(settings):
    with pytest.raises(ValueError):
        resolve_layer("itinerary_invented")


def test_the_report_answers_for_every_layer(settings):
    rows = access_report()
    assert [r["layer"] for r in rows] == list(LAYERS)
    assert all(r["refusal"] for r in rows)
    assert all(r["may_run"] is False for r in rows)


def test_the_reader_does_not_borrow_the_vision_role(settings, monkeypatch):
    """
    `_resolve_vl_model` auto-detects across every configured endpoint when
    `vision_model` is empty, and its first candidates are hosted models. The
    reader must therefore carry a role of its own (spec item 22.6, blocked).
    """
    _never_resolves(monkeypatch)
    settings.update({MASTER_SWITCH: True, layer_switch(LAYER_READ): True,
                     "vision_model": "gpt-4o", "vision_endpoint_id": "ep-cloud"})
    access = resolve_layer(LAYER_READ)

    assert access.may_run is False
    assert "gpt-4o" not in access.refusal
