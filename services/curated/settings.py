"""
curated — Configuration constants.

All environment- and policy-specific values live here so behaviour can be
changed without touching logic. Spec OPEN-A/B/E defaults are applied here and
are trivially overridable.
"""
import os

# ── Requests sheet (spec OPEN-F / §1.3) ───────────────────────────────────────
REQUESTS_SHEET_ID = "1BMS6ij7qtvn_XdIDGRBEbGzYJx2UdZVkrrxIZPxky7s"
REQUESTS_TAB = "main"

# Live operator parameters (B1 = exchange rate, IQD per 1 USD).
PARAMETERS_TAB = "parameters"
EXCHANGE_RATE_CELL = "B1"

# Columns A:AM (1..39) are reserved for the customize app's own data and are
# read-only context. The project writes output strictly to AN onward.
OUTPUT_FIRST_COL = "AN"
# Output column order, starting at OUTPUT_FIRST_COL:
OUTPUT_COLUMNS = ["status", "doc_link", "matched_route", "confidence", "notes", "processed_at"]

# ── Poll loop (§8.1) ──────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.environ.get("CURATED_POLL_SECONDS", "300"))

# ── Status state machine (§8.2) ───────────────────────────────────────────────
STATUS_NEW = ""          # empty AN cell == not yet processed
STATUS_GENERATING = "generating"
STATUS_DONE = "done"
STATUS_ERROR = "error"

# ── Input value maps (§2.2) ───────────────────────────────────────────────────
# OPEN-A (proposed default): transportation -> vehicle_code
TRANSPORT_TO_VEHICLE = {
    "sedan": "SMALL_CAR",
    "suv": "LARGE_CAR",
    "bus": "TOYOTA_COASTER",
}
HOTEL_TO_TIER = {
    "3_star": "3star",
    "4_star": "4star",
    "5_star": "5star",
}

# OPEN-B (proposed default): resolve a day range "A-B" to its minimum.
DAY_RANGE_RESOLUTION = "min"   # "min" | "max"

# pax < this -> individual flow (spec §2.2 / D4). pax >= this is flagged for
# manual group sizing in v1 (§2.2 note); generation still runs as individual.
GROUP_PAX_THRESHOLD = 10

# ── Scorer (§4.2, OPEN-E proposed defaults; themes removed per decision D) ─────
SCORER_WEIGHTS = {"region": 0.5, "day_count": 0.35, "tour_type": 0.15}
MATCH_MIN_SCORE = 0.30          # below this -> "no strong match" note (§4.3)

# The customize app exposes 4 region choices (UX-oriented); the live templates
# sheet (col D) only models 3 ("Northern Iraq" / "Central Iraq" / "Southern
# Iraq"). Kurdistan and the West/Nineveh area both fall under "Northern Iraq"
# operationally — they were split in the app for distinct cultural framing,
# not because the template DB tracks them separately (B16/B17). Mapping here
# makes a request's regions directly comparable to RouteRecord.region_set and
# DayTemplate.region.
REGION_NAME_MAP = {
    "iraqi kurdistan": "Northern Iraq",
    "western iraq & nineveh plains": "Northern Iraq",
    "central iraq & middle euphrates": "Central Iraq",
    "southern iraq": "Southern Iraq",
}

# ── Binder (§5) ───────────────────────────────────────────────────────────────
# Overnight-city matches always bind (city is a strong signal); text overlap only
# ranks among same-city codes. This floor applies ONLY to the weaker no-overnight
# day-trip fallback, to avoid binding an unrelated day-trip code (B10/B11).
DAYTRIP_MIN_SIMILARITY = 0.12

# ── Exchange rate (settings.json has null; see §2.6) ──────────────────────────
# IQD per 1 USD. Used only to convert IQD-priced entry tickets.
# NEEDS USER VERIFICATION — pricing accuracy depends on it.
EXCHANGE_RATE_FALLBACK = 1320.0

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
# The route corpus this repository already vendors, beside the pipeline that
# reads it. The standalone project kept its own copy under curated/data; two
# copies of the same corpus would drift, and this repository holds one.
ROUTES_FILE = os.path.normpath(
    os.path.join(HERE, "..", "itinerary", "data", "routes.json"))
# Only extract_offers.py (the offline corpus rebuild) needs this; the live
# runner only reads the already-built ROUTES_FILE. The original offers folder
# no longer exists anywhere, so there is no default: set BILWEEKEND_OFFERS_DIR
# to rebuild the corpus. None makes extract_offers fail fast with instructions.
OFFERS_DIR = os.environ.get("BILWEEKEND_OFFERS_DIR")
# Runner log directory (project root /logs, gitignored).
LOG_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "data", "logs"))
