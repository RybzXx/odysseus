"""
tests/test_offers_module.py

Tests for services/offers — the sent-offer corpus and the catalogue gap.

No network, no mailbox, no Google API. The offer store is redirected to a
tmp_path in every test that touches disk.
"""
import io
import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers import (  # noqa: E402
    BAND_MATCH,
    BAND_NEAR_MISS,
    BAND_NO_MATCH,
    MATCH_THRESHOLD,
    NEAR_MISS_FLOOR,
    OfferDay,
    OfferTextError,
    SentOffer,
    ambiguous_rivals,
    analyse_catalogue_gap,
    band_for,
    build_routes_json,
    cluster_days,
    detect_tour_type,
    extract_offer_text,
    load_template_texts,
    normalize_day_text,
    rank_templates,
    similarity,
    split_days,
    trim_trailer,
)
from services.offers import offer_store  # noqa: E402

TEXT_MOSUL = (
    "8 AM Start the day with discovering the reconstruction of the old city, "
    "especially Al-Nuri Mosque and Al Hadbaa Minaret. Walk through the area where "
    "the last and most intensive battle took place. Lunch with locals."
)
TEXT_MARSHES = (
    "Drive south to the marshes, board a mashoof through the reed channels, "
    "and return to the hotel before sunset."
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirect the offer store at a tmp dir; no test touches the real corpus."""
    root = tmp_path / "offer_corpus"
    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(root))
    return root


def _docx_bytes(paragraphs):
    """A minimal .docx: a zip whose word/document.xml holds the paragraphs."""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    return buffer.getvalue()


# ── Normalization ─────────────────────────────────────────────────────────────

def test_normalization_removes_calendar_noise_but_keeps_content():
    normalized = normalize_day_text(
        "Monday, 24 February 2026 — 7:30 AM depart for Babylon.\nOvernight: Karbala / night 3."
    )
    assert "monday" not in normalized
    assert "february" not in normalized
    assert "2026" not in normalized
    assert "karbala" not in normalized          # the Overnight line is boilerplate
    assert "babylon" in normalized and "depart" in normalized


def test_same_day_on_two_dates_normalizes_identically():
    """The whole reason dates are stripped: one day written on two trips."""
    monday = "Monday, 24 February — 8 AM " + TEXT_MOSUL
    friday = "Friday, 06 December — 8 AM " + TEXT_MOSUL
    assert normalize_day_text(monday) == normalize_day_text(friday)
    assert similarity(monday, friday) == 1.0


def test_similarity_is_one_for_identical_and_zero_for_empty():
    assert similarity(TEXT_MOSUL, TEXT_MOSUL) == 1.0
    assert similarity("", TEXT_MOSUL) == 0.0
    assert similarity("...", TEXT_MOSUL) == 0.0


# ── Ranking and bands ─────────────────────────────────────────────────────────

def test_ranking_orders_by_score_then_code():
    ranked = rank_templates(TEXT_MOSUL, {"ZZ": TEXT_MOSUL, "AA": TEXT_MOSUL, "MM": TEXT_MARSHES})
    assert [m.code for m in ranked[:2]] == ["AA", "ZZ"], "ties must break on code"
    assert ranked[-1].code == "MM"
    assert ranked[0].score >= ranked[-1].score


def test_blank_templates_are_omitted_not_scored_as_zero():
    assert [m.code for m in rank_templates(TEXT_MOSUL, {"A": TEXT_MOSUL, "EMPTY": "   "})] == ["A"]


def test_bands_partition_the_score_range():
    assert band_for(1.0) == BAND_MATCH
    assert band_for(MATCH_THRESHOLD) == BAND_MATCH
    assert band_for(MATCH_THRESHOLD - 0.01) == BAND_NEAR_MISS
    assert band_for(NEAR_MISS_FLOOR) == BAND_NEAR_MISS
    assert band_for(NEAR_MISS_FLOOR - 0.01) == BAND_NO_MATCH


def test_edited_template_lands_in_the_near_miss_band():
    """
    The defect this module exists to fix: MO1 scores 0.848 against three real
    offer days that are MO1 plus one clause about a church rebuilt by UNESCO.
    Verbatim matching called that a new day; it is an edit.
    """
    edited = TEXT_MOSUL + " A visit to the church rebuilt by UNESCO follows."
    best = rank_templates(edited, {"MO1": TEXT_MOSUL, "MARSH": TEXT_MARSHES})[0]
    assert best.code == "MO1"
    assert best.band == BAND_NEAR_MISS
    assert NEAR_MISS_FLOOR <= best.score < MATCH_THRESHOLD


def test_unrelated_prose_matches_nothing():
    best = rank_templates("Quarterly revenue rose on enterprise licensing.",
                          {"MO1": TEXT_MOSUL})[0]
    assert best.band == BAND_NO_MATCH


def test_only_a_near_tie_counts_as_ambiguous():
    tied = rank_templates(TEXT_MOSUL, {"A": TEXT_MOSUL, "A_DUP": TEXT_MOSUL})
    assert ambiguous_rivals(tied) == ["A_DUP"]
    clear = rank_templates(TEXT_MOSUL, {"A": TEXT_MOSUL, "MARSH": TEXT_MARSHES})
    assert ambiguous_rivals(clear) == []


def test_a_distant_second_above_threshold_is_not_ambiguous():
    """
    BANMEB and BAEB score 0.850 against each other in the live catalogue. A
    verbatim day of either has a second template above threshold and must not
    be reported as a coin flip.
    """
    texts = load_template_texts()
    ranked = rank_templates(texts["BANMEB"], texts)
    assert ranked[0].code == "BANMEB" and ranked[0].score == 1.0
    assert ambiguous_rivals(ranked) == []


def test_every_vendored_template_recovers_itself():
    """The invariant every threshold in this module rests on."""
    texts = load_template_texts()
    assert len(texts) == 28
    for code, full_text in texts.items():
        if not full_text.strip():
            continue
        assert similarity(full_text, full_text) == 1.0, code
        assert rank_templates(full_text, texts)[0].code == code


# ── Text extraction and day splitting ─────────────────────────────────────────

def test_trailer_is_cut_at_the_first_marker():
    block = ("Visit the ziggurat and return.\n"
             "Includes:\nEntry tickets to all mentioned sites.\n"
             "Currency information\nIraqi Dinar.")
    trimmed = trim_trailer(block)
    assert "ziggurat" in trimmed
    assert "Includes" not in trimmed and "Iraqi Dinar" not in trimmed


@pytest.mark.parametrize("marker", [
    "End of tour", "End of the tour", "Includes:", "Inclusions:", "Pricing:",
    "Price:", "Optional:", "General Information:", "Notes:",
])
def test_every_trailer_marker_terminates_a_day(marker):
    assert trim_trailer(f"Visit the site.\n{marker}\nboilerplate here").strip() == "Visit the site."


def test_split_days_numbers_trims_and_reads_overnight():
    text = ("Day 1\nArrival and transfer.\nOvernight: Baghdad / night 1.\n"
            "Day 2\nDrive to Babylon.\nOvernight: Karbala / night 2.\n"
            "Day 3\nTransfer to the airport.\n"
            "End of tour\nIncludes:\nEntry tickets.\nContacts:\nbook@example.com\n")
    days = split_days(text)
    assert [d.day_number for d in days] == [1, 2, 3]
    assert [d.overnight_city for d in days] == ["Baghdad", "Karbala", ""]
    assert "Includes" not in days[-1].text and "book@example.com" not in days[-1].text
    assert days[-1].word_count < 20


def test_split_days_returns_empty_when_no_day_headings():
    assert split_days("A letter with no itinerary in it.") == []


def test_docx_extraction_recovers_paragraphs():
    data = _docx_bytes(["Day 1", "Arrival &amp; transfer.", "Overnight: Baghdad / night 1."])
    text = extract_offer_text(data, "offer.docx")
    assert "Day 1" in text and "Arrival & transfer." in text
    assert split_days(text)[0].overnight_city == "Baghdad"


def test_unsupported_and_unreadable_attachments_raise_offer_text_error():
    with pytest.raises(OfferTextError):
        extract_offer_text(b"anything", "logo.png")
    with pytest.raises(OfferTextError):
        extract_offer_text(b"not a zip", "offer.docx")
    with pytest.raises(OfferTextError):
        extract_offer_text(b"   ", "offer.txt")


def test_tour_type_reads_group_from_subject_or_opening():
    assert detect_tour_type("Arrival day.", "12 Days Group Tour in February") == "group"
    assert detect_tour_type("A group tour of Iraq begins.") == "group"
    assert detect_tour_type("Arrival day.", "10 Days in Iraq") == "individual"


# ── Offer store ───────────────────────────────────────────────────────────────

def _offer(message_id="<a@bilweekend.com>", days=2):
    return SentOffer(
        message_id=message_id,
        subject="10 Days in Iraq",
        sent_at=datetime(2026, 3, 1, 9, 0),
        recipients=["client@example.com"],
        attachment_name="offer.docx",
        attachment_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        attachment_bytes=4,
        days=[OfferDay(day_number=n, text=f"Day {n} prose.", overnight_city="Baghdad")
              for n in range(1, days + 1)],
    )


def test_store_round_trips_the_offer_and_keeps_the_attachment_verbatim(store):
    offer = _offer()
    directory = offer_store.store_offer(offer, b"\x50\x4b\x03\x04", "Day 1\nArrival.\n")
    assert Path(directory, "source.docx").read_bytes() == b"\x50\x4b\x03\x04"
    assert Path(directory, "text.txt").read_text(encoding="utf-8").startswith("Day 1")

    loaded = offer_store.load_offer(offer.message_id, offer.attachment_name)
    assert loaded.subject == offer.subject
    assert loaded.sent_at == offer.sent_at
    assert [d.day_number for d in loaded.days] == [1, 2]
    assert loaded.city_sequence == ["Baghdad", "Baghdad"]


def test_store_refuses_an_attachment_whose_length_disagrees(store):
    offer = _offer()
    offer.attachment_bytes = 999
    with pytest.raises(offer_store.OfferStoreError):
        offer_store.store_offer(offer, b"1234", "text")
    assert not offer_store.is_stored(offer.message_id, offer.attachment_name)


def test_store_refuses_an_offer_with_no_message_id(store):
    with pytest.raises(offer_store.OfferStoreError):
        offer_store.store_offer(_offer(message_id=""), b"", "text")


def test_slug_is_filesystem_safe_and_stable():
    slug = offer_store.offer_slug("<CAF=abc+123@mail.gmail.com>")
    assert slug == offer_store.offer_slug("<CAF=abc+123@mail.gmail.com>")
    assert not (set(slug) & set('<>:"/\\|?*'))
    assert len(slug) <= 120


def test_is_stored_is_false_before_and_true_after(store):
    offer = _offer(message_id="<b@bilweekend.com>")
    assert not offer_store.is_stored(offer.message_id, offer.attachment_name)
    offer_store.store_offer(offer, b"1234", "text")
    assert offer_store.is_stored(offer.message_id, offer.attachment_name)


def test_both_attachments_of_one_message_survive_a_round_trip(store):
    first = _offer(message_id="<pair@x>")
    first.attachment_name = "group.docx"
    second = _offer(message_id="<pair@x>")
    second.attachment_name = "individual.docx"
    offer_store.store_offer(first, b"1234", "group text")
    offer_store.store_offer(second, b"1234", "individual text")
    assert len(list(offer_store.iter_offers())) == 2
    assert offer_store.load_offer("<pair@x>", "group.docx").attachment_name == "group.docx"


def test_iter_offers_skips_a_corrupt_record_rather_than_failing(store):
    offer_store.store_offer(_offer(message_id="<good@x>"), b"1234", "t")
    broken = Path(store, "broken")
    broken.mkdir(parents=True)
    (broken / "offer.json").write_text("{not json", encoding="utf-8")
    assert [o.message_id for o in offer_store.iter_offers()] == ["<good@x>"]


def test_routes_json_is_written_in_the_schema_existing_consumers_read(store, tmp_path):
    offer_store.store_offer(_offer(message_id="<c@x>"), b"1234", "t")
    target = tmp_path / "routes.json"
    assert build_routes_json(str(target)) == 1
    payload = json.loads(target.read_text(encoding="utf-8"))
    route = payload["routes"][0]
    assert set(route) == {"id", "source_file", "day_count", "tour_type",
                          "city_sequence", "themes", "days"}
    assert route["day_count"] == 2
    assert set(route["days"][0]) == {"day", "overnight_city", "text"}
    assert not list(target.parent.glob("*.tmp")), "atomic write left a temp file behind"


# ── Gap analysis ──────────────────────────────────────────────────────────────

def _corpus():
    edited = TEXT_MOSUL + " A visit to the church rebuilt by UNESCO follows."
    first = SentOffer(message_id="<1@x>", subject="s", sent_at=None, days=[
        OfferDay(1, TEXT_MOSUL, "Mosul"),
        OfferDay(2, edited, "Mosul"),
        OfferDay(3, TEXT_MARSHES, "Nasiriyah"),
    ])
    second = SentOffer(message_id="<2@x>", subject="s", sent_at=None, days=[
        OfferDay(1, TEXT_MARSHES, "Nasiriyah"),
    ])
    return [first, second]


def test_every_day_is_counted_in_exactly_one_band():
    report = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL})
    assert report.total_days == 4
    assert report.matched + report.near_miss + report.unmatched == report.total_days
    assert (report.matched, report.near_miss, report.unmatched) == (1, 1, 2)


def test_near_misses_are_attributed_to_the_template_they_came_from():
    report = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL})
    assert report.near_miss_by_code == {"MO1": ["<1@x>#2"]}


def test_repeated_days_collapse_into_one_recurring_pattern():
    report = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL})
    assert len(report.patterns) == 1, "both marshes days are the same day"
    pattern = report.patterns[0]
    assert pattern.occurrences == 2
    assert pattern.is_recurring
    assert pattern.overnight_city == "Nasiriyah"
    assert sorted(pattern.member_keys) == ["<1@x>#3", "<2@x>#1"]


def test_pattern_ids_are_content_addressed_and_stable():
    first = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL}).patterns[0]
    second = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL}).patterns[0]
    assert first.pattern_id == second.pattern_id


def test_a_template_used_only_in_edited_form_is_not_reported_as_unused():
    """
    The distinction that decides whether a template is retired or revised: MO1
    is matched outright here, while a template reached only by near misses must
    still count as referenced.
    """
    edited_only = TEXT_MARSHES + " A stop at the reed house follows."
    corpus = [SentOffer(message_id="<edit@x>", subject="s", sent_at=None, days=[
        OfferDay(1, TEXT_MOSUL, "Mosul"),
        OfferDay(2, edited_only, "Nasiriyah"),
    ])]
    report = analyse_catalogue_gap(corpus, {"MO1": TEXT_MOSUL, "MARSH": TEXT_MARSHES})
    assert "MARSH" in report.never_matched_codes
    assert "MARSH" not in report.never_referenced_codes


def test_a_template_no_offer_comes_near_is_reported_as_unreferenced():
    never_written = "Fly to Sulaymaniyah and walk the bazaar before the museum closes."
    report = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL, "UNUSED": never_written})
    assert "MO1" not in report.never_matched_codes
    assert "UNUSED" in report.never_matched_codes
    assert "UNUSED" in report.never_referenced_codes


def test_coverage_is_matched_over_total():
    report = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL})
    assert report.coverage == pytest.approx(0.25)


def test_clustering_an_empty_corpus_returns_no_patterns():
    assert cluster_days([]) == []


def test_days_that_normalize_to_nothing_are_not_clustered():
    offer = SentOffer(message_id="<3@x>", subject="s", sent_at=None,
                      days=[OfferDay(1, "...", "")])
    assert cluster_days([(offer, offer.days[0])]) == []


def test_similarity_is_symmetric_over_long_prose():
    """
    SequenceMatcher junks only its second argument above 200 elements, which
    made the score depend on which side was the template. Every day template is
    longer than 200 characters, so this is the common case, not an edge case.
    """
    long_day = TEXT_MOSUL + " " + TEXT_MARSHES
    edited = long_day + " A visit to the church rebuilt by UNESCO follows."
    assert len(normalize_day_text(long_day)) > 200
    assert similarity(long_day, edited) == similarity(edited, long_day)


def test_a_small_edit_to_long_prose_stays_recognisable():
    """Autojunk collapsed this pair to 0.516; without it the edit is visible."""
    long_day = TEXT_MOSUL + " " + TEXT_MARSHES
    edited = long_day.replace("Al Hadbaa Minaret", "Al Hadbaa Minaret and Al-Tahira Church")
    assert similarity(long_day, edited) >= NEAR_MISS_FLOOR


# ── Proposal queue ────────────────────────────────────────────────────────────

from services.offers import proposals as prop  # noqa: E402
from services.offers.catalogue import TEMPLATE_FIELDS  # noqa: E402


@pytest.fixture
def queue(tmp_path, monkeypatch):
    root = tmp_path / "template_proposals"
    monkeypatch.setattr(prop, "TEMPLATE_PROPOSAL_DIR", str(root))
    return root


def _fields(code="NEWDAY", text=TEXT_MARSHES):
    base = {name: "" for name in TEMPLATE_FIELDS}
    base.update(code=code, title="Marshes day", city="Nasiriyah", region="Southern Iraq",
                overnight_city="Nasiriyah", full_text=text,
                included_sites_json="[]", pricing_tags_json="[]",
                active=False, needs_review=True, internal_notes="")
    return base


def test_a_proposal_missing_catalogue_fields_is_refused(queue):
    with pytest.raises(prop.ProposalError):
        prop.build_proposal(prop.KIND_NEW, {"code": "X"}, [])


def test_a_revision_must_name_its_target(queue):
    with pytest.raises(prop.ProposalError):
        prop.build_proposal(prop.KIND_REVISION, _fields(), [])


def test_proposal_ids_are_content_addressed(queue):
    a = prop.build_proposal(prop.KIND_NEW, _fields(), ["<1@x>#3"])
    b = prop.build_proposal(prop.KIND_NEW, _fields(), ["<9@x>#1"])
    assert a.proposal_id == b.proposal_id, "same proposed text is the same proposal"
    c = prop.build_proposal(prop.KIND_NEW, _fields(text=TEXT_MOSUL), [])
    assert c.proposal_id != a.proposal_id


def test_round_trip_and_pending_by_default(queue):
    saved = prop.build_proposal(prop.KIND_NEW, _fields(), ["<1@x>#3", "<2@x>#1"])
    prop.save(saved)
    loaded = prop.load(saved.proposal_id)
    assert loaded.is_pending and not loaded.is_applicable
    assert loaded.occurrences == 2
    assert loaded.fields["active"] is False and loaded.fields["needs_review"] is True


def test_approval_can_carry_reviewer_edits(queue):
    saved = prop.save(prop.build_proposal(prop.KIND_NEW, _fields(), ["<1@x>#3"])) and None
    pid = prop.build_proposal(prop.KIND_NEW, _fields(), ["<1@x>#3"]).proposal_id
    decided = prop.record_verdict(pid, prop.STATUS_APPROVED, "tightened the wording",
                                  edited_fields={"title": "Ur and the Marshes"})
    assert decided.is_applicable
    assert decided.fields["title"] == "Ur and the Marshes"
    assert decided.decided_at and decided.reviewer_note == "tightened the wording"


def test_a_verdict_cannot_be_silently_overwritten(queue):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), [])
    prop.save(proposal)
    prop.record_verdict(proposal.proposal_id, prop.STATUS_REJECTED)
    with pytest.raises(prop.ProposalError):
        prop.record_verdict(proposal.proposal_id, prop.STATUS_APPROVED)


def test_rerunning_the_analysis_does_not_reopen_a_decided_proposal(queue):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), [])
    prop.save(proposal)
    prop.record_verdict(proposal.proposal_id, prop.STATUS_REJECTED, "already covered")
    prop.save(prop.build_proposal(prop.KIND_NEW, _fields(), []))
    assert prop.load(proposal.proposal_id).status == prop.STATUS_REJECTED


def test_edits_outside_the_catalogue_schema_are_refused(queue):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), [])
    prop.save(proposal)
    with pytest.raises(prop.ProposalError):
        prop.record_verdict(proposal.proposal_id, prop.STATUS_APPROVED,
                            edited_fields={"sneaky": "value"})


def test_queue_orders_by_evidence_and_summarises(queue):
    prop.save(prop.build_proposal(prop.KIND_NEW, _fields(text=TEXT_MARSHES), ["a", "b", "c"]))
    prop.save(prop.build_proposal(prop.KIND_NEW, _fields(text=TEXT_MOSUL), ["d"]))
    pending = list(prop.iter_proposals(prop.STATUS_PENDING))
    assert [p.occurrences for p in pending] == [3, 1]
    assert prop.queue_summary()[prop.STATUS_PENDING] == 2


def test_an_unreadable_proposal_does_not_empty_the_queue(queue):
    prop.save(prop.build_proposal(prop.KIND_NEW, _fields(), ["a"]))
    (queue / "broken.json").write_text("{not json", encoding="utf-8")
    assert len(list(prop.iter_proposals())) == 1


# ── Turning a gap into proposals ──────────────────────────────────────────────

from services.offers.propose import propose_new_templates, propose_revisions  # noqa: E402


def test_a_recurring_unmatched_day_becomes_a_new_template_proposal(queue):
    report = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL})
    made = propose_new_templates(report, {"MO1": TEXT_MOSUL})
    assert len(made) == 1
    proposal = made[0]
    assert proposal.kind == prop.KIND_NEW
    assert proposal.occurrences == 2
    assert proposal.fields["code"] == "", "a code is named by a human, never generated"
    assert proposal.fields["active"] is False and proposal.fields["needs_review"] is True
    assert proposal.nearest_code == "MO1"
    assert sorted(proposal.evidence_day_keys) == ["<1@x>#3", "<2@x>#1"]


def test_a_day_written_once_is_left_bespoke(queue):
    single = [SentOffer(message_id="<solo@x>", subject="s", sent_at=None,
                        days=[OfferDay(1, TEXT_MARSHES, "Nasiriyah")])]
    report = analyse_catalogue_gap(single, {"MO1": TEXT_MOSUL})
    assert propose_new_templates(report, {"MO1": TEXT_MOSUL}) == []


def test_repeated_near_misses_become_a_revision_of_their_template(queue):
    edited = TEXT_MOSUL + " A visit to the church rebuilt by UNESCO follows."
    offers = [SentOffer(message_id="<r1@x>", subject="s", sent_at=None,
                        days=[OfferDay(1, edited, "Mosul")]),
              SentOffer(message_id="<r2@x>", subject="s", sent_at=None,
                        days=[OfferDay(1, edited, "Mosul")])]
    texts = {"MO1": TEXT_MOSUL}
    report = analyse_catalogue_gap(offers, texts)
    assert report.near_miss == 2

    made = propose_revisions(offers, report, texts)
    assert len(made) == 1
    revision = made[0]
    assert revision.kind == prop.KIND_REVISION
    assert revision.target_code == "MO1"
    assert "UNESCO" in revision.fields["full_text"], "carries the wording actually sent"
    assert revision.occurrences == 2
    assert NEAR_MISS_FLOOR <= revision.nearest_score < MATCH_THRESHOLD


def test_a_single_disagreeing_near_miss_proposes_nothing(queue):
    """One drifted day is not evidence of a revision the catalogue should adopt."""
    offers = [SentOffer(message_id="<r1@x>", subject="s", sent_at=None,
                        days=[OfferDay(1, TEXT_MOSUL + " A short extra sentence here.", "Mosul")])]
    texts = {"MO1": TEXT_MOSUL}
    report = analyse_catalogue_gap(offers, texts)
    assert propose_revisions(offers, report, texts) == []


def test_proposals_survive_the_queue_round_trip(queue):
    report = analyse_catalogue_gap(_corpus(), {"MO1": TEXT_MOSUL})
    for proposal in propose_new_templates(report, {"MO1": TEXT_MOSUL}):
        prop.save(proposal)
    assert prop.queue_summary()[prop.STATUS_PENDING] == 1
