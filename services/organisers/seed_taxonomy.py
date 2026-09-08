"""The starting taxonomy, and the rule-driven classifier that applies it.

The seed used to exist twice in the router: once as a list of categories with
their sender/domain/keyword rules, and again as an if/elif chain testing a
narrower set of literals. The two could drift, and did -- the chain tested nine
tour keywords where the category declared thirteen.

Now the seed is data, in ``data/seed_taxonomy.json``, and classification runs
the same ``evaluate_rules`` that decides live membership. Adding a category is
an edit to that file; the studio then tunes it per user.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.organisers.match_detail import RuleMatch, evaluate_rules

SEED_PATH = Path(__file__).resolve().parent / "data" / "seed_taxonomy.json"


@lru_cache(maxsize=1)
def load_seed_taxonomy() -> Tuple[Dict[str, Any], ...]:
    """The seed categories, in the precedence the classifier applies.

    Post: a tuple ordered by each entry's ``order``, cached for the process.
          Immutable so a caller cannot reorder the shared copy.
    """
    entries = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return tuple(sorted(entries, key=lambda e: e.get("order", 0)))


def catch_all_slug() -> Optional[str]:
    """The category that claims what nothing else does, if the seed names one."""
    for entry in load_seed_taxonomy():
        if entry.get("catch_all"):
            return entry["slug"]
    return None


def classify(email: Dict[str, Any]) -> Tuple[str, str, RuleMatch]:
    """Place one email in the seed taxonomy.

    Pre:  email carries the keys the mail index produces.
    Post: (slug, reason, match) for the first category whose rules the email
          satisfies, in precedence order. When none do, the catch-all claims it
          with an empty match, so every email lands somewhere.
    Inv:  the rules consulted are the ones the category declares. There is no
          second copy of them to fall out of step.
    """
    for entry in load_seed_taxonomy():
        if entry.get("catch_all"):
            continue
        match = evaluate_rules(email, [], entry.get("rules") or {})
        if match.matched:
            return entry["slug"], entry.get("reason", ""), match

    for entry in load_seed_taxonomy():
        if entry.get("catch_all"):
            return entry["slug"], entry.get("reason", ""), RuleMatch()

    # A seed with no catch-all leaves the email unplaced rather than inventing
    # a category for it.
    return "", "", RuleMatch()


def seed_rules(slug: str) -> Dict[str, List[str]]:
    """The rules one seed category declares, or empty when it is not seeded."""
    for entry in load_seed_taxonomy():
        if entry["slug"] == slug:
            return entry.get("rules") or {}
    return {}
