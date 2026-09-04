"""
services/offers/legacy_corpus.py

Reads the pre-mail offer corpus — the 164 offers extracted from a folder of
.docx files that no longer exists.

It is kept for one purpose: ws-03 WP0.7 reconciles it against what the mailbox
returns, so the recovery can be shown to have lost nothing. It is not a source
of truth. Its day blocks were split by an extractor with no trailer terminator,
so every offer's final day carries the closing matter of the whole document;
`trim_trailer` is applied on load to undo that.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from services.offers.models import OfferDay, SentOffer
from services.offers.offer_text import trim_trailer

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LEGACY_ROUTES = os.path.join(
    os.path.dirname(_HERE), "itinerary", "data", "routes.json"
)


def load_legacy_offers(path: Optional[str] = None) -> list[SentOffer]:
    """
    Load the legacy corpus as SentOffer records.

    Pre:  `path` names a routes.json in the {"routes": [...]} schema.
    Post: one SentOffer per route, `message_id` set to `legacy:<route id>` so a
          legacy day can never collide with a recovered one, `sent_at` None
          because the legacy records carry no send date.
    """
    target = path or DEFAULT_LEGACY_ROUTES
    with open(target, encoding="utf-8") as fh:
        payload = json.load(fh)
    routes = payload.get("routes", payload) if isinstance(payload, dict) else payload

    offers = []
    for route in routes:
        offers.append(SentOffer(
            message_id=f"legacy:{route.get('id', '')}",
            subject=route.get("source_file", ""),
            sent_at=None,
            attachment_name=route.get("source_file", ""),
            tour_type=route.get("tour_type", "individual"),
            days=[
                OfferDay(
                    day_number=int(day.get("day") or 0),
                    text=trim_trailer(day.get("text") or "").strip(),
                    overnight_city=day.get("overnight_city") or "",
                )
                for day in (route.get("days") or [])
            ],
        ))
    return offers
