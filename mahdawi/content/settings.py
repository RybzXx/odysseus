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
INCLUDE_PRICE = os.environ.get("MAHDAWI_INCLUDE_PRICE", "1") == "1"
ORDER_CTA = os.environ.get("MAHDAWI_ORDER_CTA", "للطلب راسلنا عالخاص")   # W-2 = DM
TAGLINE = os.environ.get("MAHDAWI_TAGLINE", "كل ما تحتاجه كل يوم")
CITY = os.environ.get("MAHDAWI_CITY", "بغداد")

# Base hashtags; a per-category tag is added at compose time. Cap the total.
BASE_HASHTAGS = os.environ.get(
    "MAHDAWI_HASHTAGS", "#مهداوي #العراق #بغداد #تسوق #توصيل").split()
HASHTAG_CAP = int(os.environ.get("MAHDAWI_HASHTAG_CAP", "10"))

# Instagram caption hard limit. TikTok is smaller but P5 posts per platform.
CAPTION_LIMIT = int(os.environ.get("MAHDAWI_CAPTION_LIMIT", "2200"))

# -- media + posting ----------------------------------------------------------
MEDIA_CAP = int(os.environ.get("MAHDAWI_MEDIA_CAP", "10"))   # Instagram carousel max
TARGET_CHANNELS = os.environ.get("MAHDAWI_CHANNELS", "instagram,tiktok").split(",")
