"""Group estimates keep activities, distribute FOC costs, and preserve history."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date
import math

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.itinerary import drafts
from services.itinerary.group_quote import GroupQuoteOptions, quote_draft
from services.itinerary.pipeline.app_core import build_default_request
from services.itinerary.pipeline.builder import build_itinerary
from services.itinerary.pipeline.models import DayTemplate


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "ITINERARY_DRAFT_DIR", str(tmp_path))
    draft = drafts.open_draft({"name": "Example", "tripDays": 10}, request_id="curated:example")
    draft.group_quote_basis = {"label": "Operations route", "day_codes": [f"D{i}" for i in range(10)],
                               "start_date": "2027-03-26", "arrival_rest_only": True, "hotel_tier": "3star"}
    templates = {f"D{i}": DayTemplate(f"D{i}", f"Tour {i}", "Erbil", "kurdistan", "Erbil",
                                     "Full tour activities", ["ENTRY"], ["hotel_night", "guide_day", "transport_day"],
                                     True, False, "") for i in range(10)}
    pricing = {"settings": {"guide_daily_rate_usd": 80, "airport_transfer_per_person_usd": 100},
               "hotel_tiers": {"Erbil": {"3star": {"single": 30, "double": 40, "team_fee": 50}}},
               "_tickets_by_code": {"ENTRY": {"site_name": "Entry", "price_per_person": 10, "price_flat": 0, "active": True}},
               "_transport_by_code": {"TOYOTA_COASTER": {"daily_rate_usd": 200}, "VIP_BUS": {"daily_rate_usd": 450}}}
    return draft, templates, pricing


def test_duration_option_removes_only_one_hotel_night(scenario):
    draft, templates, pricing = scenario
    before = deepcopy(templates)
    kept = quote_draft(draft, GroupQuoteOptions(omit_final_night=False), templates=templates, pricing=pricing)
    omitted = quote_draft(draft, GroupQuoteOptions(), templates=templates, pricing=pricing)
    assert (kept["num_days"], kept["num_nights"]) == (11, 10)
    assert (omitted["num_days"], omitted["num_nights"]) == (10, 9)
    assert omitted["transport_days"] == kept["transport_days"] == 9
    assert omitted["guide_days"] == kept["guide_days"] == 9
    assert "Full tour activities" in omitted["days"][-1]["text"]
    assert omitted["days"][-1]["overnight_city"] == ""
    assert kept["days"][-1]["code"] == "DEPARTURE_TRANSFER"
    assert kept["days"][-1]["date"] == "2027-04-05"
    assert any("flight" in warning for warning in omitted["warnings"])
    assert templates == before


def test_prices_cover_every_headcount_and_share_all_foc_costs(scenario):
    draft, templates, pricing = scenario
    result = quote_draft(draft, GroupQuoteOptions(single_supplement_override=400), templates=templates, pricing=pricing)
    assert result["multiplier"] == 1.32
    assert result["single_supplement"] == 400
    for row in result["rows"]:
        for vehicle, rate in (("TOYOTA_COASTER", 200), ("VIP_BUS", 450)):
            expected = []
            for paying in range(row["paying_min"], row["paying_max"] + 1):
                hotel = 9 * (30 + math.ceil(paying / 2) * 40 + 50)
                other = 9 * 80 + 9 * rate + (paying + 1) * (100 + 9 * 10)
                expected.append(math.ceil((hotel + other) * 1.32 / paying / 25) * 25)
            assert row[vehicle] == max(expected)
        assert row["VIP_BUS"] > row["TOYOTA_COASTER"]
    assert [(r["paying_min"], r["paying_max"]) for r in result["rows"]] == [(8, 9), (10, 11), (12, 13), (14, 14)]


def test_unknown_rates_block_instead_of_producing_free_services(scenario):
    draft, templates, pricing = scenario
    del pricing["_transport_by_code"]["VIP_BUS"]
    with pytest.raises(ValueError, match="VIP_BUS"):
        quote_draft(draft, GroupQuoteOptions(), templates=templates, pricing=pricing)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_supplement_is_rejected(value):
    with pytest.raises(ValidationError):
        GroupQuoteOptions(single_supplement_override=value)


def test_existing_departure_does_not_get_an_extra_departure(scenario):
    draft, templates, pricing = scenario
    templates["D9"].overnight_city = ""
    templates["D9"].pricing_tags.remove("hotel_night")
    result = quote_draft(draft, GroupQuoteOptions(omit_final_night=False), templates=templates, pricing=pricing)
    assert (result["num_days"], result["num_nights"]) == (10, 9)
    with pytest.raises(ValueError, match="no included hotel night"):
        quote_draft(draft, GroupQuoteOptions(), templates=templates, pricing=pricing)


def test_generic_draft_uses_latest_proposal_without_operations_basis(scenario):
    draft, templates, pricing = scenario
    draft.group_quote_basis = {}
    draft.sequences = [drafts.ProposedSequence(source="rules", day_codes=list(templates))]
    result = quote_draft(draft, GroupQuoteOptions(), templates=templates, pricing=pricing)
    assert not result["basis_is_operations_variant"]
    assert result["guide_days"] == 10


def test_saved_options_preserve_request_history_and_comments(scenario, monkeypatch):
    import routes.curated.itinerary_desk_routes as routes
    draft, templates, pricing = scenario
    drafts.save(draft)
    drafts.add_comment(draft.draft_id, "Keep the tour visits.")
    before = asdict(drafts.load(draft.draft_id))
    monkeypatch.setattr(routes, "require_admin", lambda request: None)
    monkeypatch.setattr(routes, "quote_draft", lambda d, o: quote_draft(d, o, templates=templates, pricing=pricing))
    app = FastAPI()
    app.include_router(routes.setup_itinerary_desk_routes())
    client = TestClient(app)
    url = f"/api/itinerary/drafts/{draft.draft_id}/group-quote"
    response = client.post(url, json={"omit_final_night": False, "single_supplement_override": 400})
    assert response.status_code == 200, response.text
    assert client.get(url).json()["num_days"] == 11
    after = asdict(drafts.load(draft.draft_id))
    for key in before:
        if key != "group_quote_options":
            assert after[key] == before[key]
    assert client.post(url, json={"margin_markup_percent": -1}).status_code == 422
    assert asdict(drafts.load(draft.draft_id)) == after
    assert client.get("/api/itinerary/drafts/dr-000000000000/group-quote").status_code == 404
    def deny(request):
        raise HTTPException(401, "Sign in required")
    monkeypatch.setattr(routes, "require_admin", deny)
    assert client.get(url).status_code == 401
    assert client.post(url, json={}).status_code == 401


def test_default_pricing_applies_both_markups():
    request = build_default_request(1310)
    assert request.apply_office_markup and request.office_markup_percent == 10
    assert request.apply_margin_markup and request.margin_markup_percent == 20
