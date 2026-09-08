"""
tests/test_conversation_reader.py

The customer's screenshots, and the three ways reading them can go wrong.

Three defects these guard against. A reader that raised on a shut folder would
refuse every request, because every conversation folder answered 404 until the
owner shared them. A reader that took the worklist row would find no link,
because `_fetch_merged_worklist` builds a new dictionary of 17 named keys and
`conversation_link` is not one of them. A cache that let the model's own text
win over a human's edit would undo a correction on the next run.

Measured on 2026-09-07: all six live links resolve to one `image/jpeg` file
each. The folder branch is here because one operator pasting a folder link
would otherwise read as one unreadable file.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import conversation_reader as reader  # noqa: E402
from services.itinerary.conversation_reader import (  # noqa: E402
    ConversationError,
    ExtractedImage,
    cached_text,
    conversation_link_of,
    drive_file_id,
    read_conversation,
    set_human_text,
)

# The Q018 link, exactly as the live queue holds it.
LIVE_LINK = "https://drive.google.com/open?id=1CKw3Udgg1xYpTsE_TZNzV4SdJbnW5QVK"
LIVE_ID = "1CKw3Udgg1xYpTsE_TZNzV4SdJbnW5QVK"


@pytest.fixture(autouse=True)
def a_directory_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, "CONVERSATION_DIR", str(tmp_path))


# ── the link ─────────────────────────────────────────────────────────────────

def test_the_live_link_shape_gives_its_id():
    assert drive_file_id(LIVE_LINK) == LIVE_ID


@pytest.mark.parametrize("link,expected", [
    ("https://drive.google.com/file/d/1AAAAAAAAAAAAAAAAAAAAA/view",
     "1AAAAAAAAAAAAAAAAAAAAA"),
    ("https://drive.google.com/drive/folders/1BBBBBBBBBBBBBBBBBBBBB",
     "1BBBBBBBBBBBBBBBBBBBBB"),
    ("1CCCCCCCCCCCCCCCCCCCCC", "1CCCCCCCCCCCCCCCCCCCCC"),
])
def test_the_other_shapes_a_person_pastes(link, expected):
    assert drive_file_id(link) == expected


def test_text_that_holds_no_id_gives_nothing():
    assert drive_file_id("") == ""
    assert drive_file_id("https://example.com/nothing") == ""
    assert drive_file_id("short") == ""


def test_the_link_comes_from_the_raw_record_the_draft_holds():
    assert conversation_link_of({"conversation_link": LIVE_LINK}) == LIVE_LINK


def test_the_worklist_row_carries_no_link():
    """
    `_fetch_merged_worklist` names 17 keys and this is not one of them. A
    caller that passed the worklist row would report a request with no
    screenshots rather than one it never looked for.
    """
    worklist_row = {"key": "queue:qr-1", "source": "queue", "name": "A Customer",
                    "summary": ["B2C"], "status": "New"}
    assert conversation_link_of(worklist_row) == ""


def test_a_record_with_no_link_gives_nothing():
    assert conversation_link_of({}) == ""
    assert conversation_link_of(None) == ""


# ── a shut folder never raises out of read_conversation ──────────────────────

def test_a_request_with_no_link_is_untested_and_never_raises():
    conversation = read_conversation({})
    assert conversation.was_read is False
    assert conversation.untested == ["the request carries no conversation link"]


def test_a_link_with_no_id_is_untested():
    conversation = read_conversation({"conversation_link": "https://example.com/x"})
    assert conversation.was_read is False
    assert "no Drive id" in conversation.untested[0]


def test_a_shut_folder_is_untested_and_the_run_continues(monkeypatch):
    """
    Every conversation folder answered 404 before the owner shared them. A
    reader that raised would refuse every request (spec item 17.6).
    """
    def refuse(file_id):
        raise ConversationError(
            f"Drive answered 404 for {file_id}. The service account cannot see it")

    monkeypatch.setattr(reader, "images_at", refuse)
    conversation = read_conversation({"conversation_link": LIVE_LINK})

    assert conversation.was_read is False
    assert "404" in conversation.untested[0]


def test_an_unexpected_drive_failure_is_untested_and_never_raises(monkeypatch):
    def explode(file_id):
        raise RuntimeError("the network went away")

    monkeypatch.setattr(reader, "images_at", explode)
    conversation = read_conversation({"conversation_link": LIVE_LINK})

    assert conversation.was_read is False
    assert "the network went away" in conversation.untested[0]


def test_an_empty_folder_is_untested(monkeypatch):
    monkeypatch.setattr(reader, "images_at", lambda file_id: [])
    conversation = read_conversation({"conversation_link": LIVE_LINK})

    assert conversation.was_read is False
    assert "holds no image" in conversation.untested[0]


def test_a_disabled_reader_leaves_the_reason_and_not_an_empty_list(monkeypatch):
    monkeypatch.setattr(reader, "images_at",
                        lambda file_id: [reader.DriveImage(file_id=LIVE_ID,
                                                           name="chat.jpg",
                                                           mime="image/jpeg")])

    def refuse(image, owner=None):
        raise ConversationError("itinerary_read_enabled is off")

    monkeypatch.setattr(reader, "read_image", refuse)
    conversation = read_conversation({"conversation_link": LIVE_LINK})

    assert conversation.was_read is False
    assert conversation.untested == ["itinerary_read_enabled is off"]


# ── the cache, and the human edit ────────────────────────────────────────────

def test_a_human_edit_wins_over_the_model_text():
    reader.save_text(ExtractedImage(file_id=LIVE_ID, name="chat.jpg",
                                    model_text="ten dyas in Iarq"))
    edited = set_human_text(LIVE_ID, "ten days in Iraq")

    assert edited.text == "ten days in Iraq"
    assert edited.source == "human"


def test_the_model_text_is_kept_beside_the_edit():
    """The pair is the evidence for how well the model reads."""
    reader.save_text(ExtractedImage(file_id=LIVE_ID, model_text="ten dyas"))
    set_human_text(LIVE_ID, "ten days")

    stored = cached_text(LIVE_ID)
    assert stored.model_text == "ten dyas"
    assert stored.human_text == "ten days"


def test_an_empty_edit_is_a_caller_error():
    with pytest.raises(ConversationError):
        set_human_text(LIVE_ID, "   ")


def test_a_cached_read_calls_no_model(monkeypatch):
    reader.save_text(ExtractedImage(file_id=LIVE_ID, name="chat.jpg",
                                    model_text="the conversation"))
    monkeypatch.setattr(reader, "images_at",
                        lambda file_id: [reader.DriveImage(file_id=LIVE_ID,
                                                           name="chat.jpg",
                                                           mime="image/jpeg")])

    def never(image, owner=None):
        raise AssertionError("the cache should have answered")

    monkeypatch.setattr(reader, "read_image", never)
    conversation = read_conversation({"conversation_link": LIVE_LINK})

    assert conversation.was_read is True
    assert conversation.text.endswith("the conversation")


def test_a_forced_read_ignores_the_cache(monkeypatch):
    reader.save_text(ExtractedImage(file_id=LIVE_ID, model_text="stale"))
    monkeypatch.setattr(reader, "images_at",
                        lambda file_id: [reader.DriveImage(file_id=LIVE_ID,
                                                           mime="image/jpeg")])
    monkeypatch.setattr(reader, "read_image",
                        lambda image, owner=None: ExtractedImage(
                            file_id=LIVE_ID, model_text="fresh"))
    conversation = read_conversation({"conversation_link": LIVE_LINK}, force=True)

    assert "fresh" in conversation.text
    assert "stale" not in conversation.text


def test_a_re_read_keeps_an_earlier_human_edit(monkeypatch):
    """A forced re-read must not undo a correction a reviewer already made."""
    set_human_text(LIVE_ID, "the corrected words")
    image = reader.DriveImage(file_id=LIVE_ID, name="chat.jpg", mime="image/jpeg")

    from services.itinerary import layer_access

    monkeypatch.setattr(layer_access, "_settings", dict)
    with pytest.raises(ConversationError):
        reader.read_image(image)
    assert cached_text(LIVE_ID).text == "the corrected words"


def test_each_screenshot_is_named_in_the_text(monkeypatch):
    monkeypatch.setattr(reader, "images_at", lambda file_id: [
        reader.DriveImage(file_id="a", name="one.jpg", mime="image/jpeg"),
        reader.DriveImage(file_id="b", name="two.jpg", mime="image/jpeg"),
    ])
    monkeypatch.setattr(reader, "read_image",
                        lambda image, owner=None: ExtractedImage(
                            file_id=image.file_id, name=image.name,
                            model_text=f"words of {image.name}"))
    conversation = read_conversation({"conversation_link": LIVE_LINK})

    assert "[screenshot 1: one.jpg]" in conversation.text
    assert "[screenshot 2: two.jpg]" in conversation.text
    assert conversation.statement.startswith("2 of 2 screenshot(s) read")
