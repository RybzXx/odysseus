"""Regressions for incorrect itinerary results. No network or document writes."""
from datetime import date
from types import SimpleNamespace
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from services.itinerary.models import NormalizedRequest, RouteDay, RouteRecord
from services.itinerary.regions import (
    REGION_CENTRAL, REGION_SOUTH, REGION_KURDISTAN, REGION_WEST_NINEVEH,
    DEFAULT_ROUTE_REGIONS)
from services.itinerary.normalizer import normalize_from_dict
from services.itinerary.sequence_check import check_sequence
from services.itinerary.matcher import activity_regions
from services.itinerary.binder import bind_route_to_templates
from services.itinerary.candidates import build_candidates


def row(city="Baghdad", overnight="Baghdad", region=REGION_CENTRAL, **kwargs):
    return SimpleNamespace(city=city, overnight_city=overnight, region=region,
                           full_text="", title="", active=True, **kwargs)


def request(days=1, regions=None):
    return NormalizedRequest(key="test", source="curated", customer_name="Test",
        day_count=days, requested_regions=regions or [REGION_CENTRAL], start_date=date(2026, 10, 6))


def route(name, cities, regions=None):
    return RouteRecord(id=name, source_file=name, day_count=len(cities), tour_type="individual",
        city_sequence=cities, themes=[], days=[RouteDay(i+1, c, "") for i,c in enumerate(cities)],
        region_set=set(regions or [REGION_CENTRAL]))


def test_thursday_and_offer_flights_are_not_southern_visits():
    days = [RouteDay(1, "Baghdad", "Thursday: a tour of Baghdad.\nIncludes:\nFlights to Erbil or Basra. Lunch in marshes.")]
    assert activity_regions(days) == {REGION_CENTRAL}
    assert REGION_SOUTH in activity_regions([RouteDay(1, "Baghdad", "Visit Ur.")])


def test_missing_regions_use_the_operator_default():
    req = normalize_from_dict("test", {"tripDays": "10"}, source="curated")
    assert req.requested_regions == list(DEFAULT_ROUTE_REGIONS)
    assert req.was_defaulted("requested_regions")
    check = check_sequence(["BG"], {"BG": row()}, normalized_request=req)
    assert {f.kind for f in check.faults} >= {"default_route", "region_coverage", "day_count"}


def test_explicit_regions_override_the_operator_default():
    req = normalize_from_dict("test", {"tripDays": "7", "regions": [REGION_CENTRAL, REGION_SOUTH]}, source="curated")
    assert req.requested_regions == [REGION_CENTRAL, REGION_SOUTH]
    assert not req.was_defaulted("requested_regions")


def test_baghdad_days_do_not_satisfy_a_southern_request():
    req = request(regions=[REGION_CENTRAL, REGION_SOUTH])
    check = check_sequence(["BG"], {"BG": row()}, start_date=req.start_date, normalized_request=req)
    assert any(f.kind == "region_coverage" and REGION_SOUTH in f.statement for f in check.faults)
    found = build_candidates(req, {"BG": row()}, routes=[route("wrong", ["Baghdad"], req.requested_regions)])
    assert found.candidates[0].region_coverage == 0.5


def test_safa_cannot_replace_northbound_transit():
    req = request(regions=[REGION_CENTRAL, REGION_KURDISTAN])
    check = check_sequence(["SAFA"], {"SAFA": row()}, start_date=req.start_date, normalized_request=req)
    assert any(f.kind == "northbound_excursion" for f in check.faults)
    west = request(regions=[REGION_WEST_NINEVEH])
    check = check_sequence(["SAFA"], {"SAFA": row()}, start_date=west.start_date, normalized_request=west)
    assert not any(f.kind == "northbound_excursion" for f in check.faults)


def test_a_missing_connection_stops_binding_at_the_gap():
    templates = {"BG": row(), "URUKNA": row("Karbala / Nasiriyah", "Nasiriyah", REGION_SOUTH)}
    codes, gaps = bind_route_to_templates(route("gap", ["Baghdad", "Nasiriyah"]), templates)
    assert codes == ["BG"]
    assert "Day 2" in gaps[0] and "Binding stopped" in gaps[0]


def test_valid_lower_scoring_route_beyond_five_candidates_wins():
    templates = {"BG": row()}
    # Higher scores claim complete region evidence but have no bindable template.
    invalid = [route(f"bad{i}", ["Atlantis"]) for i in range(7)]
    valid = route("valid", ["Baghdad"], [REGION_CENTRAL, REGION_SOUTH])
    corpus = invalid + [valid]
    first = build_candidates(request(), templates, routes=corpus, ceiling=1)
    second = build_candidates(request(), templates, routes=list(reversed(corpus)), ceiling=1)
    assert first.tied_routes == 8
    assert first.candidates[0].route_id == second.candidates[0].route_id == "valid"
    assert first.candidates[0].check.is_clean


