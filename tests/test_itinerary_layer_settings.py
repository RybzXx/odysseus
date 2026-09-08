"""The generic settings route persists every itinerary model-layer field."""

from types import SimpleNamespace

import pytest

import routes.auth_routes as auth_routes
import src.settings as settings_module
from services.itinerary.layer_access import LAYERS, layer_switch


class _AdminAuth:
    def get_username_for_token(self, token):
        return "admin" if token == "admin-session" else None

    def is_admin(self, username):
        return username == "admin"


class _SettingsRequest(SimpleNamespace):
    def __init__(self, body):
        super().__init__(
            cookies={auth_routes.SESSION_COOKIE: "admin-session"},
            _body=body,
        )

    async def json(self):
        return self._body


def _settings_post(router):
    return next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/auth/settings" and "POST" in route.methods
    )


@pytest.mark.asyncio
async def test_the_settings_route_persists_every_itinerary_layer(monkeypatch):
    stored = dict(settings_module.DEFAULT_SETTINGS)
    patch = {"itinerary_model_proposals_enabled": True}
    for layer in LAYERS:
        patch[layer_switch(layer)] = True
        patch[f"{layer}_endpoint_id"] = f"{layer}-endpoint"
        patch[f"{layer}_model"] = f"{layer}-model"

    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.setattr(auth_routes, "_load_settings", lambda: dict(stored))

    def save_settings(updated):
        stored.clear()
        stored.update(updated)

    monkeypatch.setattr(auth_routes, "_save_settings", save_settings)
    post_settings = _settings_post(auth_routes.setup_auth_routes(_AdminAuth()))

    response = await post_settings(_SettingsRequest(patch))

    assert {key: response[key] for key in patch} == patch
    assert {key: stored[key] for key in patch} == patch
