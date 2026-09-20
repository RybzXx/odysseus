"""Sharing preserves operations overrides without running a model."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from services.itinerary import workspace_sync
from services.itinerary.group_quote import GroupQuoteOptions
from services.itinerary.pipeline.models import DayTemplate


def test_request_preserves_rest_arrival_and_repeated_codes(monkeypatch):
    day = DayTemplate("BG1", "Baghdad", "Baghdad", "federal", "Baghdad", "Visit museum", ["MUSEUM"], ["hotel_night", "guide_day", "transport_day"], True, False, "")
    monkeypatch.setattr(workspace_sync, "load_all_templates", lambda: {"BG1": day})
    draft = SimpleNamespace(draft_id="dr-test", request_id="queue:sample", doc_url="", request_row={"name": "Test group", "tripDays": 2}, sequences=[], group_quote_basis={"day_codes": ["BG1", "BG1"], "arrival_rest_only": True})
    before = deepcopy(draft.__dict__)
    payload = workspace_sync.workspace_request(draft, GroupQuoteOptions(single_supplement_override=400))
    assert payload["request"]["group_count_basis"] == "paying"
    assert payload["request"]["group_sizes"][0] == (8, 9)
    assert payload["request"]["sgl_supplement_override"] == 400
    assert payload["day_templates"][0]["included_sites"] == []
    assert payload["day_templates"][1]["included_sites"] == ["MUSEUM"]
    assert payload["day_templates"][0]["code"] != payload["day_templates"][1]["code"]
    assert draft.__dict__ == before
    assert day.included_sites == ["MUSEUM"]
