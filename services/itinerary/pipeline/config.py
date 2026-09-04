"""
services/itinerary/pipeline/config.py

Settings for the vendored Bil Weekend itinerary pipeline.

Replaces the standalone app's `config.py`. Only the values the generation path
actually reads are here — the web GUI's session password and sync PIN are not
vendored, because nothing in this package serves a web GUI.

Paths point at odysseus: the day-template catalogue is owned by
`services.offers`, which is what syncs it from the Google Sheet, and everything
written at runtime goes under DATA_DIR like every other persisted path in this
repository.

No credential is stored here. `CREDENTIALS_FILE` names a location; the service
account key itself is never committed.
"""
from __future__ import annotations

import os

from src.constants import DATA_DIR

from services.offers.catalogue import TEMPLATES_DIR as _CATALOGUE_TEMPLATES_DIR

_HERE = os.path.dirname(os.path.abspath(__file__))
_CATALOGUE_DIR = os.path.dirname(_CATALOGUE_TEMPLATES_DIR)

# ── Data the pipeline reads ───────────────────────────────────────────────────
# One home for the catalogue. services.offers syncs it and measures against it;
# this package renders from it. A second copy would drift.
TEMPLATES_DIR = _CATALOGUE_TEMPLATES_DIR
PRICING_DIR = os.path.join(_CATALOGUE_DIR, "pricing")
GENERAL_INFO_FILE = os.path.join(_CATALOGUE_DIR, "general_info.json")
NEW_HOTELS_FILE = os.path.join(PRICING_DIR, "new_hotels.json")

# ── Data the pipeline writes ──────────────────────────────────────────────────
LOGS_DIR = os.path.join(DATA_DIR, "itinerary_logs")
QUOTE_LOG_FILE = os.path.join(LOGS_DIR, "quote_log.jsonl")
LOGO_DRIVE_CACHE = os.path.join(DATA_DIR, "itinerary_logo_drive_id.txt")

# ── Google ────────────────────────────────────────────────────────────────────
CREDENTIALS_FILE = os.environ.get(
    "BILWEEKEND_GOOGLE_CREDENTIALS",
    os.path.join(DATA_DIR, "bilweekend_service_account.json"),
)
GOOGLE_DRIVE_FOLDER_ID = os.environ.get(
    "BILWEEKEND_DRIVE_FOLDER_ID", "1ypSCzBqMOXg_wVfDO8GXawHZwTwLcEx5"
)

# Google Sheets databases. Identifiers, not secrets — access is governed by the
# service account, not by knowing the id.
JSON_DB_SHEET_ID = "1EiNUPoI3526-3Coxkjno_CesVc4UT2LhO8RebUKwn4w"
PRICING_DB_SHEET_ID = JSON_DB_SHEET_ID
OPS_SHEET_ID = "1Qwa8XIEsgMiaTKWBRCJLYLneuzpZ6CtLt6xG6Zfqtu8"

JSON_DB_TABS = {
    "general_info": "general_info",
    "templates": "templates",
}
PRICING_DB_TABS = {
    "settings": "settings",
    "entry_tickets": "entry_tickets",
    "new_hotels": "New_Hotels",
    "transport": "transport",
    "guides": "guides",
    "extras": "extras",
}

# ── Pricing defaults ──────────────────────────────────────────────────────────
DEFAULT_HOTEL_TIER = "3star"
DEFAULT_VEHICLE = "SMALL_CAR"
DEFAULT_MARKUP_PCT = 10.0
DEFAULT_FOOD_TIER = None
DEFAULT_GROUP_SIZES = [(15, 17), (18, 20), (21, 22)]
DEFAULT_FOC_PER_GROUP = 1

# ── Document formatting ───────────────────────────────────────────────────────
COMPANY_NAME = "Bil Weekend"
PRICE_VALIDITY = "2025-2026 Season, not valid after May 2026"
BANK_TRANSFER_SURCHARGE_PCT = 5
LOGO_PNG_PATH = os.path.join(_HERE, "assets", "BilWeekendLogo.png")

# ── Data source mode ──────────────────────────────────────────────────────────
# The vendored catalogue is committed, so local is the default and a sync is an
# explicit act rather than a startup side effect.
DATA_SOURCE_MODE = os.environ.get("DATA_SOURCE_MODE", "local_only")
AUTO_SYNC_ON_START = False
