"""
fedshi.parse — turn a raw page reading into a ProductRecord. Pure, no I/O.

The engine (Playwright) hands this module a dict of what the rendered page
showed: title, full body text, and media URLs. This module maps that to a
ProductRecord. Keeping it pure makes it testable offline against a saved
fixture, with no browser and no network (spec 2.6.1).

The body text is Arabic and label-anchored. Every field is read after a
specific Arabic label, so the dashboard's "الأرباح المحققة" (earnings) can
never be mistaken for the product's "الربح" (profit).
"""
from __future__ import annotations

import re
from typing import List, Optional

from mahdawi.fedshi.models import ProductRecord

# A Fedshi price: 1-3 digits then comma-grouped thousands. "4,550" / "16,800".
_NUM = re.compile(r"\d{1,3}(?:,\d{3})*")

# Labels that mark the end of a value region, so a section read stops cleanly.
_STOPS = ("رابط الفانلز", "رقم المنتج", "اللون", "اضف الى السلة", "تحميل الصور",
          "احصائيات", "المواصفات", "متبقية", "سعر الزبون", "الربح")


def _to_int(s: str) -> Optional[int]:
    m = _NUM.search(s)
    return int(m.group(0).replace(",", "")) if m else None


def _section(text: str, start_label: str, stops=_STOPS) -> str:
    """
    The text after start_label, up to the next stop label.

    Post: "" when the label is absent. The window never crosses a stop, so a
    number belonging to a later field cannot leak into this one.
    """
    i = text.find(start_label)
    if i < 0:
        return ""
    rest = text[i + len(start_label):]
    end = len(rest)
    for stop in stops:
        if stop == start_label:
            continue
        j = rest.find(stop)
        if 0 <= j < end:
            end = j
    return rest[:end]


def _first_int(text: str, label: str, stops=_STOPS) -> Optional[int]:
    return _to_int(_section(text, label, stops))


def _all_ints(text: str, label: str, stops=_STOPS) -> List[int]:
    return [int(m.replace(",", "")) for m in _NUM.findall(_section(text, label, stops))]


def _colors(text: str) -> List[str]:
    """
    Colour names after the "اللون" label, up to the cart button.

    Post: [] when absent. Lines that are UI chrome (empty, cart) are dropped.
    """
    seg = _section(text, "اللون", stops=("اضف الى السلة", "تحميل الصور", "احصائيات"))
    out = []
    for line in seg.splitlines():
        s = line.strip()
        if s and s not in ("اضف الى السلة",):
            out.append(s)
    return out


def _description(text: str) -> Optional[str]:
    seg = _section(text, "وصف ترويجي", stops=("نسخ الوصف", "اعرض المزيد", "احصائيات"))
    seg = seg.strip()
    return seg or None


def build_record(raw: dict, sku: str) -> ProductRecord:
    """
    Map a raw page reading to a ProductRecord.

    Pre : raw has keys url, title, body_text, image_urls, video_urls.
    Post: every field is either read from raw or None/empty — never invented
          (spec 2.4.4). Prices are ints in IQD.
    """
    text = raw.get("body_text", "") or ""

    wholesale = _first_int(text, "سعر الجملة")
    profit = _first_int(text, "الربح")
    customer_prices = _all_ints(text, "سعر الزبون المقترح",
                                stops=("متبقية", "رابط الفانلز", "رقم المنتج"))
    reselling_min = min(customer_prices) if customer_prices else None

    stock = None
    m = re.search(r"متبقية\s+([\d]+(?:-[\d]+)?)\s*قطعة", text)
    if m:
        stock = m.group(1)

    is_bestseller = "الأكثر مبيع" in text   # matches with or without tatweel

    return ProductRecord(
        sku=sku,
        title=raw.get("title"),
        description=_description(text),
        category=None,                      # not reliably present on the page
        wholesale_price=wholesale,
        reselling_price_min=reselling_min,
        profit_hint=profit,
        colors=_colors(text),
        stock_band=stock,
        is_bestseller=is_bestseller,
        image_urls=list(raw.get("image_urls", [])),
        video_urls=list(raw.get("video_urls", [])),
        source_url=raw.get("url"),
    )
