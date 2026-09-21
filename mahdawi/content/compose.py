"""
content.compose — assemble a ProductRecord into a PostDraft. No I/O.

build_draft joins pricing, caption, and media ordering into one postable draft.
It composes from a record whose media P2 already downloaded; it never posts,
stages, downloads, or reaches the network (spec 3.4.3).
"""
from __future__ import annotations

from typing import List, Optional

from mahdawi.content import caption as caption_mod
from mahdawi.content import media_select, pricing, settings
from mahdawi.content.caption import CaptionGenerator
from mahdawi.content.models import FLAG_NO_MEDIA, PostDraft
from mahdawi.fedshi.models import ProductRecord


def build_draft(record: ProductRecord,
                media_paths: Optional[List[str]] = None,
                category: Optional[str] = None,
                channels: Optional[List[str]] = None,
                generator: Optional[CaptionGenerator] = None) -> PostDraft:
    """
    Turn a record into a complete PostDraft.

    Pre : record from a FedshiSource; media_paths point at files P2 saved.
    Post: a PostDraft with a price (or a NO_PRICE flag), a caption carrying the
          CTA, ordered media, and target channels. No network or DB touched.
    """
    price, profit, price_flags = pricing.price(record)
    text, hashtags, caption_flags = caption_mod.build_caption(
        record, price, category=category, generator=generator)

    # media_paths are local files from P2; empty when none were downloaded yet.
    ordered = media_select.order_media(media_paths or [])

    flags = list(price_flags) + list(caption_flags)
    if not ordered:
        flags.append(FLAG_NO_MEDIA)

    return PostDraft(
        source_sku=record.sku,
        title=record.title,
        caption=text,
        price=price,
        profit=profit,
        hashtags=hashtags,
        media_paths=ordered,
        target_channels=list(channels or settings.TARGET_CHANNELS),
        flags=flags,
    )
