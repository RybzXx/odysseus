"""
content.select — choose which products to post (B2 and B3).

B2 follows Fedshi's best-seller flag. B3 is a curated SKU list, high-margin by
default. Both take records already fetched by P2 and return a subset — they
fetch nothing themselves (spec 3.5).
"""
from __future__ import annotations

from typing import List

from mahdawi.fedshi.models import ProductRecord


def bestsellers(records: List[ProductRecord]) -> List[ProductRecord]:
    """B2: only records Fedshi flags الأكثر مبيعًا. Order preserved."""
    return [r for r in records if r.is_bestseller]


def curated(records: List[ProductRecord], skus: List[str]) -> List[ProductRecord]:
    """
    B3: keep a hand-picked SKU list, in the order given.

    Post: the result matches `skus` order, skipping any SKU not in records.
    """
    by_sku = {r.sku: r for r in records}
    return [by_sku[s] for s in skus if s in by_sku]


def by_margin(records: List[ProductRecord], min_profit: int) -> List[ProductRecord]:
    """
    B3 high-margin lean: records whose Fedshi profit hint meets min_profit,
    highest first.

    Post: every returned record has profit_hint >= min_profit.
    """
    kept = [r for r in records if (r.profit_hint or 0) >= min_profit]
    return sorted(kept, key=lambda r: r.profit_hint or 0, reverse=True)
