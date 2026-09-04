"""
BilWeekend — Calendar Warning Engine

Loads local calendar event files and checks itinerary dates against
religious events, logistical disruption periods, and public holidays.

No live network access. All events are read from data/calendar_events/.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from models import TourRequest, BuiltDay

# ── Paths ─────────────────────────────────────────────────────────────────────
_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "calendar_events")
)

# ── Severity ordering (lower = more severe) ───────────────────────────────────
_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high":     1,
    "medium":   2,
    "low":      3,
}

# ── Category → human-readable group label ─────────────────────────────────────
_CATEGORY_LABELS: dict[str, str] = {
    "religious_shia_logistics":    "Critical Logistical Disruption",
    "religious_shia":              "Shia Religious Events",
    "religious_islamic":           "Islamic Events",
    "religious_islamic_logistics": "Ramadan / Eid Operational Changes",
    "public_holiday":              "Public Holidays",
}
_DEFAULT_LABEL = "Other Calendar Warnings"

# ── Category → display colour ─────────────────────────────────────────────────
_CATEGORY_COLORS: dict[str, str] = {
    "religious_shia_logistics":    "red",
    "religious_shia":              "amber",
    "religious_islamic":           "orange",
    "religious_islamic_logistics": "yellow",
    "public_holiday":              "blue",
}
_DEFAULT_COLOR = "slate"

# ── Severity → display colour (used as fallback / for high-sev overrides) ────
_SEVERITY_COLORS: dict[str, str] = {
    "critical": "red",
    "high":     "orange",
    "medium":   "amber",
    "low":      "blue",
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_json_file(path: str) -> Optional[list | dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _effective_color(category: str, severity: str) -> str:
    """Return the most visually appropriate colour for a warning group entry."""
    sev_color = _SEVERITY_COLORS.get(severity, _DEFAULT_COLOR)
    cat_color = _CATEGORY_COLORS.get(category, _DEFAULT_COLOR)
    # Escalate to severity colour when severity is critical/high
    if severity in ("critical", "high"):
        return sev_color
    return cat_color


# ─────────────────────────────────────────────────────────────────────────────
# Event loading
# ─────────────────────────────────────────────────────────────────────────────

def load_calendar_events(years: Optional[list[int]] = None) -> list[dict]:
    """
    Load all calendar events from data/calendar_events/ for the given years.

    Sources loaded (per year):
      1. calendar_events_YYYY.json  (merged — preferred)
         or religious_events_YYYY.json  (fallback)
      2. public_holidays_YYYY.json  (if calendar_events_YYYY doesn't exist)

    Plus (always):
      3. logistical_warning_ranges.json  (no year suffix; contains multi-year entries)
    """
    if not os.path.isdir(_DATA_DIR):
        return []

    all_events: list[dict] = []

    # ── 1. Logistical warning ranges (always loaded) ──────────────────────────
    lr_path = os.path.join(_DATA_DIR, "logistical_warning_ranges.json")
    lr_data = _load_json_file(lr_path)
    if lr_data and isinstance(lr_data, list):
        all_events.extend(lr_data)

    # ── 2. Determine which years to load ─────────────────────────────────────
    if years is None:
        # Auto-detect from filenames
        detected: set[int] = set()
        try:
            for fname in os.listdir(_DATA_DIR):
                for prefix in ("calendar_events_", "religious_events_", "public_holidays_"):
                    if fname.startswith(prefix) and fname.endswith(".json"):
                        try:
                            detected.add(int(fname[len(prefix):-5]))
                        except ValueError:
                            pass
        except OSError:
            pass
        years = sorted(detected) if detected else [date.today().year]

    # ── 3. Per-year files ─────────────────────────────────────────────────────
    for yr in years:
        merged_path = os.path.join(_DATA_DIR, f"calendar_events_{yr}.json")
        rel_path    = os.path.join(_DATA_DIR, f"religious_events_{yr}.json")
        hol_path    = os.path.join(_DATA_DIR, f"public_holidays_{yr}.json")

        merged = _load_json_file(merged_path)
        if merged and isinstance(merged, list):
            # Merged file already contains holidays; don't double-load
            all_events.extend(merged)
        else:
            # Fall back to individual source files
            rel = _load_json_file(rel_path)
            if rel and isinstance(rel, list):
                all_events.extend(rel)
            hol = _load_json_file(hol_path)
            if hol and isinstance(hol, list):
                all_events.extend(hol)

    return all_events


# ─────────────────────────────────────────────────────────────────────────────
# Matching logic
# ─────────────────────────────────────────────────────────────────────────────

def _event_date_range(event: dict) -> tuple[Optional[date], Optional[date]]:
    start = _parse_date(event.get("start_date") or event.get("date"))
    end   = _parse_date(event.get("end_date")   or event.get("date"))
    if start and not end:
        end = start
    if end and not start:
        start = end
    return start, end


def _city_matches(event: dict, day_city: str, overnight_city: str) -> bool:
    """
    Return True if the event affects the given day.

    Rules:
      location_scope == "iraq"         → always warn
      location_scope == "city_specific" → warn if event cities overlap
                                         with day_city or overnight_city.
                                         If city data is missing on either
                                         side, still warn.
    """
    scope = event.get("location_scope", "iraq")
    if scope != "city_specific":
        return True  # iraq-wide or unknown scope

    ev_cities = {c.lower().strip() for c in (event.get("cities") or []) if c}
    if not ev_cities:
        return True  # no city filter specified → warn for all

    day_cities = {c.lower().strip() for c in [day_city, overnight_city] if c}
    if not day_cities:
        return True  # no city info on the day → still warn (conservative)

    return bool(ev_cities & day_cities)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def check_itinerary(request, built_days: list) -> list[dict]:
    """
    Check itinerary against calendar events.

    Returns a list of structured warning dicts, sorted by severity then day_number.
    Each dict contains:
        type, category, severity, event_id, event_name, date, day_number,
        day_title, city, affected_city_match, affects, message, source
    """
    if not built_days:
        return []

    # Only process days that have a date
    dated_days = [bd for bd in built_days if bd.date is not None]
    if not dated_days:
        return []

    years = sorted({bd.date.year for bd in dated_days})
    events = load_calendar_events(years=years)
    if not events:
        return []

    raw_warnings: list[dict] = []

    for event in events:
        ev_start, ev_end = _event_date_range(event)
        if not ev_start:
            continue

        for bd in dated_days:
            if not (ev_start <= bd.date <= ev_end):
                continue

            day_city      = (bd.template.city          or "").strip()
            overnight_city = (bd.template.overnight_city or "").strip()

            if not _city_matches(event, day_city, overnight_city):
                continue

            display_city = overnight_city or day_city
            cat = event.get("category", "other")
            sev = event.get("severity", "medium")
            scope = event.get("location_scope", "iraq")
            ev_cities = event.get("cities") or []
            affected_city_match = (
                scope == "city_specific"
                and bool({c.lower() for c in ev_cities} &
                         {display_city.lower()} - {""})
                if ev_cities else False
            )

            raw_warnings.append({
                "type":                "calendar_event",
                "category":            cat,
                "severity":            sev,
                "event_id":            event.get("event_id", ""),
                "event_name":          event.get("name") or event.get("event_name", ""),
                "date":                bd.date.isoformat(),
                "day_number":          bd.day_number,
                "day_title":           bd.template.title if bd.template else "",
                "city":                display_city,
                "affected_city_match": affected_city_match,
                "affects":             list(event.get("affects") or []),
                "message":             event.get("warning_message") or event.get("notes") or "",
                "source":              event.get("source", "manual"),
            })

    # De-duplicate: same event_id + day_number combination
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for w in raw_warnings:
        key = (w["event_id"], w["day_number"])
        if key not in seen:
            seen.add(key)
            deduped.append(w)

    # Sort: severity first, then day_number
    deduped.sort(
        key=lambda w: (_SEVERITY_ORDER.get(w["severity"], 9), w["day_number"])
    )
    return deduped


def to_plain_strings(calendar_warnings: list[dict]) -> list[str]:
    """
    Convert structured calendar warnings to plain 'WARNING: ...' strings
    for CLI and validator output.
    """
    lines = []
    for w in calendar_warnings:
        sev    = w.get("severity", "medium").upper()
        name   = w.get("event_name", "Calendar event")
        day    = w.get("day_number", "?")
        dt     = w.get("date", "")
        city   = w.get("city", "")
        city_part = f", {city}" if city else ""
        lines.append(
            f"WARNING: [Calendar:{sev}] {name} — "
            f"Day {day} ({dt}{city_part})"
        )
    return lines


def group_for_web(calendar_warnings: list[dict]) -> list[dict]:
    """
    Group structured calendar warnings by category for web display.

    Returns a list of group dicts:
        {"label": str, "color": str, "entries": [str]}

    Compatible with the existing formatted_warnings template rendering.
    """
    groups: dict[str, dict] = {}

    for w in calendar_warnings:
        cat   = w.get("category", "other")
        sev   = w.get("severity", "medium")
        label = _CATEGORY_LABELS.get(cat, _DEFAULT_LABEL)
        color = _effective_color(cat, sev)

        day     = w.get("day_number", "?")
        dt      = w.get("date", "")
        city    = w.get("city", "")
        name    = w.get("event_name", "")
        affects = w.get("affects") or []
        msg     = w.get("message", "")

        city_part    = f" · {city}" if city else ""
        affects_part = (
            f" ({', '.join(affects[:3])}{'…' if len(affects) > 3 else ''})"
            if affects else ""
        )
        entry = f"Day {day} ({dt}{city_part}) — {name}{affects_part}"
        if msg:
            entry += f". {msg}"

        if label not in groups:
            groups[label] = {"label": label, "color": color, "entries": [], "severity": sev}
        else:
            # Escalate group colour if this entry is more severe
            existing_ord = _SEVERITY_ORDER.get(groups[label]["severity"], 9)
            new_ord      = _SEVERITY_ORDER.get(sev, 9)
            if new_ord < existing_ord:
                groups[label]["color"]    = color
                groups[label]["severity"] = sev

        groups[label]["entries"].append(entry)

    # Remove internal 'severity' key before returning
    result = []
    for g in groups.values():
        g.pop("severity", None)
        result.append(g)

    # Order: logistical disruption first, then religious, then public holidays
    order = list(_CATEGORY_LABELS.values()) + [_DEFAULT_LABEL]
    result.sort(key=lambda g: order.index(g["label"]) if g["label"] in order else 99)
    return result
