"""
content.models — PostDraft, the thing P4 stages and P5 posts.

A PostDraft is a ProductRecord turned postable: a computed price, a caption
built from the product's own description, ordered media paths, and the target
channels. It carries flags (e.g. PRICE_AT_FLOOR) so a human approving it sees
why, and it holds no secret — it is safe to write to the staged outbox.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import List, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- flags a draft can carry for the human approver ---------------------------
FLAG_PRICE_AT_FLOOR = "PRICE_AT_FLOOR"       # policy fell below the Fedshi floor
FLAG_NO_PRICE = "NO_PRICE"                    # wholesale/hint missing; price is None
FLAG_CAPTION_TRUNCATED = "CAPTION_TRUNCATED"  # description trimmed to fit the limit
FLAG_NO_MEDIA = "NO_MEDIA"                    # no media files available


@dataclass
class PostDraft:
    source_sku: str
    title: Optional[str] = None
    caption: str = ""
    price: Optional[int] = None              # reselling price shown to the customer, IQD
    profit: Optional[int] = None             # price - wholesale, IQD
    hashtags: List[str] = field(default_factory=list)
    media_paths: List[str] = field(default_factory=list)
    target_channels: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    built_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PostDraft":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
