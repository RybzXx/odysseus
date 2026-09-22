"""
content.text_check — Layer One's check on customer-facing text from Layer Two.

Captions and replies are written by Gemini, and Gemini can state a price it was
never given. Nothing reaches a customer or a draft until problems() returns [].

Numbers are the load-bearing check. Every number in the text must be one code
supplied (a price, a delivery figure). Arabic-Indic and Persian digits are read
as numbers too, and thousands separators are joined, so "١٥٬٠٠٠" is 15000.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from mahdawi.content import compliance

_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# A run of digits with optional thousands separators: 15,000 / 15٬000 / 15.000
_NUMBER = re.compile(r"\d+(?:[,٬.،]\d{3})*")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")

# Words that commit the store to something only the owner may offer.
PROMISE_TERMS = ("خصم", "تخفيض", "ضمان", "كفالة", "ارجاع", "إرجاع", "استرجاع",
                 "تبديل", "مجانا", "مجاني", "هدية")


_MARKUP = re.compile(r"\*\*|__|`")
_WRAPPING = "\"'«»“”*_ \n"


def strip_markup(text: str) -> str:
    """
    Post: text without Markdown emphasis marks and without wrapping quotes.
          Gemini often bolds or quotes a one-line answer; neither may reach a
          caption or a DM, and neither changes what the text says.
    """
    return _MARKUP.sub("", (text or "")).strip(_WRAPPING)


def numbers_in(text: str) -> List[int]:
    """Post: every number in text as an int, whatever digit script it used."""
    ascii_text = (text or "").translate(_DIGIT_MAP)
    return [int(re.sub(r"[,٬.،]", "", m)) for m in _NUMBER.findall(ascii_text)]


def arabic_share(text: str) -> float:
    """Post: Arabic letters / (Arabic + Latin letters); 1.0 when there are none."""
    ar = len(_ARABIC_LETTER.findall(text or ""))
    la = len(_LATIN_LETTER.findall(text or ""))
    return 1.0 if ar + la == 0 else ar / (ar + la)


def problems(text: str, *, max_chars: int, min_arabic_share: float,
             allowed_numbers: Optional[Iterable[int]] = None,
             forbid_promises: bool = False) -> List[str]:
    """
    Every reason the text may not reach a customer.

    Pre : allowed_numbers is the set code supplied; None means no number is allowed.
    Post: [] means the text passed every check. Each entry names one failure.
    """
    out: List[str] = []
    if not text or not text.strip():
        return ["empty text"]
    if len(text) > max_chars:
        out.append("longer than %d characters" % max_chars)
    if arabic_share(text) < min_arabic_share:
        out.append("not mainly Arabic script")
    if _EMOJI.search(text):
        out.append("contains emoji")
    if "#" in text:
        out.append("contains a hashtag")
    if "*" in text or "`" in text:
        out.append("contains Markdown")
    allowed = set(allowed_numbers or ())
    stray = [n for n in numbers_in(text) if n not in allowed]
    if stray:
        out.append("states numbers code did not supply: %s" % stray)
    banned = compliance.banned_terms_in_caption(text)
    if banned:
        out.append("banned terms: %s" % ", ".join(banned))
    if forbid_promises:
        promised = [t for t in PROMISE_TERMS if t in text]
        if promised:
            out.append("promises only the owner may make: %s" % ", ".join(promised))
    return out
