"""
layer2.caption_line — the one line of the caption that Gemini writes.

Code still assembles the caption (content.caption): the title, the trust line,
the price line when enabled, the CTA, and the hashtags are Layer One text.
Gemini writes only the selling line between the title and the trust line, so a
wrong word from Layer Two can never remove the CTA or change the price.
"""
from __future__ import annotations

from typing import Optional

from mahdawi.content import text_check
from mahdawi.fedshi.models import ProductRecord
from mahdawi.layer2 import settings, voice
from mahdawi.layer2.gateway import Gateway
from mahdawi.layer2.market_note import product_facts

_TASK = """\
Write ONE selling line for an Instagram post of the product in FACTS. The shop
adds the product title, the delivery line, and the order line itself, so do not
repeat them. Follow the angle in the market note. At most {max} characters,
at most two short sentences, no numbers at all. Answer with the line only.
"""


def check_line(text: str) -> Optional[str]:
    """Post: None when the line may go into a caption; otherwise the first problem."""
    found = text_check.problems(text, max_chars=settings.CAPTION_LINE_MAX_CHARS,
                                min_arabic_share=settings.MIN_ARABIC_SHARE,
                                allowed_numbers=None)
    if text.count("\n") > 1:
        found.append("more than two lines")
    return "; ".join(found) or None


def write_line(gateway: Gateway, record: ProductRecord, market_note: str) -> str:
    """
    Pre : market_note came from market_note.write_note.
    Post: a line that passed check_line.
    Raises: Layer2Failure — the product waits for Layer Two.
    """
    facts = dict(product_facts(record), market_note=market_note)
    task = _TASK.format(max=settings.CAPTION_LINE_MAX_CHARS)
    return gateway.complete_text(settings.MODEL_WRITER, voice.messages(task, facts),
                                 check_line, clean=text_check.strip_markup)
