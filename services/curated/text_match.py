"""
curated.text_match — Token-overlap similarity for route binding (§5.1).

Deterministic, dependency-free. Used to pick the day-code whose template text
best matches a route day's prose.
"""
import re

_STOPWORDS = {
    "the", "and", "for", "with", "will", "our", "your", "you", "are", "was",
    "from", "into", "out", "off", "this", "that", "then", "there", "here",
    "have", "has", "had", "can", "also", "after", "before", "such", "via",
    "tour", "day", "visit", "see", "drive", "head", "start", "lunch",
    "breakfast", "dinner", "overnight", "night", "morning",
}

_TOKEN_RE = re.compile(r"[a-z]{3,}")


def tokens(text: str) -> set:
    """Lowercased alpha tokens (len>=3) minus generic itinerary stopwords."""
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS}


def jaccard(a: set, b: set) -> float:
    """|a∩b| / |a∪b|. Returns 0.0 for two empty sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0
