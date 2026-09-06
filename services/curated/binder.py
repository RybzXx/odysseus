"""
curated.binder — Bind a matched route to live day-codes (§5, design C2).

For each route day, pick the active template whose overnight city matches and
whose text best overlaps the day's prose. Unmatched days become gap notes and
are omitted, so a route still generates from its covered legs even at 70-80%
code coverage (§5.2, U4).
"""
from collections import defaultdict

from services.curated import settings
from services.curated.models import RouteRecord
from services.itinerary.pipeline.loader import _normalize_city_name as normalize_city
from services.curated.text_match import jaccard, tokens


def _index_by_overnight(templates: dict) -> dict:
    """{normalized_overnight_city: [codes]} for active templates only."""
    idx = defaultdict(list)
    for code, tmpl in templates.items():
        if tmpl.active and tmpl.overnight_city:
            idx[normalize_city(tmpl.overnight_city)].append(code)
    return idx


def _best_by_overlap(rd_text: str, codes: list, templates: dict) -> tuple:
    """(best_code, best_sim) ranking codes by text overlap. (None, 0.0) if empty."""
    rd_tokens = tokens(rd_text)
    best_code, best_sim = None, -1.0
    for code in codes:
        sim = jaccard(rd_tokens, tokens(templates[code].full_text))
        if sim > best_sim:
            best_code, best_sim = code, sim
    return best_code, max(best_sim, 0.0)


def bind_route(route: RouteRecord, templates: dict, requested_regions: set = None) -> tuple:
    """
    Return (day_codes, gap_notes).

    Pre: templates is {code: DayTemplate} from the live database.
         requested_regions, if given, is already mapped to template-DB region
         names (settings.REGION_NAME_MAP applied by the caller).
    Post: every code in day_codes is an active template AND, when
          requested_regions is non-empty, in one of those regions (B17 — a
          matched route may legitimately span extra regions the customer never
          asked for; those days are dropped rather than silently shipped). When
          requested_regions includes Kurdistan/Northern Iraq, the route's final
          (no-overnight, departure) day is always bound to an Erbil departure
          code if one exists — once a trip reaches the north, the customer
          departs from Erbil rather than backtracking to Baghdad. A day
          otherwise contributes a gap_note only when its overnight city has no
          template (genuine coverage gap) or a no-overnight day has no
          confident day-trip match.
    Invariant: order of day_codes follows route day order.
    """
    overnight_idx = _index_by_overnight(templates)
    req_regions = {r.strip().lower() for r in (requested_regions or set()) if r.strip()}
    force_erbil_departure = "northern iraq" in req_regions
    day_codes, gaps = [], []

    def _in_scope(code) -> bool:
        if not req_regions:
            return True
        return (templates[code].region or "").strip().lower() in req_regions

    last_day_index = len(route.days) - 1
    for i, rd in enumerate(route.days):
        oc = normalize_city(rd.overnight_city)

        if oc:
            candidates = overnight_idx.get(oc, [])
            if candidates:
                # Overnight city is a strong signal: always bind. Text overlap
                # only picks WHICH same-city code, never rejects the day (B11).
                best_code, _ = _best_by_overlap(rd.text, candidates, templates)
                if _in_scope(best_code):
                    day_codes.append(best_code)
                else:
                    gaps.append(f"Day {rd.day}: overnight in '{rd.overnight_city}' "
                                f"({templates[best_code].region}) is outside the "
                                f"requested region(s); day dropped (B17).")
            else:
                gaps.append(f"Day {rd.day}: no day-code exists for overnight city "
                            f"'{rd.overnight_city}' yet.")
            continue

        # Final no-overnight day on a Kurdistan-bound trip: depart from Erbil,
        # not wherever the historic route's own text happens to head back to
        # (often Baghdad) — overrides the normal city-token match below.
        if i == last_day_index and force_erbil_departure:
            erbil_candidates = [code for code, t in templates.items()
                                 if t.active and not t.overnight_city and "erbil" in tokens(t.city)]
            best_code, _ = _best_by_overlap(rd.text, erbil_candidates, templates)
            if best_code:
                day_codes.append(best_code)
            else:
                gaps.append(f"Day {rd.day}: requested region includes Kurdistan — "
                            "departure should be from Erbil, but no Erbil departure "
                            "day-code exists yet; needs manual override.")
            continue

        # No overnight (day-trip / departure): weaker city-token signal, so keep
        # a similarity floor and restrict to genuine no-overnight templates (B10).
        day_tokens = tokens(rd.text)
        candidates = [code for code, t in templates.items()
                      if t.active and not t.overnight_city and tokens(t.city) & day_tokens]
        best_code, best_sim = _best_by_overlap(rd.text, candidates, templates)
        if best_code and best_sim >= settings.DAYTRIP_MIN_SIMILARITY:
            if _in_scope(best_code):
                day_codes.append(best_code)
            else:
                gaps.append(f"Day {rd.day}: day trip in '{templates[best_code].region}' "
                            f"is outside the requested region(s); day dropped (B17).")
        else:
            gaps.append(f"Day {rd.day}: day trip / no overnight — no confident "
                        f"day-code match (best {best_sim:.2f}).")

    return day_codes, gaps
