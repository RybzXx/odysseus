"""
curated.routes — Load the extracted route corpus and derive regions (§3, C2).

Region per route is derived at load time from the live templates' city->region
mapping, so routes stay consistent with the database as cities/codes change.
"""
import json

from services.curated import settings
from services.curated.models import RouteDay, RouteRecord
from services.itinerary.pipeline.loader import _normalize_city_name as normalize_city


def build_city_region_map(templates: dict) -> dict:
    """{normalized_city: region} from every template's city and overnight_city."""
    city_region = {}
    for tmpl in templates.values():
        for city in (tmpl.city, tmpl.overnight_city):
            c = normalize_city(city)
            if c and tmpl.region:
                city_region.setdefault(c, tmpl.region)
    return city_region


def load_routes(templates: dict, routes_file: str = None) -> list:
    """
    Load route records and attach region_set derived from templates.

    Pre: routes_file exists (run curated.extract_offers first).
    Post: every returned RouteRecord has day_count >= 1.
    """
    routes_file = routes_file or settings.ROUTES_FILE
    with open(routes_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    city_region = build_city_region_map(templates)
    routes = []
    for r in payload.get("routes", []):
        days = [RouteDay(day=d["day"], overnight_city=d["overnight_city"], text=d["text"])
                for d in r.get("days", [])]
        region_set = {city_region[c] for c in r.get("city_sequence", []) if c in city_region}
        routes.append(RouteRecord(
            id=r["id"],
            source_file=r["source_file"],
            day_count=r["day_count"],
            tour_type=r.get("tour_type", "individual"),
            city_sequence=r.get("city_sequence", []),
            themes=r.get("themes", []),
            days=days,
            region_set=region_set,
        ))
    return routes