def test_unknown_date_is_unresolved_not_clean():
    check = check_sequence(["BG"], {"BG": row()}, normalized_request=request())
    assert check.found_no_fault and not check.is_clean
    assert check.untested


def test_same_code_cannot_fill_missing_days_even_without_sites():
    check = check_sequence(["BG", "BG"], {"BG": row()}, start_date=date(2026, 10, 6))
    assert any(f.kind == "day_repeat" for f in check.faults)


def test_changed_template_invalidates_its_old_shape():
    from services.itinerary.day_shape import all_shapes
    assert all_shapes({"X": row()})["X"].start_city == "Baghdad"
    assert all_shapes({"X": row("Mosul", "Mosul")})["X"].start_city == "Mosul"


@pytest.mark.parametrize("codes", [["BG"], ["UNKNOWN"], ["BG", "BG"]])
def test_document_boundary_rejects_incomplete_codes_before_google(monkeypatch, codes):
    from services.itinerary import generator
    monkeypatch.setattr(generator, "load_templates", lambda: {"BG": row()})
    def forbidden(*args, **kwargs):
        pytest.fail("Document generation reached Google")
    monkeypatch.setattr(generator, "_PIPELINE", {"generate_document": forbidden})
    result = generator.execute_generation(request(days=2), day_codes=codes)
    assert result.status == "error"
    assert not result.preview.can_generate_document


def test_reviewed_comment_migration_preserves_history_and_is_idempotent(tmp_path, monkeypatch):
    from services.itinerary import drafts, corrections
    from services.offers import rule_book
    monkeypatch.setattr(drafts, "ITINERARY_DRAFT_DIR", str(tmp_path / "drafts"))
    monkeypatch.setattr(rule_book, "AI_RULES_DIR", str(tmp_path / "rules"))
    draft = drafts.open_draft({"tripDays": "7"})
    draft = drafts.add_sequence(draft.draft_id, drafts.ProposedSequence(source="rules", day_codes=["BG"]))
    draft = drafts.add_comment(draft.draft_id, "Keep the south")
    comment = draft.comments[0]
    monkeypatch.setattr(corrections, "CORRECTIONS", {comment["comment_id"]: {
        "sha256": hashlib.sha256(comment["text"].encode()).hexdigest(),
        "statement": "Require the requested regions.", "enforced_by": "sequence_check.region_coverage"}})
    rule_book.save_judged_rule(rule_book.JudgedRule(rule_id="judged--safa-with-samo", statement="Original exception"))
    first = corrections.apply_reviewed_corrections()
    assert len(first["processed"]) == 1 and len(first["retired"]) == 1
    stored = drafts.load(draft.draft_id)
    assert stored.sequences == draft.sequences and stored.run_ids == draft.run_ids
    assert stored.comments[0]["text"] == comment["text"]
    assert stored.comments[0]["rule_state"] == "drafted"
    retired = rule_book.load_judged_rule("judged--safa-with-samo")
    assert retired.statement == "Original exception" and retired.status == "retired"
    second = corrections.apply_reviewed_corrections()
    assert second["processed"] == second["retired"] == []


def test_southern_route_must_visit_marshes_and_return_to_baghdad():
    req = request(days=3, regions=[REGION_CENTRAL, REGION_SOUTH])
    templates = {"BG": row(), "NA": row("Baghdad / Nasiriyah", "Nasiriyah", REGION_SOUTH),
                 "NA2BA": row("Nasiriyah / Basra", "Basra", REGION_SOUTH, included_sites=["NA_MARSHES"]),
                 "NA2BG": row("Nasiriyah / Baghdad", "Baghdad", REGION_SOUTH, included_sites=["NA_MARSHES"])}
    wrong = check_sequence(["BG", "NA", "NA2BA"], templates, start_date=req.start_date, normalized_request=req)
    right = check_sequence(["BG", "NA", "NA2BG"], templates, start_date=req.start_date, normalized_request=req)
    assert any(f.kind == "southern_return" for f in wrong.faults)
    assert not any(f.kind == "southern_return" for f in right.faults)


