"""
services/offers/offer_store.py

One directory per sent offer, holding the attachment and everything derived
from it.

    offer_corpus/<slug>/source.<ext>    the attachment exactly as sent
                       /text.txt        extracted text
                       /offer.json      parsed days plus provenance

The original attachment is kept forever and never rewritten. The corpus that
preceded this one was rebuilt from a folder of .docx files that no longer
exists anywhere, which is why nothing here derives an offer from another
derivative (ws-03 invariant 1.1).

`routes.json` is a build artifact of this store, not a second store — every
existing consumer keeps reading the file it already reads.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from typing import Iterator, Optional

from src.constants import OFFER_CORPUS_DIR

from services.offers.models import OfferDay, SentOffer

_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_OFFER_RECORD = "offer.json"
_OFFER_TEXT = "text.txt"
_SOURCE_STEM = "source"


class OfferStoreError(Exception):
    """Raised when the store cannot satisfy a write it was asked to make."""


def offer_slug(message_id: str, attachment_name: str = "") -> str:
    """
    Directory name for one offer.

    Post: filesystem-safe, stable for a given (message, attachment) pair, and
          short enough for Windows path limits.

    The attachment is part of the key, not decoration. One email can carry two
    offers — a group and an individual version of the same trip — and keying on
    the message alone makes the second silently overwrite the first.
    """
    cleaned = _UNSAFE_CHARS_RE.sub("-", (message_id or "").strip().strip("<>"))
    cleaned = cleaned.strip("-") or "unknown"
    slug = cleaned[:100]
    if attachment_name:
        digest = hashlib.sha1(attachment_name.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug}-{digest}"
    return slug


def offer_dir(message_id: str, attachment_name: str = "") -> str:
    return os.path.join(OFFER_CORPUS_DIR, offer_slug(message_id, attachment_name))


def is_stored(message_id: str, attachment_name: str = "") -> bool:
    """True when this offer's record already exists — the fetch can skip it."""
    return os.path.exists(
        os.path.join(offer_dir(message_id, attachment_name), _OFFER_RECORD)
    )


def _source_path(directory: str, attachment_name: str) -> str:
    _, ext = os.path.splitext(attachment_name or "")
    return os.path.join(directory, _SOURCE_STEM + (ext.lower() or ".bin"))


