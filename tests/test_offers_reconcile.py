"""
tests/test_offers_reconcile.py

Tests for services/offers/reconcile.py — proving the mail recovery lost nothing,
or naming exactly what it did not reach.

No corpus on disk, no network: every offer here is built in the test.
"""
import sys
from pathlib import Path

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers.models import OfferDay, SentOffer  # noqa: E402
from services.offers.reconcile import reconcile  # noqa: E402

MOSUL = ("Start the day discovering the reconstruction of the old city, especially "
         "Al-Nuri Mosque and Al Hadbaa Minaret, then walk the battle quarter.")
MARSHES = ("Drive south to the marshes, board a mashoof through the reed channels, "
           "and return to the hotel before sunset.")
BABYLON = ("Head to Babylon, a UNESCO world heritage site, and see the rebuilt "
           "Ishtar Gate and the procession street.")


def _offer(name, texts, message_id=None):
    return SentOffer(
        message_id=message_id or f"<{name}@x>",
        subject=name, sent_at=None, attachment_name=name,
        days=[OfferDay(i + 1, text, "") for i, text in enumerate(texts)],
    )


def test_the_same_itinerary_under_a_different_filename_is_one_offer():
    """Filenames drift between the .docx and PDF eras; the itinerary does not."""
    result = reconcile(
        [_offer("trip.pdf", [MOSUL, MARSHES])],
        [_offer("12 Days Group Tour - Baalbeck Sky.docx", [MOSUL, MARSHES])],
    )
    assert len(result["in_both"]) == 1
    assert result["in_both"][0]["day_coverage"] == 1.0
    assert result["legacy_only"] == [] and result["recovered_only"] == []


def test_an_offer_the_mailbox_never_held_is_reported_as_legacy_only():
    result = reconcile([_offer("trip.pdf", [MOSUL, MARSHES])],
                       [_offer("older.docx", [BABYLON, BABYLON + " Again."])])
    assert [e["legacy"] for e in result["legacy_only"]] == ["older.docx"]
    assert result["recovered_only"] == ["trip.pdf"]


def test_an_offer_newer_than_the_legacy_extract_is_recovered_only():
    result = reconcile([_offer("new.pdf", [BABYLON]), _offer("known.pdf", [MOSUL])],
                       [_offer("known.docx", [MOSUL])])
    assert result["recovered_only"] == ["new.pdf"]
    assert len(result["in_both"]) == 1


def test_a_trip_recut_by_one_day_still_matches():
    """The PDF era dropped or moved departure days; that is not a lost offer."""
    legacy = _offer("legacy.docx", [MOSUL, MARSHES, BABYLON, MOSUL + " Then rest."])
    recovered = _offer("recovered.pdf", [MOSUL, MARSHES, BABYLON])
    result = reconcile([recovered], [legacy])
    assert len(result["in_both"]) == 1
    assert 0.7 <= result["in_both"][0]["day_coverage"] < 1.0


def test_a_trip_sharing_only_one_day_of_three_is_not_the_same_offer():
    legacy = _offer("legacy.docx", [MOSUL, MARSHES, BABYLON])
    recovered = _offer("other.pdf", [MOSUL])
    result = reconcile([recovered], [legacy])
    assert result["in_both"] == []
    assert result["legacy_only"][0]["best_day_coverage"] < 0.7


def test_one_recovered_offer_cannot_absorb_two_legacy_offers():
    """Without this, a single popular itinerary would explain away the corpus."""
    recovered = [_offer("one.pdf", [MOSUL, MARSHES])]
    legacy = [_offer("a.docx", [MOSUL, MARSHES]), _offer("b.docx", [MOSUL, MARSHES])]
    result = reconcile(recovered, legacy)
    assert len(result["in_both"]) == 1
    assert len(result["legacy_only"]) == 1


def test_every_offer_is_accounted_for_exactly_once():
    recovered = [_offer("r1.pdf", [MOSUL, MARSHES]), _offer("r2.pdf", [BABYLON, BABYLON])]
    legacy = [_offer("l1.docx", [MOSUL, MARSHES]), _offer("l2.docx", [MARSHES, MARSHES]),
              _offer("l3.docx", [BABYLON, BABYLON])]
    result = reconcile(recovered, legacy)
    assert len(result["in_both"]) + len(result["legacy_only"]) == result["legacy_offers"]
    assert len(result["in_both"]) + len(result["recovered_only"]) == result["recovered_offers"]


def test_offers_with_no_days_take_no_part_in_the_comparison():
    result = reconcile([_offer("empty.pdf", [])], [_offer("also_empty.docx", [])])
    assert result["recovered_offers"] == 0 and result["legacy_offers"] == 0
    assert result["in_both"] == []
