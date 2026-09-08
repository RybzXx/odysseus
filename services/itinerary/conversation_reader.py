"""
services/itinerary/conversation_reader.py

The customer's conversation screenshots, as text.

Every queue request carries a `conversation_link`, and it is filled on 6 of 6
live rows. Nothing in this repository read it before this module. The link
already reaches the desk: `_fetch_full_record` returns every column for a queue
row, and the draft keeps that record, so four drafts on disk hold the link
today.

Measured on 2026-09-07: all six links resolve to one `image/jpeg` file each,
named as WhatsApp names an exported image. A folder is handled too, because one
operator pasting a folder link would otherwise read as one unreadable file
(spec item 17.2).

Extraction and reasoning are separate steps (ws-03 D46). This module produces
text and reasons about nothing. A human may edit the text, and the edit wins,
which is what the upload path already does for an attached image.

The text is cached against the Drive file id, so a second run of an unchanged
request calls no model (item 17.4).

Nothing here writes to Drive. The scope is `drive.readonly` (item 17.8).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.constants import DATA_DIR

logger = logging.getLogger(__name__)

CONVERSATION_DIR = os.path.join(DATA_DIR, "itinerary_conversations")

# The columns a request may carry its conversation in, most specific first.
CONVERSATION_COLUMNS = ("conversation_link", "email_chain_link")

# Drive ids as they appear in the links Bil Weekend's queue holds, plus the two
# other shapes a person pastes from a browser.
_ID_PATTERNS = (
    re.compile(r"[?&]id=([A-Za-z0-9_-]{20,})"),        # /open?id=<id>, the queue's shape
    re.compile(r"/d/([A-Za-z0-9_-]{20,})"),            # /file/d/<id>/view
    re.compile(r"/folders/([A-Za-z0-9_-]{20,})"),      # /drive/folders/<id>
)

FOLDER_MIME = "application/vnd.google-apps.folder"

# How many images one link may contribute. A folder somebody filled with a whole
# album would otherwise put fifty images into one prompt.
IMAGE_CEILING = 8

# How much text one screenshot may contribute.
#
# A chat screenshot reads as a few hundred to a few thousand characters. A
# reader that repeats itself, or an image of a wall of text, would otherwise
# reach a prompt unbounded: one image produced two million characters in a
# test, and eight of those is sixteen million.
#
# The cap sits here rather than at each prompt builder. A caller that forgot it
# would be the one caller that sends everything.
TEXT_PER_IMAGE_CEILING = 6_000

# What the reader asks the model for. It asks for the words, not for a reading
# of them. A model told to summarise a conversation decides what matters, and
# deciding what matters is layer 1's work (ws-03 D46).
READ_INSTRUCTION = (
    "This is a screenshot of a chat conversation with a travel customer. "
    "Write out every message you can read, in order, and say who sent each one. "
    "Keep names, dates, numbers and place names exactly as they appear. "
    "Do not summarise, and do not add anything the image does not show. "
    "If part of the image is unreadable, write [unreadable] there."
)

READ_TIMEOUT_SECONDS = 180

_MIME_SUFFIX = {"image/jpeg": "jpeg", "image/png": "png",
                "image/gif": "gif", "image/webp": "webp"}


class ConversationError(Exception):
    """The conversation could not be read, and the reason is stated."""


@dataclass
class DriveImage:
    """One image a conversation link points at."""
    file_id: str
    name: str = ""
    mime: str = ""
    size: int = 0


@dataclass
class ExtractedImage:
    """The text of one image, and who produced it."""
    file_id: str
    name: str = ""
    model_text: str = ""
    human_text: str = ""       # an edit, which wins over the model (item 17.5)
    where: str = ""            # host and model that read it
    # What Drive said this id is, recorded when the reader read it. Empty on an
    # entry a human typed against an id nobody has read.
    #
    # A folder id and a file id are the same shape, so without this the
    # cache-first read answered a folder link with one typed entry and never
    # listed the two real screenshots inside it (measured 2026-09-08).
    mime: str = ""
    at: str = ""

    @property
    def is_a_known_image(self) -> bool:
        """Post: whether Drive told this reader the id names one image."""
        return self.mime.startswith("image/")

    @property
    def text(self) -> str:
        """
        Post: the text a reader should use, capped. A human edit wins.

        The cap applies to both. A reviewer who pasted a whole mail thread is
        as able to fill a prompt as a model that repeated itself.
        """
        chosen = self.human_text.strip() or self.model_text.strip()
        if len(chosen) <= TEXT_PER_IMAGE_CEILING:
            return chosen
        cut = len(chosen) - TEXT_PER_IMAGE_CEILING
        return (chosen[:TEXT_PER_IMAGE_CEILING]
                + f"\n[{cut} more characters were not used]")

    @property
    def source(self) -> str:
        return "human" if self.human_text.strip() else "model"


@dataclass
class Conversation:
    """Every screenshot one request points at, as text."""
    link: str = ""
    images: list = field(default_factory=list)   # list[ExtractedImage]
    untested: list = field(default_factory=list)

    @property
    def was_read(self) -> bool:
        """Post: whether any image produced text."""
        return any(image.text for image in self.images)

    @property
    def text(self) -> str:
        """Post: every image's text, in order, each under its own heading."""
        parts = []
        for position, image in enumerate(self.images, start=1):
            if not image.text:
                continue
            parts.append(f"[screenshot {position}: {image.name or image.file_id}]\n"
                         f"{image.text}")
        return "\n\n".join(parts)

    @property
    def statement(self) -> str:
        read = sum(1 for i in self.images if i.text)
        edited = sum(1 for i in self.images if i.source == "human")
        return (f"{read} of {len(self.images)} screenshot(s) read, "
                f"{edited} edited by hand")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── the link ─────────────────────────────────────────────────────────────────

