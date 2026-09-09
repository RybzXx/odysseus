"""
tests/test_phase_five_attacks_two.py

The second attack pass, against the fixes of 2026-09-08.

Each test pins one defect found by attacking the code rather than by reading
it. Each one failed when it was written and passes now. They stay because the
same mistake is easy to make again.

    1. a queue row never marks its regions defaulted, and a curated row does
    2. a placeholder region reads as more certain than an empty one
    3. an unparsable day count reads as a value the record gave
    4. a record's own day count has no ceiling
    5. a human edit on a folder id hides every screenshot in that folder
    6. layer 2 decides on prose that varies while the fields do not

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import conversation_reader as reader  # noqa: E402
from services.itinerary.normalizer import (  # noqa: E402
    normalize_curated_record,
    normalize_from_dict,
    normalize_queue_record,
)
from services.itinerary.regions import REGION_WHEN_UNSTATED  # noqa: E402
from services.itinerary.request_brief import field_was_defaulted  # noqa: E402

A_QUEUE_ROW = {"row_id": "qr-1", "full_name": "A Customer"}


# ── 1. the two branches disagree about regions ───────────────────────────────

def test_a_queue_row_that_names_no_region_says_the_region_is_a_default():
    queue = normalize_queue_record("queue:qr-1", dict(A_QUEUE_ROW))
    curated = normalize_curated_record("curated:cr-1", {})

    assert (queue.requested_regions == curated.requested_regions
            == [REGION_WHEN_UNSTATED])
    assert field_was_defaulted(curated, "requested_regions") is True
    assert field_was_defaulted(queue, "requested_regions") is True


# ── 2. a placeholder beats a blank ───────────────────────────────────────────

@pytest.mark.parametrize("placeholder", ["Not Known", "Not known ", "-", "None"])
def test_a_placeholder_region_is_not_more_certain_than_a_blank_one(placeholder):
    blank = normalize_curated_record("curated:cr-1", {})
    typed = normalize_curated_record("curated:cr-2", {"regions": placeholder})

    assert typed.requested_regions == blank.requested_regions
    assert field_was_defaulted(typed, "requested_regions") is True


# ── 3. an unparsable value reads as an answer ────────────────────────────────

@pytest.mark.parametrize("unreadable", ["eight", "a fortnight", "TBC", "???"])
def test_a_day_count_the_resolver_could_not_read_is_a_default(unreadable):
    request = normalize_from_dict("graded:x", {"day_count": unreadable},
                                  source="graded")
    assert request.day_count == 5
    assert field_was_defaulted(request, "day_count") is True


# ── 4. the record's own number has no ceiling ────────────────────────────────

@pytest.mark.parametrize("absurd,field,ceiling", [
    ({"day_count": "1000000000"}, "day_count", 60),
    ({"numberOfPeople": "99999"}, "pax", 100),
])
def test_a_record_number_is_bounded_like_a_brief_number(absurd, field, ceiling):
    from services.itinerary.request_brief import MAX_DAY_COUNT, MAX_PARTY_SIZE

    assert (MAX_DAY_COUNT, MAX_PARTY_SIZE) == (60, 100)
    request = normalize_from_dict("graded:x", absurd, source="graded")
    assert getattr(request, field) <= ceiling


# ── 5. an edit on a folder id hides the folder ───────────────────────────────

def test_an_edit_on_a_folder_id_does_not_hide_the_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(reader, "CONVERSATION_DIR", str(tmp_path))
    folder_id = "1FolderIdAAAAAAAAAAAAAAAAAAAAAAA"
    reader.set_human_text(folder_id, "a text somebody typed for a folder")

    listed = []

    def fake_images_at(file_id):
        listed.append(file_id)
        return [reader.DriveImage(file_id="img1", name="a.jpg", mime="image/jpeg"),
                reader.DriveImage(file_id="img2", name="b.jpg", mime="image/jpeg")]

    monkeypatch.setattr(reader, "images_at", fake_images_at)
    monkeypatch.setattr(reader, "read_image",
                        lambda image, owner=None: reader.ExtractedImage(
                            file_id=image.file_id, name=image.name,
                            model_text=f"words of {image.name}"))
    conversation = reader.read_conversation(
        {"conversation_link": f"https://drive.google.com/open?id={folder_id}"})

    assert listed, "Drive was never asked what the folder holds"
    assert len(conversation.images) == 2


# ── 6. layer 2 decides on prose ──────────────────────────────────────────────

def test_layer_two_receives_the_briefs_fields_and_not_only_its_prose():
    from types import SimpleNamespace

    from services.itinerary.candidates import Candidate, CandidateSet
    from services.itinerary.offer_run import build_rank_prompt
    from services.itinerary.request_brief import RequestBrief

    brief = RequestBrief(
        summary="A group tour.", day_count=12, party_size=20,
        must_see_sites=["Basra", "Uruk", "Mosul"], interests=["rest days"],
        read_the_conversation=True)
    found = CandidateSet(candidates=[Candidate(
        index=1, route_id="r", route_name="r.docx", route_days=12,
        match_score=1.0, region_coverage=1.0, asked_days=12,
        day_codes=["ARRBG"],
        check=SimpleNamespace(faults=[], flags=[]))])

    user = build_rank_prompt(brief, found)[1]["content"]
    for named in ("Basra", "Uruk", "Mosul", "rest days", "20"):
        assert named in user, f"layer 2 never sees {named}"
