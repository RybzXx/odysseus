"""
content.settings — pricing, caption, and posting tunables, overridable by env.

Defaults encode the P3 decisions: margin follows Fedshi's own profit hint
(OPEN-P3b), price shows in the caption (OPEN-P3a), captions carry Arabic store
tags (OPEN-P3c). None of these is advice; change them per the business.
"""
import os

# -- margin policy (OPEN-P3b) -------------------------------------------------
# "hint":    reselling = wholesale + profit_hint  (Fedshi's own suggested margin)
# "percent": reselling = wholesale * (1 + MARGIN_VALUE)
# "flat":    reselling = wholesale + MARGIN_VALUE  (IQD)
MARGIN_KIND = os.environ.get("MAHDAWI_MARGIN_KIND", "hint")
MARGIN_VALUE = float(os.environ.get("MAHDAWI_MARGIN_VALUE", "0.5"))   # used by percent/flat

# Round the customer price up to a clean figure (IQD).
PRICE_ROUND_TO = int(os.environ.get("MAHDAWI_PRICE_ROUND", "250"))

# -- caption (OPEN-P3a, P3c) --------------------------------------------------
# "short": title, trust line, CTA — three lines, matching observed Iraqi store
#          practice (research 2026-09-22). The price rides on the media instead.
# "full":  the earlier skeleton, with the product description as the body.
CAPTION_STYLE = os.environ.get("MAHDAWI_CAPTION_STYLE", "short")

# Off by default: the price is rendered onto the image, so repeating it in the
# caption wastes the first line and re-introduces the RTL digit collision.
INCLUDE_PRICE = os.environ.get("MAHDAWI_INCLUDE_PRICE", "0") == "1"

# The trust line. Iraqi buyers read delivery reach and cash on delivery as proof
# the seller is real, not as pricing (research 2026-09-22).
TRUST_LINE = os.environ.get(
    "MAHDAWI_TRUST_LINE", "توصيل لجميع المحافظات - الدفع عند الاستلام")

# -- order channel, swappable without a code change (spec 5) ------------------
ORDER_CHANNEL = os.environ.get("MAHDAWI_ORDER_CHANNEL", "dm")   # "dm" | "whatsapp"
ORDER_CTA_DM = os.environ.get("MAHDAWI_ORDER_CTA", "للطلب راسلنا عالخاص")
ORDER_CTA_WHATSAPP = os.environ.get(
    "MAHDAWI_ORDER_CTA_WHATSAPP", "للطلب واتساب {number}")
WHATSAPP_NUMBER = os.environ.get("MAHDAWI_WHATSAPP_NUMBER", "")

# Kept so existing callers and tests that read ORDER_CTA still resolve.
ORDER_CTA = ORDER_CTA_DM

TAGLINE = os.environ.get("MAHDAWI_TAGLINE", "كل ما تحتاجه كل يوم")
CITY = os.environ.get("MAHDAWI_CITY", "بغداد")

# Base hashtags; a per-category tag is added at compose time. Cap the total.
BASE_HASHTAGS = os.environ.get(
    "MAHDAWI_HASHTAGS", "#مهداوي #العراق #بغداد #تسوق #توصيل").split()
HASHTAG_CAP = int(os.environ.get("MAHDAWI_HASHTAG_CAP", "10"))
# Per channel. TikTok still indexes tags. Instagram's own head states they do not
# add reach, so Instagram gets the minimum (research 2026-09-22).
HASHTAG_CAP_TIKTOK = int(os.environ.get("MAHDAWI_HASHTAG_CAP_TIKTOK", "5"))
HASHTAG_CAP_INSTAGRAM = int(os.environ.get("MAHDAWI_HASHTAG_CAP_INSTAGRAM", "2"))

# Instagram caption hard limit. TikTok is smaller but P5 posts per platform.
CAPTION_LIMIT = int(os.environ.get("MAHDAWI_CAPTION_LIMIT", "2200"))

# -- media + posting ----------------------------------------------------------
MEDIA_CAP = int(os.environ.get("MAHDAWI_MEDIA_CAP", "10"))   # Instagram carousel max
TARGET_CHANNELS = os.environ.get("MAHDAWI_CHANNELS", "instagram,tiktok").split(",")