def conversation_link_of(request_row: dict) -> str:
    """
    Post: the link the request carries, or "".

    Pre:  `request_row` is the raw submitted record the draft holds, not the
          worklist's composed row.

    Blame: the worklist row cannot answer. `_fetch_merged_worklist` builds a new
    dictionary of 17 named keys and `conversation_link` is not one of them, so a
    caller that passes it gets "" for a request that has a link.
    """
    for column in CONVERSATION_COLUMNS:
        value = str((request_row or {}).get(column) or "").strip()
        if value:
            return value
    return ""


def drive_file_id(link: str) -> str:
    """
    Post: the Drive id in a link, or "" when the link holds none.

    A bare id is accepted, because an operator who copies the id alone should
    not have to know which URL shape this module expects.
    """
    text = (link or "").strip()
    if not text:
        return ""
    for pattern in _ID_PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", text):
        return text
    return ""


# ── Drive ────────────────────────────────────────────────────────────────────

def images_at(file_id: str) -> list:
    """
    Every image one Drive id points at.

    Pre:  the service account may read the id. The owner shares each folder
          with it, and nothing in this repository can do that.
    Post: a list of DriveImage, at most IMAGE_CEILING long. A file id gives one
          entry. A folder id gives its images, oldest name first. A non-image
          file gives none.

    Blame: an id the account cannot see raises ConversationError naming the
    404, because a caller that received an empty list would report a request
    with no screenshots rather than one it may not read (item 17.6).
    """
    from googleapiclient.errors import HttpError

    from services.itinerary.pipeline import google_clients

    try:
        meta = google_clients.drive_files().get(
            fileId=file_id, fields="id,name,mimeType,size").execute()
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status == 404:
            raise ConversationError(
                f"Drive answered 404 for {file_id}. The service account cannot "
                f"see it, which means nobody shared it") from exc
        raise ConversationError(f"Drive answered {status} for {file_id}") from exc

    if meta.get("mimeType") != FOLDER_MIME:
        if not str(meta.get("mimeType") or "").startswith("image/"):
            raise ConversationError(
                f"{meta.get('name') or file_id} is {meta.get('mimeType')}, "
                f"which is not an image")
        return [DriveImage(file_id=meta["id"], name=meta.get("name", ""),
                           mime=meta.get("mimeType", ""),
                           size=int(meta.get("size") or 0))]

    listed = google_clients.drive_files().list(
        q=f"'{file_id}' in parents and trashed=false",
        fields="files(id,name,mimeType,size)",
        orderBy="name", pageSize=IMAGE_CEILING * 4).execute().get("files", [])
    images = [DriveImage(file_id=f["id"], name=f.get("name", ""),
                         mime=f.get("mimeType", ""), size=int(f.get("size") or 0))
              for f in listed
              if str(f.get("mimeType") or "").startswith("image/")]
    return images[:IMAGE_CEILING]


