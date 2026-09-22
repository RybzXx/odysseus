"""
content.caption — build the post caption from the product's own description.

You chose the page's promo copy as the caption. So this assembles, it does not
write: the product's description is the body, wrapped in a fixed skeleton —
title, price, tagline, and the DM call to action عالخاص.

A CaptionGenerator seam lets a later custom or model writer replace the body.
It is dormant now: with no generator, the caption uses the description as is
(spec 3.2.6).

When the caption exceeds the channel limit, only the description is trimmed,
at a word boundary. The price and the CTA are load-bearing and never cut
(spec 3.2.5).
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from mahdawi.content import settings
from mahdawi.content.models import FLAG_CAPTION_TRUNCATED
from mahdawi.fedshi.models import ProductRecord

# A generator returns a custom caption body, or None to use the description.
CaptionGenerator = Callable[[ProductRecord], Optional[str]]


def build_hashtags(record: ProductRecord, category: Optional[str] = None,
                   channel: Optional[str] = None) -> List[str]:
    """
    Base store tags plus one category tag, capped for the channel.

    Post: at most the channel's cap, no duplicates, order preserved.
    """
    tags = list(settings.BASE_HASHTAGS)
    cat = category or record.category
    if cat:
        tag = "#" + str(cat).replace(" ", "_")
        if tag not in tags:
            tags.append(tag)
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:hashtag_cap(channel)]


def _price_line(price: Optional[int]) -> str:
    if price is None or not settings.INCLUDE_PRICE:
        return ""
    return "السعر: {:,} د.ع".format(price)


def order_cta() -> str:
    """
    The call to action for the active order channel.

    Pre : settings.ORDER_CHANNEL is "dm" or "whatsapp".
    Post: the DM line, or the WhatsApp line with the number filled in. A
          WhatsApp channel with no number falls back to DM, so a half-configured
          switch never ships a caption reading "واتساب {number}".
    """
    if settings.ORDER_CHANNEL == "whatsapp" and settings.WHATSAPP_NUMBER:
        return settings.ORDER_CTA_WHATSAPP.format(number=settings.WHATSAPP_NUMBER)
    return settings.ORDER_CTA_DM


def hashtag_cap(channel: Optional[str]) -> int:
    """Post: the per-channel cap, or the general cap when the channel is unknown."""
    if channel == "tiktok":
        return settings.HASHTAG_CAP_TIKTOK
    if channel == "instagram":
        return settings.HASHTAG_CAP_INSTAGRAM
    return settings.HASHTAG_CAP


def _build_short(record: ProductRecord, price: Optional[int],
                 hashtags: List[str]) -> str:
    """
    Three lines: the product, the trust line, the call to action.

    Pre : the price already rides on the media (spec 2.3), so it is omitted here
          unless INCLUDE_PRICE overrides.
    Post: a caption of at most four lines plus the tag line. Observed Iraqi store
          captions run one to three lines (research 2026-09-22).
    """
    lines = [p for p in (record.title or "", _price_line(price),
                         settings.TRUST_LINE, order_cta()) if p]
    body = "\n".join(lines)
    tags = " ".join(hashtags)
    return body + ("\n\n" + tags if tags else "")


def build_caption(record: ProductRecord,
                  price: Optional[int],
                  category: Optional[str] = None,
                  generator: Optional[CaptionGenerator] = None,
                  channel: Optional[str] = None
                  ) -> Tuple[str, List[str], List[str]]:
    """
    Assemble the caption. Returns (caption, hashtags, flags).

    Pre : price came from content.pricing.
    Post: the caption always carries the CTA. In the short style it also carries
          the trust line and stays inside a few lines. In the full style the
          description is the body and is the only part trimmed to CAPTION_LIMIT.
    """
    flags: List[str] = []
    hashtags = build_hashtags(record, category, channel)

    if settings.CAPTION_STYLE == "short":
        return _build_short(record, price, hashtags), hashtags, flags

    body = None
    if generator is not None:
        body = generator(record)
    if not body:
        body = record.description or ""

    head = record.title or ""
    price_line = _price_line(price)
    # Fixed tail: everything that must survive truncation.
    tail_parts = [p for p in (price_line, settings.TAGLINE, order_cta(),
                              " ".join(hashtags)) if p]
    tail = "\n".join(tail_parts)

    def assemble(desc: str) -> str:
        parts = [p for p in (head, desc, tail) if p]
        return "\n\n".join(parts)

    caption = assemble(body)
    if len(caption) > settings.CAPTION_LIMIT:
        # Trim the description only, at a word boundary, leaving room for an ellipsis.
        fixed_len = len(assemble(""))
        budget = settings.CAPTION_LIMIT - fixed_len - 2
        if budget < 0:
            budget = 0
        trimmed = body[:budget].rsplit(" ", 1)[0].rstrip()
        caption = assemble(trimmed + " …")
        flags.append(FLAG_CAPTION_TRUNCATED)

    return caption, hashtags, flags
