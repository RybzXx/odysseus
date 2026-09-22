"""
layer2.ranking — Gemini orders the products that already passed Layer One.

Code filters first (content.scoring: margin, stock, compliance, logistics,
media). Only survivors reach this module, so Gemini decides posting order and
never whether a product is allowed. The check below makes that structural: the
answer must name exactly the SKUs it was given, each once, ranked 1..n.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from mahdawi.layer2 import settings, voice
from mahdawi.layer2.gateway import Gateway


_TOKENS_PER_ENTRY = 60     # headroom over the ~40 an entry uses


@dataclass
class Candidate:
    """One product that passed the Layer One gates, as the judge sees it."""
    sku: str
    title: Optional[str]
    category: Optional[str]
    tier: str                      # the rubric tier, A/B/C
    margin_pct: Optional[float]
    price: Optional[int]
    market_note: Optional[str]


@dataclass
class Ranked:
    sku: str
    rank: int                      # 1 = post first
    reason: str


_TASK = """\
Rank the products in FACTS for posting on an Iraqi Instagram and TikTok shop.
Rank 1 is the product to post first. Weigh Iraqi demand and season from each
market note, then the rubric tier (A is strongest) and the margin. Every product
has already passed the shop's rules; your only job is the order.
Answer with JSON only: a list with one object per product,
[{"sku": "<sku>", "rank": <1..n>, "reason": "<one short sentence in Iraqi Arabic>"}]
Use every sku exactly once and no other sku.
"""


def check_ranking(data: Any, skus: List[str]) -> Optional[str]:
    """
    Pre : skus is the candidate list sent to the judge.
    Post: None only when data ranks exactly those skus, each once, as 1..n,
          and every entry carries a reason.
    """
    if not isinstance(data, list):
        return "ranking is not a list"
    got = [d.get("sku") for d in data if isinstance(d, dict)]
    if len(got) != len(data):
        return "ranking entry is not an object"
    if sorted(got) != sorted(skus):
        return "ranking skus differ from the candidates"
    ranks = [d.get("rank") for d in data]
    if any(isinstance(r, bool) or not isinstance(r, int) for r in ranks):
        return "rank is not an integer"
    if sorted(ranks) != list(range(1, len(skus) + 1)):
        return "ranks are not 1..%d" % len(skus)
    if any(not isinstance(d.get("reason"), str) or not d["reason"].strip() for d in data):
        return "a ranking entry has no reason"
    return None


def rank(gateway: Gateway, candidates: List[Candidate]) -> List[Ranked]:
    """
    Post: one Ranked per candidate, sorted by rank. [] for no candidates,
          with no gateway call.
    Raises: Layer2Failure — the ranking step waits; the drafts stay as they are.
    """
    if not candidates:
        return []
    skus = [c.sku for c in candidates]
    facts = {"products": [c.__dict__ for c in candidates]}
    # The answer holds one {sku, rank, Arabic reason} entry per product, about
    # 40 tokens each. A fixed budget truncates the JSON on a large catalog, and
    # a truncated answer can never pass check_ranking.
    budget = max(settings.MAX_TOKENS, _TOKENS_PER_ENTRY * len(candidates) + 256)
    data = gateway.complete_json(settings.MODEL_JUDGE, voice.messages(_TASK, facts),
                                 lambda d: check_ranking(d, skus), max_tokens=budget)
    out = [Ranked(sku=d["sku"], rank=d["rank"], reason=d["reason"].strip()) for d in data]
    return sorted(out, key=lambda r: r.rank)
