"""
content.compliance — what the platforms and Iraqi law refuse, expressed as classes.

Two separate risks live here, and they fire at different moments.

Product risk comes from what the item IS. A support brace is a medical device to
Meta Commerce Policies whatever the caption says.

Caption risk comes from what the post SAYS. Ordinary fitness goods become a
removal on TikTok the moment a caption frames them as weight loss or muscle
gain, and Meta's own policy line covers the word "mention". So the caption must
be screened separately from the product (research 2026-09-22).

This module only classifies. content.scoring decides what a class costs.
"""
from __future__ import annotations

from typing import List, Optional

from mahdawi.fedshi.models import ProductRecord

# -- product risk classes -----------------------------------------------------
RISK_MEDICAL = "MEDICAL"        # Meta Commerce prohibits medical devices
RISK_COSMETICS = "COSMETICS"    # Meta age-restricts, Iraq requires conformity
RISK_FITNESS = "FITNESS"        # safe as a product, unsafe if the caption frames it
RISK_BLADED = "BLADED"          # Meta age-restricts bladed items
RISK_BATTERY = "BATTERY"        # lithium cells, plus Iraqi telecom type approval
RISK_APPLIANCE = "APPLIANCE"    # Iraqi Quality Mark, mandatory since 2025-09-15

# Fedshi category names that carry a class outright.
_CATEGORY_RISK = {
    "الصحة والدعم": RISK_MEDICAL,
    "العناية والتجميل": RISK_COSMETICS,
    "اللياقة": RISK_FITNESS,
    "إلكترونيات": RISK_BATTERY,
    "أجهزة منزلية": RISK_APPLIANCE,
}

# Title words that carry a class whatever the category says.
_TITLE_RISK = (
    (RISK_BLADED, ("مقص", "سكين", "سكاكين", "شفرة", "موس")),
    (RISK_MEDICAL, ("طبي", "طبية", "علاج", "مشد", "دعامة")),
    (RISK_BATTERY, ("بلوتوث", "شاحن", "بطارية", "سماعة", "لاسلكي",
                    "شمسي", "بروجكتر", "كاست", "داتا شو")),
    (RISK_COSMETICS, ("تبييض", "تفتيح", "كريم")),
)


def product_risks(record: ProductRecord) -> List[str]:
    """
    Every risk class the product itself carries.

    Pre : record came from fedshi. Post: classes in a stable order, no repeats.
          [] means the product carries no known class.
    """
    found: List[str] = []
    cat_risk = _CATEGORY_RISK.get((record.category or "").strip())
    if cat_risk:
        found.append(cat_risk)
    title = record.title or ""
    for risk, words in _TITLE_RISK:
        if risk not in found and any(w in title for w in words):
            found.append(risk)
    return found


# -- caption risk -------------------------------------------------------------
# Terms that move a post from allowed to removed on TikTok, and to age-restricted
# on Meta. Arabic first, then the English a generated caption might reach for.
BANNED_CAPTION_TERMS = (
    # weight and muscle framing
    "تنحيف", "تخسيس", "خسارة الوزن", "حرق الدهون", "شد البطن",
    "تكبير العضلات", "ضخامة", "انقاص الوزن", "إنقاص الوزن",
    "weight loss", "slimming", "fat burn", "muscle gain",
    # medical cure claims
    "يشفي", "الشفاء", "يعالج", "علاج نهائي",
    "cure", "heals", "treats disease",
    # whitening
    "تبييض البشرة", "تفتيح البشرة", "whitening", "bleaching",
)


def banned_terms_in_caption(caption: str) -> List[str]:
    """
    Every banned term the caption contains.

    Pre : caption is the assembled text about to be packaged.
    Post: [] means the caption is clear. A non-empty list names each hit, so a
          human sees exactly which wording blocks the post.
    """
    if not caption:
        return []
    lowered = caption.lower()
    return [t for t in BANNED_CAPTION_TERMS if t.lower() in lowered]


def stock_floor(stock_band: Optional[str]) -> int:
    """
    The lower bound of a Fedshi stock band.

    Pre : band looks like "20-30", or None. Post: 20 for "20-30", 0 when the
          band is missing or unparsable — an unknown stock reads as empty, which
          fails closed.
    """
    if not stock_band:
        return 0
    head = str(stock_band).split("-")[0].strip()
    return int(head) if head.isdigit() else 0
