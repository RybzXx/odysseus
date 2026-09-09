"""
tests/test_itinerary_desk_requests.py

Tests for WP6: the desk lists the worklist's requests, keeps no copy of them,
saves feedback whether or not a model may run, and never reaches an endpoint
while the owner has the proposer off.

The defect these guard against is a desk that looks like it is working. A model
route that answers while invariant 1.9 is unenforced sends the customer's own
words off the machine, and a comment that is lost when the model refuses takes
the judged rule book's only input with it.

Per tests/TESTING_STANDARD.md: tmp_path for the draft store, no network, and no
test reaches a model endpoint.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import drafts, propose_sequence  # noqa: E402
from services.itinerary.drafts import (  # noqa: E402
    RULE_STATE_DECLINED,
    RULE_STATE_DRAFTED,
    RULE_STATE_NEW,
    DraftError,
    add_comment,
    draft_id_for,
    iter_comments,
    load,
    open_draft,
    set_comment_rule_state,
)
from services.itinerary.models import NormalizedRequest  # noqa: E402
from services.itinerary.regions import (  # noqa: E402
    REGION_CENTRAL,
    REGION_KURDISTAN,
    REGION_SOUTH,
    REGION_WEST_NINEVEH,
    REGION_WHEN_UNSTATED,
)
from services.itinerary.propose_sequence import (  # noqa: E402
    MODEL_PROPOSALS_SETTING,
    ModelProposalsDisabled,
    model_proposals_enabled,
    propose_by_model,
)

CURATED_RECORD = {
    "name": "Simone Rosenkranz",
    "numberOfPeople": "4",
    "tripDays": "8",
    "accommodation": "4 star",
    "regions": "central iraq, kurdistan",
    "comments": "We would like to see Babylon.",
}


@pytest.fixture
def draft_store(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "ITINERARY_DRAFT_DIR",
                        str(tmp_path / "itinerary_drafts"))


def _settings(monkeypatch, **values):
    """Replace the settings read, so no test depends on the real file."""
    import src.settings

    monkeypatch.setattr(src.settings, "load_settings", lambda: dict(values))


# ── the model gate ───────────────────────────────────────────────────────────

def test_the_model_proposer_is_off_by_default():
    """A missing key must read as off, because off is the safe answer."""
    from src.settings import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS[MODEL_PROPOSALS_SETTING] is False


def test_an_unreadable_settings_file_reads_as_off(monkeypatch):
    import src.settings

    def _explode():
        raise OSError("no settings")

    monkeypatch.setattr(src.settings, "load_settings", _explode)
    with pytest.raises(OSError):
        model_proposals_enabled()


def test_the_gate_reads_the_setting(monkeypatch):
    _settings(monkeypatch, **{MODEL_PROPOSALS_SETTING: True})
    assert model_proposals_enabled() is True
    _settings(monkeypatch, **{MODEL_PROPOSALS_SETTING: False})
    assert model_proposals_enabled() is False


@pytest.mark.asyncio
async def test_no_request_reaches_an_endpoint_while_the_proposer_is_off(monkeypatch):
    """The regression: request text leaving the machine under invariant 1.9."""
    _settings(monkeypatch, **{MODEL_PROPOSALS_SETTING: False})

    def _never_called(*args, **kwargs):
        raise AssertionError("resolve_endpoint must not run while the gate is shut")

    import src.endpoint_resolver

    monkeypatch.setattr(src.endpoint_resolver, "resolve_endpoint", _never_called)
    request = NormalizedRequest(key="curated:1", source="curated",
                               customer_name="Simone", day_count=8)
    with pytest.raises(ModelProposalsDisabled):
        await propose_by_model(request, {"ARRBG": {}})


@pytest.mark.asyncio
async def test_the_refusal_names_the_setting_that_lifts_it(monkeypatch):
    _settings(monkeypatch, **{MODEL_PROPOSALS_SETTING: False})
    request = NormalizedRequest(key="curated:1", source="curated",
                               customer_name="Simone", day_count=8)
    with pytest.raises(ModelProposalsDisabled) as caught:
        await propose_by_model(request, {})
    assert MODEL_PROPOSALS_SETTING in str(caught.value)


# ── a worklist request keeps one thread ──────────────────────────────────────

def test_a_worklist_key_gives_a_stable_draft_id(draft_store):
    """An edit to the submitted record must not orphan the comments."""
    first = open_draft(CURATED_RECORD, request_id="curated:abc")
    edited = dict(CURATED_RECORD, tripDays="9")
    second = open_draft(edited, request_id="curated:abc")
    assert first.draft_id == second.draft_id
    assert second.request_id == "curated:abc"


def test_a_typed_request_is_still_keyed_on_its_contents(draft_store):
    """With no id, two different rows must not share one thread."""
    first = open_draft(CURATED_RECORD)
    second = open_draft(dict(CURATED_RECORD, tripDays="9"))
    assert first.draft_id != second.draft_id


def test_the_customize_column_still_names_a_request(draft_store):
    row = dict(CURATED_RECORD, Customize="cr-desk-1")
    assert open_draft(row).request_id == "cr-desk-1"


def test_a_supplied_id_outranks_the_customize_column(draft_store):
    row = dict(CURATED_RECORD, Customize="cr-desk-1")
    draft = open_draft(row, request_id="curated:abc")
    assert draft.request_id == "curated:abc"
    assert draft.draft_id == draft_id_for(row, "curated:abc")


# ── feedback survives the model being off ────────────────────────────────────

def test_a_comment_starts_as_new(draft_store):
    draft = open_draft(CURATED_RECORD, request_id="curated:abc")
    draft = add_comment(draft.draft_id, "end in Erbil, not Baghdad")
    assert draft.comments[0]["rule_state"] == RULE_STATE_NEW
    assert draft.comments[0]["comment_id"].startswith("cm-")


def test_two_comments_on_one_draft_have_different_ids(draft_store):
    draft = open_draft(CURATED_RECORD, request_id="curated:abc")
    add_comment(draft.draft_id, "end in Erbil")
    draft = add_comment(draft.draft_id, "and start in Basra")
    ids = {c["comment_id"] for c in draft.comments}
    assert len(ids) == 2


def test_a_comment_leaves_the_queue_when_it_is_read(draft_store):
    draft = open_draft(CURATED_RECORD, request_id="curated:abc")
    draft = add_comment(draft.draft_id, "end in Erbil")
    comment_id = draft.comments[0]["comment_id"]

    assert [c["comment_id"] for c in iter_comments(RULE_STATE_NEW)] == [comment_id]
    set_comment_rule_state(draft.draft_id, comment_id, RULE_STATE_DRAFTED)
    assert list(iter_comments(RULE_STATE_NEW)) == []
    assert [c["comment_id"] for c in iter_comments(RULE_STATE_DRAFTED)] == [comment_id]


def test_a_comment_that_states_no_rule_also_leaves_the_queue(draft_store):
    draft = open_draft(CURATED_RECORD, request_id="curated:abc")
    draft = add_comment(draft.draft_id, "thanks")
    comment_id = draft.comments[0]["comment_id"]
    set_comment_rule_state(draft.draft_id, comment_id, RULE_STATE_DECLINED)
    assert list(iter_comments(RULE_STATE_NEW)) == []


def test_an_unknown_rule_state_is_refused(draft_store):
    draft = open_draft(CURATED_RECORD, request_id="curated:abc")
    draft = add_comment(draft.draft_id, "end in Erbil")
    with pytest.raises(DraftError):
        set_comment_rule_state(draft.draft_id, draft.comments[0]["comment_id"], "maybe")


def test_a_comment_written_before_this_field_existed_reads_as_new(draft_store):
    """Two drafts on disk predate rule_state. They are unread, not handled."""
    draft = open_draft(CURATED_RECORD, request_id="curated:abc")
    draft.comments.append({"text": "an older comment", "at": "2026-09-05T19:58:23+00:00"})
    drafts.save(draft)

    listed = list(iter_comments(RULE_STATE_NEW))
    assert len(listed) == 1
    assert listed[0]["rule_state"] == RULE_STATE_NEW
    assert listed[0]["comment_id"].startswith("cm-")


# ── the queue normalizer reads the record it was given ───────────────────────

# A real queue row, as /api/operations/detail returns it. "Not Known" is what
# the data-entry team types for a column the submitter left blank.
QUEUE_RECORD = {
    "row_id": "qr-mtppk9g4-169e9ae5",
    "full_name": "Leonard Borriello",
    "customer_email": "lenborriello@example.com",
    "number_of_people": "1",
    "trip_days": "3-4 days",
    "regions": "Central Iraq & Middle Euphrates, Southern Iraq",
    "travel_date": "2026-10-15",
    "accommodation": "Not Known",
    "transportation": "Not Known",
    "phone": "Not known ",
    "trip_focus": "Ancient History",
    "additional_interests": "No museums. Interested in Babylon.",
    "dietary_restrictions": "Not Known",
    "service_type": "- Tour/Full service",
    "request_type": "B2C",
}


def test_a_queue_request_for_one_traveller_is_not_read_as_two():
    """The regression: pax was hard-coded to 2 whatever the record said."""
    from services.itinerary.normalizer import normalize_from_dict

    normalized = normalize_from_dict("queue:1", QUEUE_RECORD, source="queue")
    assert normalized.pax == 1


def test_a_queue_group_of_twelve_is_read_as_a_group():
    from services.itinerary.normalizer import normalize_from_dict

    normalized = normalize_from_dict(
        "queue:1", dict(QUEUE_RECORD, number_of_people="12"), source="queue")
    assert normalized.pax == 12
    assert normalized.tour_type == "group"
    assert normalized.vehicle_type != "SMALL_CAR"


def test_a_queue_placeholder_does_not_become_a_value():
    """"Not Known" is an empty cell the team typed into. It is not a hotel."""
    from services.itinerary.normalizer import normalize_from_dict

    normalized = normalize_from_dict("queue:1", QUEUE_RECORD, source="queue")
    assert normalized.hotel_tier == "3star"
    assert normalized.customer_phone is None
    assert not any("Not Known" in note for note in normalized.special_notes)


def test_a_queue_hotel_choice_is_read_when_the_record_carries_one():
    from services.itinerary.normalizer import normalize_from_dict

    normalized = normalize_from_dict(
        "queue:1", dict(QUEUE_RECORD, accommodation="5 star"), source="queue")
    assert normalized.hotel_tier == "5star"


def test_a_queue_request_keeps_the_words_the_customer_wrote():
    from services.itinerary.normalizer import normalize_from_dict

    normalized = normalize_from_dict("queue:1", QUEUE_RECORD, source="queue")
    joined = " ".join(normalized.special_notes)
    assert "Babylon" in joined
    assert "Ancient History" in joined


def test_a_queue_region_outside_the_catalogue_is_warned_about():
    from services.itinerary.normalizer import normalize_from_dict

    normalized = normalize_from_dict(
        "queue:1", dict(QUEUE_RECORD, regions="Atlantis"), source="queue")
    assert normalized.parse_warnings, "an unmapped region must be named"


def test_a_curated_request_is_unchanged_by_the_queue_repair():
    from services.itinerary.normalizer import normalize_from_dict

    normalized = normalize_from_dict("curated:1", CURATED_RECORD, source="curated")
    assert normalized.pax == 4
    assert normalized.day_count == 8
    assert normalized.hotel_tier == "4star"


# ── the region labels the live worklist actually uses ────────────────────────
#
# Measured over the 43 live Curated and Queue requests on 2026-09-07. Six of the
# eight labels had no entry in REGION_NAME_MAP, so the binder dropped every day
# of those requests as outside the requested region. The first run built 1 of 10
# documents before this, and 8 of 10 after.
#
# ws-03 phase seven took the four names the intake form itself offers, so a
# label and a region are now the same string. Kurdistan and the Nineveh plains
# stopped being one region on 2026-09-08: folding them made a request for Mosul
# match an Erbil route and report full coverage (D60).
LIVE_REGION_LABELS = {
    "Central Iraq & Middle Euphrates": REGION_CENTRAL,
    "Center & Middle Euphrates": REGION_CENTRAL,
    "Iraqi Kurdistan": REGION_KURDISTAN,
    "Western Iraq & Nineveh Plains": REGION_WEST_NINEVEH,
    "West & Nineveh Plains": REGION_WEST_NINEVEH,
    "South of Iraq": REGION_SOUTH,
    "Southern Iraq": REGION_SOUTH,
}


@pytest.mark.parametrize("label,expected", sorted(LIVE_REGION_LABELS.items()))
def test_every_live_region_label_maps_to_one_the_catalogue_models(label, expected):
    from services.itinerary.normalizer import _normalize_regions

    assert _normalize_regions(label) == [expected]


def test_a_region_the_catalogue_does_not_model_is_kept_and_warned_about():
    """An unmapped region must stay visible, not vanish into a default."""
    from services.itinerary.normalizer import _normalize_regions, unmapped_regions

    regions = _normalize_regions("Atlantis")
    assert regions == ["Atlantis"]
    assert unmapped_regions(regions) == ["Atlantis"]


def test_a_placeholder_region_is_not_a_region():
    """"Not Known" filtered every day out of a ten-day trip."""
    from services.itinerary.normalizer import _normalize_regions

    assert _normalize_regions("Not Known") == [REGION_WHEN_UNSTATED]
    assert _normalize_regions("Iraqi Kurdistan, Not Known") == [REGION_KURDISTAN]


def test_two_labels_that_mean_one_region_are_named_once():
    from services.itinerary.normalizer import _normalize_regions

    assert _normalize_regions(
        "Central Iraq & Middle Euphrates, Center & Middle Euphrates") == [REGION_CENTRAL]


def test_a_queue_request_with_no_stated_region_still_names_one():
    from services.itinerary.normalizer import normalize_from_dict

    normalized = normalize_from_dict(
        "queue:1", dict(QUEUE_RECORD, regions="Not Known"), source="queue")
    assert normalized.requested_regions == [REGION_WHEN_UNSTATED]
    assert normalized.parse_warnings == []


# ── the pipeline's own entry points are bound in one place ───────────────────

def test_the_preview_path_binds_every_pipeline_symbol_it_uses():
    """
    The regression: build_itinerary and calculate_quote were still imported
    from `src.`, which is where the pipeline lived before it was vendored. Every
    preview lost its quote to a ModuleNotFoundError the caller logged as a note.
    """
    from services.itinerary.generator import _ensure_pipeline_imported

    pipeline = _ensure_pipeline_imported()
    assert pipeline is not None
    for entry in ("build_itinerary", "calculate_quote", "check_request",
                  "generate_document", "load_pricing", "load_all_templates"):
        assert callable(pipeline[entry]), f"{entry} is not bound"


def test_no_module_still_imports_the_pipeline_from_its_old_home():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "services" / "itinerary"
    stale = re.compile(r"from src\.(calculator|builder|assembler|renderer|loader|validator)")
    offenders = [str(path) for path in root.rglob("*.py")
                 if stale.search(path.read_text(encoding="utf-8"))]
    assert offenders == [], f"pre-vendoring imports survive in {offenders}"


def test_an_empty_comment_is_refused(draft_store):
    draft = open_draft(CURATED_RECORD, request_id="curated:abc")
    with pytest.raises(DraftError):
        add_comment(draft.draft_id, "   ")


def test_a_comment_on_a_missing_draft_is_refused(draft_store):
    with pytest.raises(DraftError):
        add_comment("dr-000000000000", "end in Erbil")