def image_bytes(file_id: str) -> bytes:
    """
    Post: the file's bytes.

    Blame: a Drive failure raises ConversationError. The caller records the step
    as untested and the run continues.
    """
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload

    from services.itinerary.pipeline import google_clients

    buffer = io.BytesIO()
    try:
        request = google_clients.drive_files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        raise ConversationError(f"Drive answered {status} for {file_id}") from exc
    return buffer.getvalue()


# ── the cache, and the human edit ────────────────────────────────────────────

def _cache_path(file_id: str) -> str:
    """
    Post: the cache file this Drive id names, inside CONVERSATION_DIR.

    Blame: an id that could name a file elsewhere raises RecordIdError. This
    path is reached from `PUT /api/itinerary/conversations/{file_id}`, so the
    id is a caller's text and it is treated as hostile.
    """
    from services.itinerary.record_paths import record_path

    return record_path(CONVERSATION_DIR, file_id)


def cached_text(file_id: str) -> Optional[ExtractedImage]:
    """Post: what an earlier run read from this image, or None."""
    from services.itinerary.record_paths import RecordIdError

    try:
        path = _cache_path(file_id)
    except RecordIdError:
        return None
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return ExtractedImage(**json.load(fh))
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def save_text(extracted: ExtractedImage) -> str:
    """Post: the text is on disk against its Drive file id, written atomically."""
    os.makedirs(CONVERSATION_DIR, exist_ok=True)
    target = _cache_path(extracted.file_id)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(extracted), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return target


def set_human_text(file_id: str, text: str) -> ExtractedImage:
    """
    Record a human's own reading of one screenshot (item 17.5).

    Pre:  the image has been read at least once, or the caller accepts a record
          with no model text beside the edit.
    Post: the edit is stored and `ExtractedImage.text` returns it. The model
          text is kept beside it and never overwritten, because the pair is the
          evidence for how well the model read.

    Blame: an empty edit is a caller error. Clearing an edit is a different act
    from making one, and a silent clear would restore the model text under a
    reviewer who had corrected it.
    """
    from services.itinerary.record_paths import RecordIdError, is_record_id

    if not (text or "").strip():
        raise ConversationError("an edit cannot be empty")
    if not is_record_id(file_id):
        raise ConversationError(
            f"{file_id!r} is not a Drive file id")
    existing = cached_text(file_id) or ExtractedImage(file_id=file_id)
    existing.human_text = text.strip()
    existing.at = _now()
    save_text(existing)
    return existing


# ── the read ─────────────────────────────────────────────────────────────────

def _data_uri(raw: bytes, mime: str) -> str:
    suffix = _MIME_SUFFIX.get(mime, "jpeg")
    return f"data:image/{suffix};base64,{base64.b64encode(raw).decode('ascii')}"


