"""Contracts for shared day facts, corpus provenance, and generation gates."""
from dataclasses import replace
from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.itinerary.models import NormalizedRequest
from services.itinerary.resolved_plan import resolve_plan, stale_plan_errors
from services.itinerary.sequence_check import check_sequence
from services.itinerary.regions import REGION_CENTRAL


def request(**changes):
    return replace(NormalizedRequest(key="test", source="curated", customer_name="Test",
        day_count=1, start_date=date(2026, 10, 6), requested_regions=[REGION_CENTRAL]), **changes)


def templates():
    return {"BG": SimpleNamespace(code="BG", title="Baghdad city tour", city="Baghdad",
        overnight_city="Baghdad", region=REGION_CENTRAL, full_text="Visit Baghdad.",
        included_sites=[], pricing_tags=["hotel_night"], active=True, needs_review=False)}


def test_plan_freezes_rows_and_separates_accommodation():
    rows = templates()
    rows["BG"].pricing_tags = []
    plan = resolve_plan(["BG"], rows, request())
    assert plan.days[0]["overnight_status"] == "present"
    assert plan.days[0]["accommodation"] == "excluded"
    rows["BG"].overnight_city = "Mosul"
    assert plan.templates["BG"].overnight_city == "Baghdad"
    assert plan.days[0]["evidence"]["template_version"]


@pytest.mark.parametrize("change", ["request", "template", "codes", "integrity", "legacy", "pricing"])
def test_obsolete_or_modified_plans_require_recalculation(change, monkeypatch):
    from services.itinerary import resolved_plan
    rows, req = templates(), request()
    stored = resolve_plan(["BG"], rows, req).to_dict()
    codes = ["BG"]
    assert not stale_plan_errors(stored, req, rows, codes)
    if change == "request":
        req = replace(req, pax=5)
    elif change == "template":
        rows["BG"].full_text = "Changed activity"
    elif change == "codes":
        codes = []
    elif change == "integrity":
        stored["days"][0]["overnight_city"] = "Mosul"
    elif change == "legacy":
        stored = {}
    else:
        monkeypatch.setattr(resolved_plan, "pricing_version", lambda: "changed")
    assert stale_plan_errors(stored, req, rows, codes)


def test_required_city_is_not_satisfied_by_its_region():
    req = request(required_cities=["Najaf"])
    checked = check_sequence(["BG"], templates(), start_date=req.start_date, normalized_request=req)
    assert any(f.kind == "required_city" for f in checked.faults)


def test_active_catalogue_plan_matches_generator_catalogue():
    rows, req = templates(), request()
    stored = resolve_plan(["BG"], rows, req).to_dict()
    rows["RETIRED"] = SimpleNamespace(code="RETIRED", active=False)
    assert not stale_plan_errors(stored, req, rows, ["BG"])
    rows["BG"].active = False
    assert stale_plan_errors(stored, req, rows, ["BG"])


def test_explicit_requirements_remain_separate_from_free_text():
    from services.itinerary.normalizer import normalize_from_dict
    req = normalize_from_dict("test", {"tripDays": "1", "required_cities": ["Nasiriyah,"],
        "required_sites": ["NA_UR"], "departure_city": "Erbil", "special_notes": "Maybe visit Mosul"})
    assert req.required_cities == ["Nasiriyah"]
    assert req.required_sites == ["NA_UR"]
    assert req.departure_city == "Erbil"
    assert req.requirement_sources["required_cities"] == "explicit request field"


def test_hotel_inclusion_without_a_stay_is_a_blocker():
    rows = templates()
    rows["BG"].overnight_city = ""
    rows["BG"].title = "Baghdad departure"
    plan = resolve_plan(["BG"], rows, request())
    assert any("accommodation is included without" in issue for issue in plan.issues)


@pytest.mark.parametrize("value", [[123], ["Baghdad or Mosul"], [""]])
def test_invalid_required_places_are_not_discarded(value):
    from services.itinerary.normalizer import normalize_from_dict
    req = normalize_from_dict("test", {"tripDays": "1", "required_cities": value})
    assert req.required_cities
    checked = check_sequence(["BG"], templates(), normalized_request=req)
    assert any(f.kind == "required_city" for f in checked.faults)


