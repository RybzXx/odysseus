"""
content.scoring — reject a product, or rank it A, B, or C.

Two stages, in order. Hard gates reject outright and name the reason, so the
dashboard can say why. Whatever survives falls into a tier, and the tier decides
posting order.

Every threshold comes from the 40-product Fedshi sample analysed on 2026-09-22.
Margin is bimodal there, so 25% separates the traps from the rest. A profit hint
of exactly 1,000 IQD marks a floor filler, and every sub-10% item carries one.
Stock band 0-10 means the product can sell out while the post is live.

The gates rank the product, never the person. Nothing here posts anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from mahdawi.content import compliance
from mahdawi.fedshi.models import ProductRecord

# -- gate identifiers, stable enough to store on a row ------------------------
GATE_MARGIN = "G1_MARGIN"
GATE_STOCK = "G2_STOCK"
GATE_COMPLIANCE = "G3_COMPLIANCE"
GATE_LOGISTICS = "G4_LOGISTICS"
GATE_MEDIA = "G5_MEDIA"

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_REJECTED = "REJECTED"

# Thresholds (spec 3.1, 3.2).
MIN_MARGIN_PCT = 25.0          # below this the margin cannot absorb one refusal
TIER_A_MARGIN_PCT = 40.0
TIER_A_STOCK_FLOOR = 20
TIER_C_PRICE_IQD = 40000       # above the observed impulse band
TRAP_PROFIT_HINT = 1000        # Fedshi's floor filler

# A product class that blocks the product itself, whatever the caption says.
_BLOCKING_PRODUCT_RISKS = (compliance.RISK_MEDICAL, compliance.RISK_COSMETICS,
                           compliance.RISK_BLADED)
# A product class that is a shipping problem rather than a policy one.
_LOGISTICS_RISKS = (compliance.RISK_BATTERY, compliance.RISK_APPLIANCE)


@dataclass
class ProductScore:
    """Why a product was rejected, or which tier it earned."""
    sku: str
    tier: str
    margin_pct: Optional[float] = None
    price: Optional[int] = None
    gates_failed: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)   # human-readable, one per gate
    risks: List[str] = field(default_factory=list)     # compliance classes found

    @property
    def rejected(self) -> bool:
        return self.tier == TIER_REJECTED

    def to_dict(self) -> dict:
        return {"sku": self.sku, "tier": self.tier, "margin_pct": self.margin_pct,
                "price": self.price, "gates_failed": list(self.gates_failed),
                "reasons": list(self.reasons), "risks": list(self.risks)}


def _margin_pct(price: Optional[int], wholesale: Optional[int]) -> Optional[float]:
    """Post: margin as a percentage of the selling price, or None when unknown."""
    if not price or wholesale is None or price <= 0:
        return None
    return (price - wholesale) / price * 100.0


def score_product(record: ProductRecord, price: Optional[int] = None) -> ProductScore:
    """
    Gate then tier one product.

    Pre : record came from fedshi. price is the reselling price from
          content.pricing, or None to derive it from wholesale + profit_hint.
    Post: tier is REJECTED with at least one gate, or A/B/C with none.
    Invariant: a rejected product never carries a tier, so a caller cannot post
          a rejected SKU by reading the tier alone.
    """
    if price is None and record.wholesale_price and record.profit_hint:
        price = record.wholesale_price + record.profit_hint

    margin = _margin_pct(price, record.wholesale_price)
    risks = compliance.product_risks(record)
    gates: List[str] = []
    reasons: List[str] = []

    # G1 — margin. A 1,000 IQD hint is a floor filler, not a margin.
    if record.profit_hint == TRAP_PROFIT_HINT:
        gates.append(GATE_MARGIN)
        reasons.append("profit hint is the %d IQD floor filler" % TRAP_PROFIT_HINT)
    elif margin is None:
        gates.append(GATE_MARGIN)
        reasons.append("no price or wholesale, margin unknown")
    elif margin < MIN_MARGIN_PCT:
        gates.append(GATE_MARGIN)
        reasons.append("margin %.0f%% is below %.0f%%" % (margin, MIN_MARGIN_PCT))

    # G2 — stock. A band starting at 0 can empty while the post is live.
    if compliance.stock_floor(record.stock_band) < 10:
        gates.append(GATE_STOCK)
        reasons.append("stock band %r is near empty" % (record.stock_band or "unknown"))

    # G3 — platform policy on the product itself.
    blocking = [r for r in risks if r in _BLOCKING_PRODUCT_RISKS]
    if blocking:
        gates.append(GATE_COMPLIANCE)
        reasons.append("platform-restricted class: %s" % ", ".join(blocking))

    # G4 — shipping and Iraqi import rules.
    logistics = [r for r in risks if r in _LOGISTICS_RISKS]
    if logistics:
        gates.append(GATE_LOGISTICS)
        reasons.append("shipping or import class: %s" % ", ".join(logistics))

    # G5 — enough media to build a post.
    if len(record.video_urls) < 1 and len(record.image_urls) < 3:
        gates.append(GATE_MEDIA)
        reasons.append("needs 1 video or 3 images, has %d video and %d image"
                       % (len(record.video_urls), len(record.image_urls)))

    if gates:
        return ProductScore(sku=record.sku, tier=TIER_REJECTED, margin_pct=margin,
                            price=price, gates_failed=gates, reasons=reasons, risks=risks)

    # -- tier the survivors ---------------------------------------------------
    if price and price > TIER_C_PRICE_IQD:
        tier = TIER_C
    elif (margin is not None and margin >= TIER_A_MARGIN_PCT
          and compliance.stock_floor(record.stock_band) >= TIER_A_STOCK_FLOOR):
        tier = TIER_A
    else:
        tier = TIER_B
    return ProductScore(sku=record.sku, tier=tier, margin_pct=margin, price=price,
                        risks=risks)


def score_caption(caption: str) -> List[str]:
    """
    Screen an assembled caption for wording that removes the post.

    Pre : caption is the final text. Post: [] means the caption may ship. A
          non-empty list names every banned term, so the writer sees the fix.
    Invariant: this runs on the caption, not the product, because a compliant
          product plus the wrong wording is still a removal (research 2026-09-22).
    """
    return compliance.banned_terms_in_caption(caption)
