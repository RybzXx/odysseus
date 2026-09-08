"""
tests/test_offer_run.py

Seven steps, and what happens when four of them cannot run.

Three defects these guard against. A run that stopped at the first disabled
layer would produce nothing today, because the master switch is off and every
layer is unconfigured. A ranker whose answer landed outside the candidate list
would silently become candidate 1, and the record would read as a choice
somebody made. A layer 3 that could stop a build would take the gate away from
the human, which is what D15 gives them.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import drafts as drafts_module  # noqa: E402
from services.itinerary import layer_access  # noqa: E402
from services.itinerary import run_record  # noqa: E402
from services.itinerary.candidates import Candidate, CandidateSet  # noqa: E402
from services.itinerary.offer_run import (  # noqa: E402
    RankError,
    ReviewError,
    build_rank_prompt,
    build_review_prompt,
    create_offer,
    parse_ranking,
    parse_review,
)
from services.itinerary.run_record import STEPS  # noqa: E402


@pytest.fixture(autouse=True)
def directories_of_their_own(tmp_path, monkeypatch):
    """No test touches the real drafts, runs or conversation cache."""
    from services.itinerary import conversation_reader

    for module, name in ((run_record, "ITINERARY_RUN_DIR"),
                         (drafts_module, "ITINERARY_DRAFT_DIR"),
                         (conversation_reader, "CONVERSATION_DIR")):
        directory = tmp_path / name.lower()
        directory.mkdir()
        monkeypatch.setattr(module, name, str(directory))
    # Every layer off, which is the desk's state today.
    monkeypatch.setattr(layer_access, "_settings", dict)


def a_template(code: str, city: str = "Baghdad"):
    return SimpleNamespace(code=code, overnight_city=city, city=city,
                           title=f"{city} day", active=True,
                           included_sites_json="[]", region="Central Iraq")


def a_candidate(index: int, codes, faults=(), asked=4) -> Candidate:
    check = SimpleNamespace(
        faults=[SimpleNamespace(statement=f) for f in faults], flags=[])
    return Candidate(index=index, route_id=f"r{index}",
                     route_name=f"r{index}.docx", route_days=asked,
                     match_score=0.8, region_coverage=1.0, asked_days=asked,
                     day_codes=list(codes), check=check)


# ── layer 2's answer ─────────────────────────────────────────────────────────

def test_a_ranking_names_a_candidate_and_a_reason():
    ranking = parse_ranking('{"candidate": 2, "reason": "it is not short"}', 3)
    assert ranking.index == 2
    assert ranking.reason == "it is not short"


@pytest.mark.parametrize("answer", ['{"candidate": 0}', '{"candidate": 9}',
                                    '{"candidate": -1}'])
def test_a_candidate_outside_the_list_is_a_model_error(answer):
    """A silent substitution would read as a choice nobody made (item 20.3)."""
    with pytest.raises(RankError):
        parse_ranking(answer, 5)


def test_a_day_code_where_a_number_belongs_is_a_model_error():
    with pytest.raises(RankError):
        parse_ranking('{"candidate": "SAFA"}', 5)


def test_text_that_is_not_json_is_a_model_error():
    with pytest.raises(RankError):
        parse_ranking("I would take the second one.", 5)


def test_the_ranker_sees_the_shortfall_and_the_faults():
    """A ranker given sequences and no checks would rank on wording."""
    found = CandidateSet(candidates=[
        a_candidate(1, ["ARRBG"], faults=["day 2 repeats day 1"]),
        a_candidate(2, ["ARRBG", "BG1CT", "SAFA", "BB"]),
    ])
    user = build_rank_prompt("a four-day trip", found)[1]["content"]

    assert '"days_short": 3' in user
    assert "day 2 repeats day 1" in user
    assert "you never invent one" in build_rank_prompt("x", found)[0]["content"]


# ── layer 3's answer ─────────────────────────────────────────────────────────

def test_a_review_gives_a_note_and_the_problems():
    note, problems = parse_review(
        '{"answers_the_request": false, "problems": ["no marsh day"], '
        '"note": "the customer named the marshes"}')
    assert note == "the customer named the marshes"
    assert problems == ["no marsh day"]


def test_a_review_with_no_note_falls_to_its_problems():
    note, problems = parse_review('{"problems": ["three days short"]}')
    assert note == "three days short"


def test_a_review_that_cannot_be_read_is_a_model_error():
    with pytest.raises(ReviewError):
        parse_review("Looks fine to me.")


def test_layer_three_sees_one_itinerary_and_no_other_candidate():
    """It reads the result against the request. It does not re-run the choice."""
    templates = {"BG1CT": a_template("BG1CT")}
    chosen = a_candidate(1, ["BG1CT"])
    user = build_review_prompt("a trip", chosen, templates)[1]["content"]
    system = build_review_prompt("a trip", chosen, templates)[0]["content"]

    assert "BG1CT" in user
    assert "r2.docx" not in user
    assert "You do not refuse this itinerary" in system


# ── the run with every layer off ─────────────────────────────────────────────

def test_a_run_with_every_layer_off_still_produces_a_proposal():
    """
    The desk's state today: the master switch is off and no layer is
    configured. A run that refused would refuse every request (ws-03 D43).
    """
    templates = {"BG1CT": a_template("BG1CT")}
    draft = drafts_module.open_draft({"row_id": "qr-1", "full_name": "A Customer",
                                      "trip_days": "4 days", "regions": "Central Iraq"},
                                     origin=drafts_module.ORIGIN_SHEET,
                                     request_id="queue:qr-1")
    outcome = create_offer(draft, templates)

    assert outcome.run.is_sealed is True
    assert outcome.run.is_complete is False
    assert outcome.chosen_codes != []
    assert outcome.ranking.chose_by_default is True


def test_the_record_says_which_steps_did_not_run():
    templates = {"BG1CT": a_template("BG1CT")}
    draft = drafts_module.open_draft({"row_id": "qr-2", "full_name": "A Customer",
                                      "trip_days": "4 days", "regions": "Central Iraq"},
                                     origin=drafts_module.ORIGIN_SHEET,
                                     request_id="queue:qr-2")
    run = create_offer(draft, templates).run
    untested = " ".join(run.untested)

    assert "extract" in untested
    assert "brief" in untested
    assert "rank" in untested
    assert "review" in untested
    assert [s.name for s in run.steps] == list(STEPS)


def test_a_run_with_no_model_reaches_no_endpoint():
    """Invariant 3.2. Nothing leaves the machine while the layers are off."""
    templates = {"BG1CT": a_template("BG1CT")}
    draft = drafts_module.open_draft({"row_id": "qr-3", "full_name": "A Customer",
                                      "trip_days": "4 days", "regions": "Central Iraq"},
                                     origin=drafts_module.ORIGIN_SHEET,
                                     request_id="queue:qr-3")
    assert create_offer(draft, templates).run.endpoints_reached == []


def test_the_run_leaves_a_sequence_and_a_run_id_on_the_draft():
    templates = {"BG1CT": a_template("BG1CT")}
    draft = drafts_module.open_draft({"row_id": "qr-4", "full_name": "A Customer",
                                      "trip_days": "4 days", "regions": "Central Iraq"},
                                     origin=drafts_module.ORIGIN_SHEET,
                                     request_id="queue:qr-4")
    outcome = create_offer(draft, templates)
    stored = drafts_module.load(draft.draft_id)

    assert outcome.run.run_id in stored.run_ids
    assert any(s.source == drafts_module.SOURCE_MODEL for s in stored.sequences)


def test_the_run_builds_no_document():
    """Button 1 makes a proposal. Button 2 makes the document (item 23.1)."""
    templates = {"BG1CT": a_template("BG1CT")}
    draft = drafts_module.open_draft({"row_id": "qr-5", "full_name": "A Customer",
                                      "trip_days": "4 days", "regions": "Central Iraq"},
                                     origin=drafts_module.ORIGIN_SHEET,
                                     request_id="queue:qr-5")
    outcome = create_offer(draft, templates)
    stored = drafts_module.load(draft.draft_id)

    assert stored.doc_url == ""
    assert stored.generated_from is None
    assert outcome.run.step("read_link") is not None


def test_a_request_no_route_matches_seals_the_run_and_names_every_step():
    draft = drafts_module.open_draft({"row_id": "qr-6", "full_name": "A Customer",
                                      "trip_days": "4 days", "regions": "Atlantis"},
                                     origin=drafts_module.ORIGIN_SHEET,
                                     request_id="queue:qr-6")
    run = create_offer(draft, {}).run

    assert run.is_sealed is True
    assert run.is_complete is False
    assert [s.name for s in run.steps] == list(STEPS)