def read_image(image: DriveImage, owner: Optional[str] = None) -> ExtractedImage:
    """
    Ask the reader layer for the words in one screenshot.

    Pre:  `LAYER_READ` resolves, which means the master switch is on, the
          layer's switch is on, and the owner named an endpoint for it.
    Post: an ExtractedImage carrying the model's text and the endpoint that
          produced it. The result is cached against the Drive file id.

    Blame: a layer the owner did not configure raises ConversationError with the
    refusal as its message. The caller records the step untested and the run
    continues (ws-03 D43). This module never reaches another role's model, and
    never auto-detects one (invariant 3.2).
    """
    from services.itinerary.layer_access import LAYER_READ, resolve_layer
    from src.llm_core import llm_call

    access = resolve_layer(LAYER_READ, owner=owner)
    if not access.may_run:
        raise ConversationError(access.refusal)

    raw = image_bytes(image.file_id)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": READ_INSTRUCTION},
            {"type": "image_url",
             "image_url": {"url": _data_uri(raw, image.mime)}},
        ],
    }]
    try:
        answer = llm_call(access.url, access.model, messages,
                          headers=access.headers, timeout=READ_TIMEOUT_SECONDS)
    except Exception as exc:
        raise ConversationError(
            f"{access.where} did not read {image.name or image.file_id}: {exc}"
        ) from exc

    extracted = ExtractedImage(file_id=image.file_id, name=image.name,
                               model_text=(answer or "").strip(),
                               where=access.where, mime=image.mime, at=_now())
    existing = cached_text(image.file_id)
    if existing is not None:
        extracted.human_text = existing.human_text
    save_text(extracted)
    return extracted


def read_conversation(request_row: dict, owner: Optional[str] = None,
                      force: bool = False) -> Conversation:
    """
    Every screenshot one request points at, as text.

    Pre:  `request_row` is the raw record the draft holds.
    Post: a Conversation. Each image that could not be read leaves an entry in
          `untested` naming the reason, and the others are still returned. A
          request with no link, an unreadable folder and a disabled layer all
          give `was_read` false and a stated reason.
    Inv:  nothing is written to Drive, and no endpoint but the reader layer's
          own is reached.

    Blame: this never raises for a shut folder or a disabled layer. Every
    conversation folder answered 404 before the owner shared them, so a reader
    that refused would refuse every request (item 17.6).
    """
    conversation = Conversation(link=conversation_link_of(request_row))
    if not conversation.link:
        conversation.untested.append(
            "the request carries no conversation link")
        return conversation

    file_id = drive_file_id(conversation.link)
    if not file_id:
        conversation.untested.append(
            f"no Drive id could be read from {conversation.link}")
        return conversation

    # The cache first, but only where an earlier read proved the id names one
    # image.
    #
    # All six live links name one image, so the link's own id is the cache key
    # and Drive has nothing to add. Listing first made every cached
    # conversation unreachable the moment Drive answered 404.
    #
    # `is_a_known_image` is what keeps a folder out. An entry a human typed
    # against a folder id carries no mime, so the folder is still listed and
    # the edit reaches whichever image inside it shares that id.
    if not force:
        held = cached_text(file_id)
        if held is not None and held.text and held.is_a_known_image:
            conversation.images.append(held)
            return conversation

    try:
        found = images_at(file_id)
    except ConversationError as exc:
        conversation.untested.append(str(exc))
        return conversation
    except Exception as exc:                       # noqa: BLE001
        logger.warning("the conversation link could not be listed: %s", exc)
        conversation.untested.append(f"the link could not be listed: {exc}")
        return conversation

    if not found:
        conversation.untested.append(
            f"{conversation.link} holds no image")
        return conversation

    for image in found:
        cached = None if force else cached_text(image.file_id)
        if cached is not None and cached.text:
            cached.name = cached.name or image.name
            conversation.images.append(cached)
            continue
        try:
            conversation.images.append(read_image(image, owner=owner))
        except ConversationError as exc:
            conversation.untested.append(str(exc))
        except Exception as exc:                   # noqa: BLE001
            logger.warning("a screenshot could not be read: %s", exc)
            conversation.untested.append(
                f"{image.name or image.file_id} could not be read: {exc}")
    return conversation
