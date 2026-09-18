"""Read-only, versioned references from sent offers with explicit dispositions."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import threading

from services.itinerary.models import RouteDay, RouteRecord
from services.itinerary.places import normalize_place
from services.itinerary.resolved_plan import content_hash

_cache = None
_lock = threading.RLock()


def load_reference_pool(force_reload=False):
    """Return all record dispositions and deduplicated usable route references.

    Pre: the sent corpus is local. Post: every record has a disposition.
    Malformed records never fall back to an unrelated legacy route silently.
    """
    from services.offers import offer_store
    from services.itinerary.matcher import activity_regions, activity_text
    from services.itinerary.day_facts import source_day_facts
    global _cache
    stamp = offer_store.corpus_fingerprint()
    key = (offer_store.OFFER_CORPUS_DIR, stamp["fingerprint"])
    with _lock:
        if _cache and _cache[0] == key and not force_reload:
            return _cache[1]
        records, unique = [], {}
        for path in sorted(Path(offer_store.OFFER_CORPUS_DIR).glob("*/offer.json")):
            reference = {"record": path.parent.name}
            reasons = []
            status = "usable"
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                reference.update(message_id=raw["message_id"], attachment_name=raw.get("attachment_name", ""),
                                 sent_at=raw.get("sent_at"), content_version=content_hash(raw))
                if not raw.get("sent_at"):
                    reasons.append("The reference has no sent date.")
                else:
                    datetime.fromisoformat(raw["sent_at"])
                days = [RouteDay(int(d["day"]), str(d.get("overnight_city") or ""),
                                 activity_text(str(d.get("text") or ""))) for d in raw["days"]]
                if not days:
                    status = "rejected"
                    reasons.append("The record contains no itinerary days.")
                elif [d.day for d in days] != list(range(1, len(days) + 1)):
                    reasons.append("Day numbers are not contiguous from day 1.")
                for i, day in enumerate(days):
                    facts = source_day_facts(day, days[i - 1].overnight_city if i else "")
                    if facts["overnight_status"] == "unknown":
                        reasons.append(f"Day {day.day}: {facts['evidence']}.")
                    if day.overnight_city:
                        from services.itinerary.move_map import resolve_place, PLACES_WITHOUT_A_COORDINATE
                        city = normalize_place(day.overnight_city)
                        if city and not resolve_place(city) and city not in PLACES_WITHOUT_A_COORDINATE:
                            reasons.append(f"Day {day.day}: overnight place {city} is not established.")
                if reasons and status != "rejected":
                    status = "needs_review"
                if status == "usable":
                    signature = content_hash({"tour_type": raw.get("tour_type", "individual"),
                        "days": [[normalize_place(d.overnight_city),
                                  re.sub(r"\s+", " ", d.text).casefold().strip()] for d in days]})
                    if signature in unique:
                        unique[signature].references.append(reference)
                    else:
                        unique[signature] = RouteRecord(
                            id="sent:" + signature[:16], source_file=raw.get("attachment_name") or path.parent.name,
                            day_count=len(days), tour_type=raw.get("tour_type", "individual"),
                            city_sequence=[normalize_place(d.overnight_city) for d in days if d.overnight_city],
                            themes=[], days=days, region_set=activity_regions(days),
                            references=[reference], corpus_version=stamp["fingerprint"])
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                status = "rejected"
                reasons = [f"Unreadable offer record: {type(exc).__name__}."]
            records.append({"reference": reference, "status": status, "reasons": reasons})
        result = {"version": stamp["fingerprint"], "record_count": len(records),
                  "records": records, "routes": list(unique.values()),
                  "counts": {status: sum(r["status"] == status for r in records)
                             for status in ("usable", "needs_review", "rejected")}}
        _cache = (key, result)
        return result


def reference_pool_view():
    pool = load_reference_pool()
    return {key: value for key, value in pool.items() if key != "routes"} | {"route_count": len(pool["routes"])}
