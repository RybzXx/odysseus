"""
BilWeekend — Builder
Resolves day codes into an ordered list of BuiltDay objects with day numbers,
night numbers, and dates assigned.
"""
from datetime import date, timedelta
from typing import Optional
from services.itinerary.pipeline.models import BuiltDay, TourRequest, DayTemplate


def build_itinerary(request: TourRequest, templates: dict) -> list:
    """
    Returns an ordered list of BuiltDay objects.
    Days with overnight_city get a night number; day-trips / departures do not.
    """
    built = []
    night_counter = 0
    current_date = request.start_date  # None if no dates

    for i, code in enumerate(request.day_codes):
        tmpl = templates[code]
        day_number = i + 1

        has_overnight = bool(tmpl.overnight_city)
        if has_overnight:
            night_counter += 1
            night_number = night_counter
        else:
            night_number = None

        day_date = current_date
        if current_date is not None:
            current_date = current_date + timedelta(days=1)

        built.append(BuiltDay(
            day_number=day_number,
            night_number=night_number,
            date=day_date,
            template=tmpl,
        ))

    return built


def format_day_header(built_day: BuiltDay) -> str:
    """
    Returns the bold day header string, e.g.:
      "Day 1"                        (no date)
      "Day 1 — Monday, 12 May"       (with date)
    """
    header = f"Day {built_day.day_number}"
    if built_day.date is not None:
        weekday = built_day.date.strftime("%A")
        day_num = built_day.date.strftime("%d").lstrip("0")
        month   = built_day.date.strftime("%B")
        header += f" \u2014 {weekday}, {day_num} {month}"
    return header


def format_overnight_line(built_day: BuiltDay) -> Optional[str]:
    """
    Returns the overnight line, e.g. "Overnight: Baghdad / night 3."
    Returns None if there is no overnight.
    """
    if not built_day.template.overnight_city or built_day.night_number is None:
        return None
    return f"Overnight: {built_day.template.overnight_city} / night {built_day.night_number}."


def count_guide_days(built_days: list) -> int:
    return sum(1 for d in built_days if "guide_day" in d.template.pricing_tags)


def count_transport_days(built_days: list) -> int:
    return sum(1 for d in built_days if "transport_day" in d.template.pricing_tags)


def count_hotel_nights_by_city(built_days: list) -> dict:
    """Returns {city: nights_count}."""
    nights = {}
    for d in built_days:
        if "hotel_night" in d.template.pricing_tags and d.template.overnight_city:
            city = d.template.overnight_city
            nights[city] = nights.get(city, 0) + 1
    return nights


def collect_all_sites(built_days: list) -> list:
    """Returns flat list of all included_sites across all days (with duplicates)."""
    sites = []
    for d in built_days:
        sites.extend(d.template.included_sites)
    return sites