def test_recalculation_appends_rules_and_direct_api_refuses_invalid_generation(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.itinerary import drafts, generator
    from routes.curated import itinerary_desk_routes as desk
    from src import llm_core
    monkeypatch.setattr(drafts, "ITINERARY_DRAFT_DIR", str(tmp_path / "drafts"))
    monkeypatch.setattr(desk, "require_admin", lambda req: None)
    monkeypatch.setattr(desk, "active_day_templates", lambda: {"BG": row()})
    monkeypatch.setattr(generator, "load_templates", lambda: {"BG": row()})
    def forbidden(*args, **kwargs):
        pytest.fail("The repair reached a model or document service")
    monkeypatch.setattr(llm_core, "llm_call", forbidden)
    monkeypatch.setattr(llm_core, "llm_call_async", forbidden)
    monkeypatch.setattr(generator, "_PIPELINE", {"generate_document": forbidden})
    draft = drafts.open_draft({"tripDays": "4", "regions": [REGION_CENTRAL]}, request_id="curated:sample")
    draft = drafts.add_sequence(draft.draft_id, drafts.ProposedSequence(source="model", day_codes=["BG"]))
    draft = drafts.add_comment(draft.draft_id, "Keep this comment")
    app = FastAPI()
    app.include_router(desk.setup_itinerary_desk_routes())
    with TestClient(app) as client:
        response = client.post(f"/api/itinerary/drafts/{draft.draft_id}/propose-again")
        assert response.status_code == 200
        body = response.json()
        assert body["sequences"][-1]["source"] == "rules"
        assert body["sequences"][-1]["check"]["is_clean"] is False
        stored = drafts.load(draft.draft_id)
        assert stored.sequences[:-1] == draft.sequences
        assert stored.comments == draft.comments and stored.run_ids == draft.run_ids
        rejected = client.post(f"/api/itinerary/drafts/{draft.draft_id}/generate", json={"source": "model"})
        assert rejected.status_code == 200
        assert rejected.json()["ok"] is False
        assert "Requested 4 days" in rejected.json()["errors"][0]
    assert drafts.load(draft.draft_id).doc_url == ""


def test_missing_template_end_is_unresolved():
    check = check_sequence(["X"], {"X": row("", "")}, start_date=date(2026, 10, 6), normalized_request=request())
    assert not check.is_clean
    assert any("end city" in note for note in check.untested)


def test_unknown_and_inactive_codes_are_not_clean():
    inactive = row()
    inactive.active = False
    check = check_sequence(["X", "OFF"], {"OFF": inactive}, start_date=date(2026, 10, 6))
    assert not check.is_clean and not check.found_no_fault
    assert check.unknown_codes == ["X", "OFF"]


def test_valid_exact_sequence_can_reach_document_service(monkeypatch):
    from services.itinerary import generator
    from unittest.mock import Mock
    create = Mock(return_value={"ok": True, "doc_url": "test://document", "doc_id": "test"})
    monkeypatch.setattr(generator, "load_templates", lambda: {"BG": row()})
    monkeypatch.setattr(generator, "build_tour_request", lambda req, codes: codes)
    monkeypatch.setattr(generator, "_PIPELINE", {
        "check_request": lambda req: {"ok": True}, "load_pricing": lambda: {},
        "build_itinerary": lambda req, templates: req,
        "calculate_quote": lambda req, days, pricing: {"total_usd": 1},
        "generate_document": create})
    result = generator.execute_generation(request(), day_codes=["BG"])
    assert result.status == "success"
    create.assert_called_once_with(["BG"])


def test_desk_reports_pricing_failure_on_an_otherwise_valid_route(tmp_path, monkeypatch):
    from services.itinerary import drafts, generator
    from routes.curated import itinerary_desk_routes as desk
    from services.itinerary.models import ItineraryPreviewResult
    monkeypatch.setattr(drafts, "ITINERARY_DRAFT_DIR", str(tmp_path / "drafts"))
    draft = drafts.open_draft({"tripDays": "1", "regions": [REGION_CENTRAL],
        "travelDateMode": "exact", "exactDate": "2026-10-06"}, request_id="curated:price")
    draft = drafts.add_sequence(draft.draft_id, drafts.ProposedSequence(source="rules", day_codes=["BG"]))
    monkeypatch.setattr(generator, "preview_itinerary", lambda *a, **k: ItineraryPreviewResult(
        key="test", matched_route_id="", matched_route_name="", confidence_score=1,
        confidence_level="high", requested_day_count=1, delivered_day_count=1,
        bound_day_codes=["BG"], coverage_gaps=[], calendar_warnings=[],
        validation_errors=["Vehicle VAN is not in the catalogue"]))
    result = desk._draft_to_dict(draft, templates={"BG": row()})["sequences"][-1]
    assert result["check"]["is_clean"]
    assert not result["generation"]["ready"]
    assert "VAN" in result["generation"]["errors"][0]
