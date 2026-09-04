"""
BilWeekend — Validator
Validates a TourRequest before document generation.
Returns a list of error/warning strings. Empty list = all clear.
"""
from services.itinerary.pipeline.models import TourRequest


# Recognised site availability statuses (Column I in entry_tickets sheet)
_STATUS_CLOSED            = "Closed"
_STATUS_MAINT_CLOSED      = "Under Maintenance (Closed)"
_STATUS_CLOSED_ARR        = "Closed But Arrangeable"
_STATUS_MAINT_ARR         = "Under Maintenance But Arrangeable"
_STATUS_OPEN              = "Open"

_INACCESSIBLE_STATUSES   = {_STATUS_CLOSED, _STATUS_MAINT_CLOSED}
_ARRANGEABLE_STATUSES    = {_STATUS_CLOSED_ARR, _STATUS_MAINT_ARR}


def validate(request: TourRequest, templates: dict, pricing: dict,
             built_days: list = None) -> list:
    errors = []
    warnings = []

    # ── Day codes ────────────────────────────────────────────────────────────
    if not request.day_codes:
        errors.append("No day codes provided.")
    for code in request.day_codes:
        if code not in templates:
            errors.append(f"Unknown day code: '{code}'. Check data/templates/ for valid codes.")
        else:
            tmpl = templates[code]
            if not tmpl.active:
                errors.append(f"Day code '{code}' is retired/inactive. Use the replacement codes instead.")
            if tmpl.needs_review:
                warnings.append(f"Day code '{code}' ({tmpl.title}) is flagged for manual review: {tmpl.internal_notes}")
            if not tmpl.overnight_city and "hotel_night" in tmpl.pricing_tags:
                warnings.append(f"Day '{code}' has 'hotel_night' pricing tag but no overnight_city. Check template.")

    # ── Document name ────────────────────────────────────────────────────────
    if not request.doc_name or not request.doc_name.strip():
        errors.append("Document name is required.")

    # ── Start date ───────────────────────────────────────────────────────────
    if request.start_date is not None:
        from datetime import date
        if request.start_date < date.today():
            warnings.append(f"Start date {request.start_date} is in the past.")

    # ── Exchange rate ────────────────────────────────────────────────────────
    if not request.exchange_rate or request.exchange_rate <= 0:
        errors.append("Exchange rate must be set and greater than 0.")

    if request.tour_type == "individual":
        _validate_individual(request, templates, pricing, errors, warnings)
    elif request.tour_type == "group":
        _validate_group(request, templates, pricing, errors, warnings)
    else:
        errors.append(f"Unknown tour_type: '{request.tour_type}'. Must be 'individual' or 'group'.")

    # ── Pricing tag completeness ─────────────────────────────────────────────
    for code in request.day_codes:
        if code in templates:
            for site_code in templates[code].included_sites:
                if site_code not in pricing["_tickets_by_code"]:
                    warnings.append(
                        f"Site code '{site_code}' in day '{code}' not found in entry_tickets.json. "
                        "It will be skipped in pricing."
                    )

    # ── Availability warnings (grouped by category) ──────────────────────────
    _check_site_availability(request, templates, pricing, built_days, warnings)

    return [f"ERROR: {e}" for e in errors] + [f"WARNING: {w}" for w in warnings]


