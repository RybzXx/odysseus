"""
services/itinerary/layer_access.py

Whether one itinerary layer may call a model, and which endpoint it may reach.

Odysseus resolves a model role by settings prefix, and an unset prefix reaches
the utility role, then the default role. That chain is right for chat and wrong
here. `default_model` is `gemma4:31b-cloud`, which the local Ollama relays off
the machine. An unconfigured itinerary role would therefore send a customer's
conversation screenshots to a hosted service with nothing said.

So this module resolves a layer by its own prefix and stops there. It reads
`{prefix}_endpoint_id` and `{prefix}_model`, and it reads nothing else. An unset
layer runs nothing and states why (ws-03 D38, D43, invariant 3.2).

The reader layer does not reuse the `vision` role for the same reason.
`_resolve_vl_model` auto-detects across every configured endpoint when
`vision_model` is empty, and its first three candidates are hosted models. A
screenshot must never reach an endpoint the owner did not name for it.

Two switches gate every call. `itinerary_model_proposals_enabled` is the master
and it is off (ws-03 D25, D47). Each layer carries its own switch below it, so a
reader can run with a ranker turned off.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# The four layers, each a settings prefix of its own.
LAYER_READ = "itinerary_read"      # a screenshot becomes text
LAYER_BRIEF = "itinerary_brief"    # layer 1: the request becomes a brief
LAYER_RANK = "itinerary_rank"      # layer 2: one candidate becomes the choice
LAYER_REVIEW = "itinerary_review"  # layer 3: the choice becomes a note
LAYERS = (LAYER_READ, LAYER_BRIEF, LAYER_RANK, LAYER_REVIEW)

# What each layer is for, in the words a settings page would use.
LAYER_PURPOSE = {
    LAYER_READ: "reads the conversation screenshots",
    LAYER_BRIEF: "reasons about what the customer asked for",
    LAYER_RANK: "chooses one itinerary from the candidates",
    LAYER_REVIEW: "states whether the itinerary answers the request",
}

# The master switch. Off means no layer calls anything, whatever a layer switch
# holds (ws-03 D25, spec item 22.3).
MASTER_SWITCH = "itinerary_model_proposals_enabled"


def layer_switch(layer: str) -> str:
    """Post: the settings key that enables one layer."""
    return f"{layer}_enabled"


@dataclass
class LayerAccess:
    """What one layer may do right now, and where it may send."""
    layer: str
    url: str = ""
    model: str = ""
    headers: Optional[dict] = None
    refusal: str = ""      # empty when the layer may run

    @property
    def may_run(self) -> bool:
        """Post: whether the caller may make the call."""
        return not self.refusal and bool(self.url) and bool(self.model)

    @property
    def where(self) -> str:
        """Post: the endpoint host and model, for the run record. No secret."""
        if not self.url:
            return ""
        host = self.url.split("/")[2] if "://" in self.url else self.url
        return f"{host} {self.model}"


def _settings() -> dict:
    from src.settings import load_settings

    try:
        return load_settings()
    except Exception:
        return {}


def master_enabled(settings: Optional[dict] = None) -> bool:
    """
    Post: whether the owner has allowed any itinerary layer to call a model.

    A missing or unreadable settings file reads as off, which is the safe
    answer and therefore carries no risk.
    """
    return bool((settings if settings is not None else _settings())
                .get(MASTER_SWITCH, False))


def resolve_layer(layer: str, owner: Optional[str] = None) -> LayerAccess:
    """
    Where one layer may send, or why it may not send at all.

    Pre:  `layer` is one of LAYERS.
    Post: a LayerAccess. `may_run` is true only when the master switch is on,
          the layer's own switch is on, and the owner named an endpoint for
          this layer. `refusal` states which of the three failed.
    Inv:  the returned url and model come from this layer's own prefix. No
          other prefix is read, and no endpoint is auto-detected (invariant
          3.2).

    Blame: an unknown layer is a caller bug and raises. A layer the owner never
    configured is a configuration state, not a failure, and the caller records
    it as untested rather than raising (D43).
    """
    if layer not in LAYERS:
        raise ValueError(f"not an itinerary layer: {layer!r}")

    settings = _settings()
    if not master_enabled(settings):
        return LayerAccess(layer=layer, refusal=(
            f"the master switch {MASTER_SWITCH} is off, so no itinerary layer "
            f"calls a model"))

    switch = layer_switch(layer)
    if not bool(settings.get(switch, False)):
        return LayerAccess(layer=layer,
                           refusal=f"{switch} is off, so this layer did not run")

    from src.endpoint_resolver import resolve_endpoint_by_id
    from src.settings import get_user_setting

    def stated(key: str) -> str:
        return (get_user_setting(key, owner or "", settings.get(key, ""))
                or "").strip()

    endpoint_id = stated(f"{layer}_endpoint_id")
    model = stated(f"{layer}_model")
    if not endpoint_id or not model:
        return LayerAccess(layer=layer, refusal=(
            f"no endpoint is set for {layer}. Set {layer}_endpoint_id and "
            f"{layer}_model. This layer never reaches another role's model"))

    resolved = resolve_endpoint_by_id(endpoint_id, model, owner=owner,
                                      require_exact_model=True)
    if not resolved:
        return LayerAccess(layer=layer, refusal=(
            f"{layer} names endpoint {endpoint_id} and model {model}, and that "
            f"pair does not resolve. The endpoint may be disabled"))

    url, resolved_model, headers = resolved
    return LayerAccess(layer=layer, url=url, model=resolved_model,
                       headers=headers)


def access_report(owner: Optional[str] = None) -> list:
    """
    Post: one row per layer, saying whether it may run and where it would send.

    Written for a settings page and for a run that wants to state, before it
    starts, which of its four steps will do nothing.
    """
    rows = []
    for layer in LAYERS:
        access = resolve_layer(layer, owner=owner)
        rows.append({
            "layer": layer,
            "purpose": LAYER_PURPOSE[layer],
            "switch": layer_switch(layer),
            "may_run": access.may_run,
            "where": access.where,
            "refusal": access.refusal,
        })
    return rows