def store_offer(offer: SentOffer, attachment_data: bytes, text: str) -> str:
    """
    Write one offer's attachment, text and parsed record.

    Pre:  `offer.message_id` is non-empty; `attachment_data` is the bytes as
          received; `offer.attachment_bytes` is their declared length.
    Post: the directory holds all three files, and the stored attachment is
          byte-identical to what was passed in.

    Blame: a length mismatch is a fetch bug, not a store bug, and is raised
    rather than written — a truncated attachment silently stored would corrupt
    the corpus permanently.
    """
    if not offer.message_id:
        raise OfferStoreError("offer has no message_id")
    if offer.attachment_bytes and offer.attachment_bytes != len(attachment_data):
        raise OfferStoreError(
            f"attachment length mismatch for {offer.message_id}: "
            f"declared {offer.attachment_bytes}, received {len(attachment_data)}"
        )

    directory = offer_dir(offer.message_id, offer.attachment_name)
    os.makedirs(directory, exist_ok=True)

    with open(_source_path(directory, offer.attachment_name), "wb") as fh:
        fh.write(attachment_data)
    with open(os.path.join(directory, _OFFER_TEXT), "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(os.path.join(directory, _OFFER_RECORD), "w", encoding="utf-8") as fh:
        json.dump(_offer_to_dict(offer), fh, ensure_ascii=False, indent=2)
    return directory


def _offer_to_dict(offer: SentOffer) -> dict:
    return {
        "message_id": offer.message_id,
        "subject": offer.subject,
        "sent_at": offer.sent_at.isoformat() if offer.sent_at else None,
        "recipients": offer.recipients,
        "attachment_name": offer.attachment_name,
        "attachment_mime": offer.attachment_mime,
        "attachment_bytes": offer.attachment_bytes,
        "tour_type": offer.tour_type,
        "extraction_warnings": offer.extraction_warnings,
        "days": [
            {
                "day": day.day_number,
                "overnight_city": day.overnight_city,
                "text": day.text,
            }
            for day in offer.days
        ],
    }


def _offer_from_dict(record: dict) -> SentOffer:
    sent_at = record.get("sent_at")
    return SentOffer(
        message_id=record.get("message_id", ""),
        subject=record.get("subject", ""),
        sent_at=datetime.fromisoformat(sent_at) if sent_at else None,
        recipients=list(record.get("recipients") or []),
        attachment_name=record.get("attachment_name", ""),
        attachment_mime=record.get("attachment_mime", ""),
        attachment_bytes=int(record.get("attachment_bytes") or 0),
        tour_type=record.get("tour_type", "individual"),
        days=[
            OfferDay(
                day_number=int(d.get("day") or 0),
                text=d.get("text") or "",
                overnight_city=d.get("overnight_city") or "",
            )
            for d in (record.get("days") or [])
        ],
        extraction_warnings=list(record.get("extraction_warnings") or []),
    )


def load_offer(message_id: str, attachment_name: str = "") -> Optional[SentOffer]:
    path = os.path.join(offer_dir(message_id, attachment_name), _OFFER_RECORD)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return _offer_from_dict(json.load(fh))


def iter_offers() -> Iterator[SentOffer]:
    """
    Yield every stored offer, oldest first where a sent date is known.

    Post: a directory with an unreadable record is skipped, not raised — one
          bad offer must not stop a corpus-wide pass.
    """
    if not os.path.isdir(OFFER_CORPUS_DIR):
        return
    records = []
    for name in sorted(os.listdir(OFFER_CORPUS_DIR)):
        path = os.path.join(OFFER_CORPUS_DIR, name, _OFFER_RECORD)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                records.append(_offer_from_dict(json.load(fh)))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    records.sort(key=lambda o: (o.sent_at is None, o.sent_at or datetime.min))
    yield from records


def reparse_stored(prune: bool = False) -> dict:
    """
    Re-split every stored offer's days from the text already on disk.

    The extracted text is kept precisely so a parser improvement does not cost
    another pass over the mailbox. Nothing here re-reads mail, and `source.*` is
    never touched.

    Pre:  the store holds `text.txt` beside each `offer.json`.
    Post: each record's days reflect the current splitter. A record that now
          yields no days is reported as carrying no itinerary, and removed only
          when `prune` is set — the caller decides whether to discard.
    """
    from services.offers.offer_text import split_days

    outcome = {"reparsed": 0, "days_before": 0, "days_after": 0,
               "no_itinerary": [], "pruned": 0}
    if not os.path.isdir(OFFER_CORPUS_DIR):
        return outcome

    for name in sorted(os.listdir(OFFER_CORPUS_DIR)):
        directory = os.path.join(OFFER_CORPUS_DIR, name)
        record_path = os.path.join(directory, _OFFER_RECORD)
        text_path = os.path.join(directory, _OFFER_TEXT)
        if not (os.path.exists(record_path) and os.path.exists(text_path)):
            continue
        try:
            with open(record_path, encoding="utf-8") as fh:
                record = json.load(fh)
            with open(text_path, encoding="utf-8") as fh:
                text = fh.read()
        except (json.JSONDecodeError, OSError):
            continue

        offer = _offer_from_dict(record)
        outcome["days_before"] += len(offer.days)
        offer.days = split_days(text)
        outcome["days_after"] += len(offer.days)
        outcome["reparsed"] += 1

        if not offer.days:
            outcome["no_itinerary"].append(offer.attachment_name)
            if prune:
                shutil.rmtree(directory, ignore_errors=True)
                outcome["pruned"] += 1
            continue

        temporary = record_path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as fh:
            json.dump(_offer_to_dict(offer), fh, ensure_ascii=False, indent=2)
        os.replace(temporary, record_path)
    return outcome


def build_routes_json(path: str) -> int:
    """
    Write the corpus in the schema `services/itinerary` already reads.

    Post: `path` holds {"routes": [...]} with one entry per stored offer, and
          the file is replaced atomically so a crash mid-write cannot leave a
          half-corpus behind a name every consumer trusts.

    Returns the number of routes written.
    """
    routes = []
    for offer in iter_offers():
        routes.append({
            "id": offer_slug(offer.message_id, offer.attachment_name),
            "source_file": offer.attachment_name,
            "day_count": offer.day_count,
            "tour_type": offer.tour_type,
            "city_sequence": offer.city_sequence,
            "themes": [],
            "days": [
                {
                    "day": day.day_number,
                    "overnight_city": day.overnight_city,
                    "text": day.text,
                }
                for day in offer.days
            ],
        })
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump({"routes": routes}, fh, ensure_ascii=False, indent=1)
    os.replace(temporary, path)
    return len(routes)
