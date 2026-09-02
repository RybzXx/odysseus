"""
services/itinerary/binder.py

Binds matched route days to live DayTemplate codes from the Bil Weekend database.
Includes fixes for B18 (activity region vs city region) and B19 (transit connector preservation).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

from services.itinerary.models import RouteRecord
from services.itinerary.matcher import CITY_REGION_MAP


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\b[a-zA-Z0-9]{3,}\b", (text or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _normalize_city_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"^(city of|overnight in|night in)\s+", "", s)
    aliases = {
        "bagdad": "baghdad",
        "arbil": "erbil",
        "hewler": "erbil",
        "suleymaniyah": "sulaymaniyah",
        "sulaimani": "sulaymaniyah",
        "sulaymaniya": "sulaymaniyah",
        "basrah": "basra",
        "an-najaf": "najaf",
        "al-najaf": "najaf",
        "al-basra": "basra",
        "al-kufa": "kufa",
        "an-nasiriyah": "nasiriyah",
        "nasiriya": "nasiriyah",
        "al-chibayish": "chibayish",
        "chibaish": "chibayish",
        "ahwar": "marshes",
        "marshlands": "marshes",
    }
    return aliases.get(s, s)


def _city_region(city_name: str, template_region: Optional[str] = None) -> str:
    c_norm = _normalize_city_name(city_name)
    if c_norm in CITY_REGION_MAP:
        return CITY_REGION_MAP[c_norm]
    if template_region and template_region.strip():
        return template_region.strip()
    return "Central Iraq"


def _index_templates(templates: dict[str, Any]) -> dict[str, list[str]]:
    idx = defaultdict(list)
    for code, tmpl in templates.items():
        if getattr(tmpl, "active", True):
            city = getattr(tmpl, "overnight_city", "") or getattr(tmpl, "city", "")
            if city:
                idx[_normalize_city_name(city)].append(code)
    return idx


def _best_template_by_text(day_text: str, candidate_codes: list[str], templates: dict[str, Any]) -> tuple[Optional[str], float]:
    if not candidate_codes:
        return None, 0.0
    day_toks = _tokens(day_text)
    best_code: Optional[str] = None
    best_sim = -1.0

    for code in candidate_codes:
        tmpl = templates.get(code)
        if not tmpl:
            continue
        tmpl_text = getattr(tmpl, "full_text", "") or getattr(tmpl, "description", "") or getattr(tmpl, "name", "")
        sim = _jaccard(day_toks, _tokens(tmpl_text))
        if sim > best_sim:
            best_code = code
            best_sim = sim

    return best_code, max(best_sim, 0.0)


def bind_route_to_templates(
    route: RouteRecord,
    templates: dict[str, Any],
    requested_regions: Optional[list[str]] = None,
) -> tuple[list[str], list[str]]:
    req_regions = {r.strip() for r in (requested_regions or []) if r.strip()}
    is_multi_region_non_contiguous = (
        "Northern Iraq" in req_regions
        and "Southern Iraq" in req_regions
        and "Central Iraq" not in req_regions
    )
    force_erbil_departure = "Northern Iraq" in req_regions

    overnight_idx = _index_templates(templates)
    bound_codes: list[str] = []
    gap_notes: list[str] = []

    last_day_idx = len(route.days) - 1

    for i, rd in enumerate(route.days):
        oc = _normalize_city_name(rd.overnight_city)

        if oc:
            candidates = overnight_idx.get(oc, [])
            if candidates:
                best_code, _ = _best_template_by_text(rd.text, candidates, templates)
                if best_code:
                    tmpl = templates[best_code]
                    city_reg = _city_region(oc, getattr(tmpl, "region", ""))

                    if not req_regions or city_reg in req_regions:
                        bound_codes.append(best_code)
                    elif is_multi_region_non_contiguous and city_reg == "Central Iraq":
                        bound_codes.append(best_code)
                        gap_notes.append(
                            f"Day {rd.day} ({rd.overnight_city}): Retained as required Central Iraq transit connector."
                        )
                    else:
                        gap_notes.append(
                            f"Day {rd.day}: Overnight in '{rd.overnight_city}' ({city_reg}) outside requested region(s); omitted."
                        )
            else:
                gap_notes.append(f"Day {rd.day}: No active template found for overnight city '{rd.overnight_city}'.")
            continue

        if i == last_day_idx and force_erbil_departure:
            erbil_departures = [
                code for code, t in templates.items()
                if getattr(t, "active", True)
                and not getattr(t, "overnight_city", "")
                and "erbil" in _normalize_city_name(getattr(t, "city", ""))
            ]
            best_code, _ = _best_template_by_text(rd.text, erbil_departures, templates)
            if best_code:
                bound_codes.append(best_code)
            else:
                gap_notes.append(
                    f"Day {rd.day}: Kurdistan departure should be from Erbil; fallback needed."
                )
            continue

        day_toks = _tokens(rd.text)
        no_overnight_candidates = [
            code for code, t in templates.items()
            if getattr(t, "active", True)
            and not getattr(t, "overnight_city", "")
            and _tokens(getattr(t, "city", "") or "") & day_toks
        ]
        best_code, sim = _best_template_by_text(rd.text, no_overnight_candidates, templates)
        if best_code and sim >= 0.05:
            tmpl = templates[best_code]
            city_reg = _city_region(getattr(tmpl, "city", ""), getattr(tmpl, "region", ""))
            if not req_regions or city_reg in req_regions:
                bound_codes.append(best_code)
            else:
                gap_notes.append(f"Day {rd.day}: Day trip in '{city_reg}' outside requested region(s); omitted.")
        else:
            gap_notes.append(f"Day {rd.day}: Day trip / departure has no confident template match.")

    return bound_codes, gap_notes
