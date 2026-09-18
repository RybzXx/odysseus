"""Read a historical day's role without treating missing text as evidence."""
from __future__ import annotations

import re

from services.itinerary.places import normalize_place, places_in


def source_day_facts(day, previous_city="") -> dict:
    """Separate known overnight stays from explicit departures and unknowns."""
    from services.itinerary.matcher import activity_text
    text = activity_text(day.text)
    overnight = normalize_place(day.overnight_city)
    facts = {"role": "unknown", "overnight_status": "unknown", "overnight_city": overnight,
             "start_city": normalize_place(previous_city), "end_city": "", "evidence": ""}
    if overnight:
        facts.update(role="city_day" if overnight == normalize_place(previous_city) else "transit",
                     overnight_status="present", end_city=overnight, evidence="source overnight field")
        return facts
    if day.overnight_city.strip():
        facts["evidence"] = "ambiguous source overnight field"
        return facts
    departure = re.search(
        r"\b(?:departure|departing|depart|fly out|flight home)\b|"
        r"\b(?:transfer|drive|head)\b[^.\n]{0,100}\bairport\b", text, re.I)
    if departure:
        # Read a named airport from its clause. A generic airport is not a city.
        airports = re.findall(r"[^.\n]{0,80}\bairport\b[^.\n]{0,30}", text, re.I)
        destinations = set().union(*(places_in(clause) for clause in airports)) if airports else set()
        facts.update(role="departure", overnight_status="none", evidence=departure.group(0))
        if len(destinations) == 1:
            facts["end_city"] = next(iter(destinations))
        return facts
    returning = re.search(r"\b(?:back|return(?:ing)?)\s+to\s+([^.,;\n]+)", text, re.I)
    if returning:
        cities = places_in(returning.group(1))
        if len(cities) == 1:
            city = next(iter(cities))
            facts.update(role="day_trip", overnight_status="none", start_city=city,
                         end_city=city, evidence=returning.group(0))
            return facts
    facts["evidence"] = "source does not establish a stay, return, or departure"
    return facts