def test_reference_pool_accounts_for_every_record_and_deduplicates(tmp_path, monkeypatch):
    from services.offers import offer_store
    from services.itinerary.route_corpus import load_reference_pool
    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(tmp_path))
    def write(name, day=1, text="Tour Baghdad.", overnight="Baghdad"):
        path = tmp_path / name
        path.mkdir()
        (path / "offer.json").write_text(json.dumps({"message_id": name,
            "attachment_name": name + ".docx", "sent_at": "2026-01-01T10:00:00+00:00",
            "days": [{"day": day, "text": text, "overnight_city": overnight}]}), encoding="utf-8")
    write("a")
    write("b")
    write("numbering", day=2)
    write("unknown", overnight="")
    write("excursion", text="Visit Babylon. Return to Baghdad.", overnight="")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "offer.json").write_text("broken", encoding="utf-8")
    pool = load_reference_pool(force_reload=True)
    assert pool["record_count"] == 6
    assert pool["counts"] == {"usable": 3, "needs_review": 2, "rejected": 1}
    assert len(pool["routes"]) == 2
    assert len(pool["routes"][0].references) == 2
    assert all(r["reasons"] for r in pool["records"] if r["status"] != "usable")
    assert load_reference_pool()["version"] == pool["version"]
    write("new", text="A different Baghdad day.")
    assert load_reference_pool()["version"] != pool["version"]


def test_appending_a_plan_preserves_legacy_sequence_json(tmp_path, monkeypatch):
    from services.itinerary import drafts
    monkeypatch.setattr(drafts, "ITINERARY_DRAFT_DIR", str(tmp_path))
    draft = drafts.open_draft({"tripDays": "1"})
    draft = drafts.add_sequence(draft.draft_id, drafts.ProposedSequence(source="rules", day_codes=["OLD"]))
    path = tmp_path / (draft.draft_id + ".json")
    old = json.loads(path.read_text(encoding="utf-8"))["sequences"]
    assert "plan" not in old[0]
    drafts.add_sequence(draft.draft_id, drafts.ProposedSequence(source="rules", day_codes=["BG"],
        plan=resolve_plan(["BG"], templates(), request()).to_dict()))
    assert json.loads(path.read_text(encoding="utf-8"))["sequences"][:-1] == old


def test_generation_receives_the_same_built_days_and_quote_as_validation(monkeypatch):
    from services.itinerary import generator
    rows, req = templates(), request()
    built = [object()]
    quote = SimpleNamespace(final_total_3star=123, per_person_3star=123)
    create = Mock(return_value={"ok": True, "doc_url": "test://doc", "quote": quote})
    checked = Mock(return_value={"ok": True})
    monkeypatch.setattr(generator, "load_templates", lambda: rows)
    monkeypatch.setattr(generator, "_PIPELINE", {
        "TourRequest": lambda **kwargs: SimpleNamespace(**kwargs),
        "build_itinerary": lambda request, templates: built,
        "check_request": checked, "load_pricing": lambda: {"fixed": 1},
        "calculate_quote": lambda request, days, pricing: quote,
        "generate_document": create})
    result = generator.execute_generation(req, ["BG"], expected_plan=resolve_plan(["BG"], rows, req).to_dict())
    assert result.status == "success"
    prepared = create.call_args.kwargs["prepared"]
    assert prepared["built_days"] is checked.call_args.kwargs["built_days"] is built
    assert prepared["quote"] is quote


def test_generation_blocks_a_pricing_change_after_validation(monkeypatch):
    from services.itinerary import generator
    rows, req = templates(), request()
    create = Mock()
    rates = iter([{"rate": 1}, {"rate": 2}])
    monkeypatch.setattr(generator, "load_templates", lambda: rows)
    monkeypatch.setattr(generator, "_PIPELINE", {
        "TourRequest": lambda **kwargs: SimpleNamespace(**kwargs),
        "build_itinerary": lambda request, templates: [],
        "check_request": lambda *args, **kwargs: {"ok": True},
        "load_pricing": lambda: next(rates),
        "calculate_quote": lambda *args: SimpleNamespace(final_total_3star=1),
        "generate_document": create})
    result = generator.execute_generation(req, ["BG"])
    assert result.status == "error"
    assert "Pricing changed" in result.error_message
    create.assert_not_called()