def _check_site_availability(request, templates, pricing, built_days, warnings):
    """
    Emit grouped availability warnings for sites based on:
      1. review_note (Column I) — status category
      2. closed_on  (Column J) — weekday conflict against itinerary dates
    """
    tickets = pricing["_tickets_by_code"]

    # Collect all site appearances: {site_code: [(day_code, day_number, date_obj), ...]}
    site_appearances = {}
    if built_days:
        for bd in built_days:
            for site_code in bd.template.included_sites:
                site_appearances.setdefault(site_code, []).append(
                    (bd.template.code, bd.day_number, bd.date)
                )
    else:
        for code in request.day_codes:
            if code in templates:
                for site_code in templates[code].included_sites:
                    site_appearances.setdefault(site_code, []).append((code, None, None))

    # ── 1. Status / review_note warnings ─────────────────────────────────────
    # Categorise sites by their review_note value
    status_buckets: dict[str, list] = {}
    for site_code, appearances in site_appearances.items():
        ticket = tickets.get(site_code)
        if not ticket:
            continue
        status = (ticket.get("review_note") or "").strip()
        if not status or status == _STATUS_OPEN:
            continue
        status_buckets.setdefault(status, []).append((site_code, ticket.get("site_name", site_code), appearances))

    if status_buckets:
        # Inaccessible statuses first, then arrangeable, then other
        ordered_statuses = (
            [s for s in status_buckets if s in _INACCESSIBLE_STATUSES] +
            [s for s in status_buckets if s in _ARRANGEABLE_STATUSES] +
            [s for s in status_buckets if s not in _INACCESSIBLE_STATUSES and s not in _ARRANGEABLE_STATUSES]
        )
        for status in ordered_statuses:
            sites = status_buckets[status]
            site_lines = []
            for site_code, site_name, appearances in sites:
                day_refs = ", ".join(
                    f"Day {num}" + (f" ({d.strftime('%A %d %b')})" if d else "")
                    for _, num, d in appearances
                    if num is not None
                ) if any(num for _, num, _ in appearances) else ""
                label = f"{site_name} [{site_code}]"
                if day_refs:
                    label += f" — {day_refs}"
                site_lines.append(label)
            sites_str = "; ".join(site_lines)
            if status in _INACCESSIBLE_STATUSES:
                qualifier = "NOT accessible"
            elif status in _ARRANGEABLE_STATUSES:
                qualifier = "accessible with extra effort/cost"
            else:
                qualifier = "flagged"
            warnings.append(
                f"[{status}] The following sites are {qualifier}: {sites_str}"
            )

    # ── 2. Weekday conflict warnings ──────────────────────────────────────────
    if not built_days:
        return  # Cannot check weekday conflicts without dated itinerary

    conflicts: list[str] = []
    for bd in built_days:
        if bd.date is None:
            continue
        day_weekday = bd.date.strftime("%A").upper()
        for site_code in bd.template.included_sites:
            ticket = tickets.get(site_code)
            if not ticket:
                continue
            closed_on = ticket.get("closed_on", [])
            if day_weekday in closed_on:
                site_name = ticket.get("site_name", site_code)
                conflicts.append(
                    f"{site_name} [{site_code}] on Day {bd.day_number} "
                    f"({bd.date.strftime('%A %d %b')}) — closed on {day_weekday.capitalize()}s"
                )

    if conflicts:
        conflicts_str = "; ".join(conflicts)
        warnings.append(
            f"[Day Conflict] The itinerary visits sites on their closed weekday: {conflicts_str}"
        )


def _validate_individual(request, templates, pricing, errors, warnings):
    if request.num_people < 1:
        errors.append("Number of people must be at least 1.")
    if request.single_rooms < 0 or request.double_rooms < 0:
        errors.append("Room counts cannot be negative.")
    if request.single_rooms + request.double_rooms * 2 < request.num_people:
        warnings.append(
            f"Room capacity ({request.single_rooms} single + {request.double_rooms} double = "
            f"{request.single_rooms + request.double_rooms * 2} beds) is less than "
            f"number of people ({request.num_people})."
        )
    if request.hotel_tier not in ("3star", "4star", "5star"):
        errors.append(f"Invalid hotel_tier '{request.hotel_tier}'. Must be '3star', '4star', or '5star'.")

    if request.selected_vehicle not in pricing["_transport_by_code"]:
        errors.append(f"Vehicle '{request.selected_vehicle}' not found in transport.json.")

    if request.include_food and request.food_tier not in (1, 2, 3):
        errors.append(f"Invalid food_tier '{request.food_tier}'. Must be 1, 2, or 3.")

    if request.markup_percent < 0:
        errors.append("Markup percent cannot be negative.")

    # Warn if nights have no hotel tier data
    hotel_tiers = pricing.get("hotel_tiers", {})
    overnight_cities = set()
    for code in request.day_codes:
        if code in templates and templates[code].overnight_city:
            overnight_cities.add(templates[code].overnight_city)
    for city in overnight_cities:
        if city not in hotel_tiers:
            warnings.append(
                f"City '{city}' has overnight stays but no hotel tier data in the New_Hotels pricing bundle. "
                "Accommodation cost will be $0 for that city."
            )


def _validate_group(request, templates, pricing, errors, warnings):
    if not request.group_sizes:
        errors.append("Group pricing requires at least one group size range.")
    for gs in request.group_sizes:
        if len(gs) != 2 or gs[0] > gs[1]:
            errors.append(f"Invalid group size range: {gs}. Must be (min, max).")
    if request.foc_per_group < 0:
        errors.append("FOC per group cannot be negative.")
    if request.group_vehicle not in pricing["_transport_by_code"]:
        warnings.append(
            f"Group vehicle '{request.group_vehicle}' not found in transport.json. "
            "Transport cost will use daily rate of 0."
        )
    if request.hotel_tier not in ("3star", "4star", "5star"):
        errors.append(f"Invalid hotel_tier '{request.hotel_tier}' for group pricing.")

