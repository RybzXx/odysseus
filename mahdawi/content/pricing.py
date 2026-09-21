"""
content.pricing — set the customer price, never below Fedshi's floor.

The default policy follows Fedshi's own profit hint ("اربح X او اكثر"), so the
B3 high-margin lane needs no invented percentage: reselling = wholesale + hint.
Percent and flat policies stay available for tuning.

The floor (reselling_price_min) is a Fedshi rule, not a preference. A price
below it is raised to it and the draft is flagged, never sent low (spec 3.1.2).
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from mahdawi.content import settings
from mahdawi.content.models import FLAG_NO_PRICE, FLAG_PRICE_AT_FLOOR
from mahdawi.fedshi.models import ProductRecord


def _round_up(value: int, step: int) -> int:
    if step <= 1:
        return value
    return int(math.ceil(value / step) * step)


def _raw_price(record: ProductRecord, kind: str, margin_value: float) -> Optional[int]:
    """The price a policy proposes, before the floor and rounding. None if unknowable."""
    w = record.wholesale_price
    if w is None:
        return None
    if kind == "hint":
        if record.profit_hint is None:
            return None
        return w + record.profit_hint
    if kind == "percent":
        return int(w * (1 + margin_value))
    if kind == "flat":
        return int(w + margin_value)
    raise ValueError("unknown margin kind %r" % kind)


def price(record: ProductRecord,
          kind: Optional[str] = None,
          margin_value: Optional[float] = None,
          round_to: Optional[int] = None) -> Tuple[Optional[int], Optional[int], List[str]]:
    """
    Compute (reselling_price, profit, flags) for a record.

    Pre : record came from a FedshiSource.
    Post: reselling_price >= record.reselling_price_min when both are known.
          profit = reselling_price - wholesale_price, or None.
    Invariant: never returns a price below the floor. When the policy would go
          under, the floor wins and FLAG_PRICE_AT_FLOOR is set (spec 3.1.2).
    """
    kind = kind or settings.MARGIN_KIND
    margin_value = settings.MARGIN_VALUE if margin_value is None else margin_value
    round_to = settings.PRICE_ROUND_TO if round_to is None else round_to
    flags: List[str] = []

    raw = _raw_price(record, kind, margin_value)
    floor = record.reselling_price_min

    if raw is None and floor is None:
        return None, None, [FLAG_NO_PRICE]

    candidate = raw if raw is not None else floor
    if floor is not None and candidate < floor:
        candidate = floor
        flags.append(FLAG_PRICE_AT_FLOOR)

    reselling = _round_up(candidate, round_to)
    profit = (reselling - record.wholesale_price) if record.wholesale_price is not None else None
    return reselling, profit, flags
