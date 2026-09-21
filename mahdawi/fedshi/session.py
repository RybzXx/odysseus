"""
fedshi.session — where the Fedshi login state lives.

The user performs the OTP login once in a headed browser. Playwright saves the
browser state (cookies) to a file. Later runs reuse it headlessly. Code never
sees the phone number or the OTP (spec 2.3).

This module only names the path and reports whether a state file exists. The
Playwright engine reads and writes the actual state.
"""
from __future__ import annotations

import os

# Git-ignored (see .gitignore). Holds cookies, so it is a secret, not a config.
# Under the Odysseus data dir by default, so the cookie file lives with other
# app state and never inside a client-served path. Override with FEDSHI_SESSION_DIR.
_DATA = os.environ.get("ODYSSEUS_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"))
SESSION_DIR = os.environ.get("FEDSHI_SESSION_DIR", os.path.join(_DATA, "mahdawi", "session"))
STATE_FILE = os.path.join(SESSION_DIR, "state.json")

LOGIN_URL = "https://web.fedshi.com/auth/login"
PRODUCT_URL = "https://web.fedshi.com/products/%s"
LISTING_URL = "https://web.fedshi.com/listing?%s"


def has_state() -> bool:
    """True when a saved session exists to reuse."""
    return os.path.isfile(STATE_FILE) and os.path.getsize(STATE_FILE) > 0


def ensure_dir() -> str:
    os.makedirs(SESSION_DIR, exist_ok=True)
    return SESSION_DIR


def listing_query(collection: str) -> str:
    """
    Map a friendly collection name to the Fedshi listing query string.

    "new" -> automatic-collection=new; "bestseller" -> automatic-collection=
    bestseller; anything else is passed through (e.g. "collection-id=411").
    """
    if collection in ("new", "bestseller"):
        return "automatic-collection=%s" % collection
    return collection
