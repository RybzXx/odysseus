"""
messaging.reply_check — the code check a Gemini reply must pass to auto-send.

This replaces the engine's template byte-match. A generated reply cannot be
compared with a stored body, so code checks what it can prove instead: every
number is one the shop supplied for a product the customer's message names, no
banned or promise term appears, and the text is Arabic, short, and free of
emoji and hashtags.
"""
from __future__ import annotations

from typing import List

from mahdawi.content import text_check
from mahdawi.layer2 import settings as l2_settings
from mahdawi.messaging.models import ShopFacts


def problems(text: str, facts: ShopFacts, customer_text: str) -> List[str]:
    """
    Pre : facts is the same ShopFacts the writer received; customer_text is the
          message being answered.
    Post: [] means the reply may auto-send (all other dispatch conditions aside).
          A price appears only when the customer's message names its product,
          so a message that names no product gets no auto-sent price.
    """
    return text_check.problems(text, max_chars=l2_settings.REPLY_MAX_CHARS,
                               min_arabic_share=l2_settings.MIN_ARABIC_SHARE,
                               allowed_numbers=facts.allowed_numbers(customer_text),
                               forbid_promises=True)
