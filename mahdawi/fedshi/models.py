"""
fedshi.models — the one object the rest of the system reads.

ProductRecord is what a FedshiSource returns and what content/ (P3) prices and
captions. It carries facts read from the page, never a computed reselling price
— that decision belongs to P3 (spec 2.1.2).

Prices are integers in IQD, or None when the page does not show them. A None is
an honest gap; an invented number is a bug (spec 2.4.4).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import List, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProductRecord:
    sku: str                              # e.g. "AFOZC" — the product code
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    wholesale_price: Optional[int] = None       # what the reseller pays Fedshi, IQD
    reselling_price_min: Optional[int] = None    # floor Fedshi allows, IQD
    profit_hint: Optional[int] = None            # Fedshi's "الربح ... أو أكثر", IQD
    colors: List[str] = field(default_factory=list)
    stock_band: Optional[str] = None             # e.g. "20-30"
    is_bestseller: bool = False
    image_urls: List[str] = field(default_factory=list)   # raw prod-media origins
    video_urls: List[str] = field(default_factory=list)
    media_dir: Optional[str] = None              # where media.py saved files
    source_url: Optional[str] = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ProductRecord":
        """Pre: d has the keys to_dict emits. Post: from_dict(r.to_dict()) == r."""
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class ListingEntry:
    """One card on a listing page. Enough to choose a SKU to fetch in full."""
    sku: str
    title: Optional[str] = None
    is_bestseller: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
