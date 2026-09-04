"""
BilWeekend — Pricing Calculator
Calculates tour quotes (individual and group) from structured pricing data.
All prices in USD. IQD prices are converted using request.exchange_rate.
"""
import copy
from datetime import datetime
from services.itinerary.pipeline.models import TourRequest, Quote, QuoteLineItem, GroupPricingRow
from services.itinerary.pipeline.builder import (
    count_guide_days, count_transport_days,
    count_hotel_nights_by_city, collect_all_sites,
)


def _iqd_to_usd(amount: float, exchange_rate: float) -> float:
    if exchange_rate <= 0:
        raise ValueError("Exchange rate must be > 0")
    return amount / exchange_rate


def _hotel_night_cost(city: str, tier: str, single_rooms: int,
                      double_rooms: int, pricing: dict) -> float:
    """Returns total accommodation cost for one night in a city at the given tier."""
    hotel_tiers = pricing.get("hotel_tiers", {})
    if city not in hotel_tiers:
        return 0.0
    tier_data = hotel_tiers[city].get(tier, {})
    single_rate = tier_data.get("single", 0)
    double_rate = tier_data.get("double", 0)
    team_fee    = tier_data.get("team_fee", 0)
    return single_rooms * single_rate + double_rooms * double_rate + team_fee


def _hotel_team_fee_cost(city: str, tier: str, pricing: dict) -> float:
    """Returns only the per-night team fee for a city/tier (no room costs).
    Used when no_hotels_mode is active."""
    hotel_tiers = pricing.get("hotel_tiers", {})
    if city not in hotel_tiers:
        return 0.0
    return hotel_tiers[city].get(tier, {}).get("team_fee", 0.0)


def _effective_multiplier(request) -> float:
    """Combined markup multiplier from office + margin markups."""
    office_mult = (1 + request.office_markup_percent / 100) if request.apply_office_markup else 1.0
    margin_mult = (1 + request.margin_markup_percent / 100) if request.apply_margin_markup else 1.0
    return office_mult * margin_mult


def calculate_quote(request: TourRequest, built_days: list, pricing: dict) -> Quote:
    now = datetime.now().isoformat(timespec="seconds")
    num_days = len(built_days)
    num_nights = sum(1 for d in built_days if d.night_number is not None)

    if request.tour_type == "individual":
        return _calculate_individual(request, built_days, pricing, now, num_days, num_nights)
    else:
        return _calculate_group(request, built_days, pricing, now, num_days, num_nights)


# ── Individual / FIT Pricing ──────────────────────────────────────────────────

def _calculate_individual(request, built_days, pricing, now, num_days, num_nights):
    line_items = []
    settings = pricing["settings"]

    # 1. Entry tickets
    all_sites = collect_all_sites(built_days)
    tickets_by_code = pricing["_tickets_by_code"]
    for site_code in all_sites:
        ticket = tickets_by_code.get(site_code)
        if not ticket or not ticket.get("active", True):
            continue
        per_person = ticket.get("price_per_person", 0)
        flat = ticket.get("price_flat", 0)
        currency = ticket.get("currency", "USD")
        rate = request.exchange_rate

        total_pp = per_person * request.num_people
        if currency == "IQD":
            total_pp = _iqd_to_usd(total_pp, rate)
            flat = _iqd_to_usd(flat, rate)

        if total_pp > 0:
            line_items.append(QuoteLineItem(
                category="Entry Tickets",
                description=f"{ticket['site_name']} — ${per_person}/person",
                unit_price=per_person,
                quantity=request.num_people,
                total=round(total_pp, 2),
            ))
        if flat > 0:
            line_items.append(QuoteLineItem(
                category="Entry Tickets",
                description=f"{ticket['site_name']} — group fee",
                unit_price=flat,
                quantity=1,
                total=round(flat, 2),
            ))

    # 2. Guide
    guide_days = (request.guide_days_override
                  if request.guide_days_override is not None
                  else count_guide_days(built_days))
    guide_rate = settings.get("guide_daily_rate_usd", 80)
    if guide_days > 0:
        guide_cost = guide_days * guide_rate
        line_items.append(QuoteLineItem(
            category="Guide",
            description=f"Tour guide — {guide_days} day(s) × ${guide_rate}/day",
            unit_price=guide_rate,
            quantity=guide_days,
            total=round(guide_cost, 2),
        ))

    # 2b. Extra staff (guides, photographers, etc.)
    extra_staff_total = 0.0
    if request.extra_staff_enabled:
        staff_days = request.extra_staff_days if request.extra_staff_days is not None else guide_days or 1
        extra_staff_total = round(
            request.extra_staff_count * staff_days * request.extra_staff_daily_rate, 2
        )
        line_items.append(QuoteLineItem(
            category="Guide",
            description=(
                f"Additional guide/photographer — {staff_days} day(s) × "
                f"{request.extra_staff_count} person(s) × ${request.extra_staff_daily_rate:.0f}/day"
            ),
            unit_price=request.extra_staff_daily_rate,
            quantity=request.extra_staff_count * staff_days,
            total=extra_staff_total,
        ))

    # 3. Transportation
    transport_days = (request.transport_days_override
                      if request.transport_days_override is not None
                      else count_transport_days(built_days))
    transport_data = pricing["_transport_by_code"].get(request.selected_vehicle, {})
    transport_rate = (request.transport_rate_override if getattr(request, 'transport_rate_override', 0) > 0
                      else transport_data.get("daily_rate_usd", 0))
    if transport_days > 0 and transport_rate > 0:
        transport_cost = transport_days * transport_rate
        line_items.append(QuoteLineItem(
            category="Transportation",
            description=f"{transport_data.get('vehicle_name', request.selected_vehicle)} — "
                        f"{transport_days} day(s) × ${transport_rate}/day",
            unit_price=transport_rate,
            quantity=transport_days,
            total=round(transport_cost, 2),
        ))
    elif transport_days > 0 and transport_rate == 0:
        line_items.append(QuoteLineItem(
            category="Transportation",
            description=f"{transport_data.get('vehicle_name', request.selected_vehicle)} — "
                        f"{transport_days} day(s) — rate not set, enter manually",
            unit_price=0,
            quantity=transport_days,
            total=0.0,
        ))

    # 4. Airport transfers (per person)
    if request.include_transfers:
        tf_rate = settings.get("airport_transfer_per_person_usd",
                               settings.get("airport_transfer_flat_usd", 50))
        tf_cost = tf_rate * request.num_people
        line_items.append(QuoteLineItem(
            category="Transfers",
            description=f"Airport transfers (both ways) + fast track visa — {request.num_people} person(s) × ${tf_rate}/person",
            unit_price=tf_rate,
            quantity=request.num_people,
            total=round(tf_cost, 2),
        ))

    # 5. Shrine help
    if request.include_shrine_help:
        sh_cost = settings.get("shrine_help_fee_usd", 20)
        line_items.append(QuoteLineItem(
            category="Extras",
            description="Shrine help (Abaya + female guide assistance)",
            unit_price=sh_cost,
            quantity=1,
            total=round(sh_cost, 2),
        ))

    # 6. Food
    if request.include_food and request.food_tier in (1, 2, 3):
        food_tiers = settings.get("food_tiers_usd", {})
        tier_data = food_tiers.get(str(request.food_tier), {})
        food_rate = tier_data.get("price_per_person_per_day", 0)
        food_desc = tier_data.get("description", f"Tier {request.food_tier}")
        food_cost = food_rate * request.num_people * num_days
        line_items.append(QuoteLineItem(
            category="Food",
            description=f"{food_desc} — {num_days} days × {request.num_people} people × ${food_rate}/pp/day",
            unit_price=food_rate,
            quantity=request.num_people * num_days,
            total=round(food_cost, 2),
        ))

    # 7. Accommodation (3 tiers)
    city_nights = count_hotel_nights_by_city(built_days)
    acc_3star = acc_4star = acc_5star = 0.0
    for city, nights in city_nights.items():
        for tier_key in ("3star", "4star", "5star"):
            if request.no_hotels_mode:
                cost = _hotel_team_fee_cost(city, tier_key, pricing) * nights
            else:
                cost = _hotel_night_cost(city, tier_key, request.single_rooms,
                                         request.double_rooms, pricing) * nights
            if tier_key == "3star":
                acc_3star += cost
            elif tier_key == "4star":
                acc_4star += cost
            else:
                acc_5star += cost

    # Non-accommodation subtotal (without markup yet)
    non_acc_total = sum(li.total for li in line_items)

    # Optional SUV upgrade (calculated separately, NOT folded into the main total)
    suv_upgrade_total = 0.0
    if request.show_optional_suv_upgrade:
        suv_days = transport_days or num_days
        suv_upgrade_total = round(request.suv_upgrade_daily_rate * suv_days, 2)

    # Apply dual markup
    combined_mult = _effective_multiplier(request)
    final_3 = round((non_acc_total + acc_3star) * combined_mult, 2)
    final_4 = round((non_acc_total + acc_4star) * combined_mult, 2)
    final_5 = round((non_acc_total + acc_5star) * combined_mult, 2)

    ppl = max(request.num_people, 1)

    return Quote(
        tour_type="individual",
        line_items=line_items,
        accommodation_3star=round(acc_3star, 2),
        accommodation_4star=round(acc_4star, 2),
        accommodation_5star=round(acc_5star, 2),
        non_accommodation_subtotal=round(non_acc_total, 2),
        markup_percent=request.office_markup_percent,  # legacy field — stores office %
        office_markup_percent=request.office_markup_percent,
        margin_markup_percent=request.margin_markup_percent,
        final_total_3star=final_3,
        final_total_4star=final_4,
        final_total_5star=final_5,
        per_person_3star=round(final_3 / ppl, 2),
        per_person_4star=round(final_4 / ppl, 2),
        per_person_5star=round(final_5 / ppl, 2),
        group_rows=[],
        prices_snapshot=_snapshot(pricing, request),
        generated_at=now,
        num_people=request.num_people,
        num_days=num_days,
        num_nights=num_nights,
        suv_upgrade_total=suv_upgrade_total,
        extra_staff_total=extra_staff_total,
    )


# ── Group Pricing ─────────────────────────────────────────────────────────────

def _calculate_group(request, built_days, pricing, now, num_days, num_nights):
    """
    Group pricing: calculates a per-person price for each PAX range.
    The per-person price = (all costs for group_size people) / paying_pax
    where paying_pax = group_size - foc_count.
    """
    group_rows = []
    settings = pricing["settings"]
    first_row_items = []
    first_row_acc_3 = first_row_acc_4 = first_row_acc_5 = 0.0
    first_row_non_acc = 0.0

    for i, (min_pax, max_pax) in enumerate(request.group_sizes):
        # Price from the minimum PAX in the band to avoid underquoting the
        # lower end of the range. This gives the highest per-person cost,
        # which is safe for the whole band.
        pricing_pax = min_pax
        paying_pax = max(pricing_pax - request.foc_per_group, 1)

        import copy as _copy
        fake_req = _copy.copy(request)
        fake_req.tour_type = "individual"
        fake_req.num_people = pricing_pax
        # FOC traveller(s) get single room(s); remaining pax twin-share doubles
        foc = request.foc_per_group
        fake_req.single_rooms = foc
        fake_req.double_rooms = max((pricing_pax - foc + 1) // 2, 0)
        fake_req.selected_vehicle = request.group_vehicle
        fake_req.guide_days_override = request.guide_days_override
        fake_req.transport_days_override = request.transport_days_override
        fake_req.apply_markup = request.apply_markup
        fake_req.markup_percent = request.markup_percent
        fake_req.apply_office_markup = request.apply_office_markup
        fake_req.office_markup_percent = request.office_markup_percent
        fake_req.apply_margin_markup = request.apply_margin_markup
        fake_req.margin_markup_percent = request.margin_markup_percent
        fake_req.no_hotels_mode = request.no_hotels_mode
        fake_req.extra_staff_enabled = request.extra_staff_enabled
        fake_req.extra_staff_count = request.extra_staff_count
        fake_req.extra_staff_days = request.extra_staff_days
        fake_req.extra_staff_daily_rate = request.extra_staff_daily_rate
        fake_req.show_optional_suv_upgrade = False  # SUV upgrade is individual-only
        fake_req.transport_rate_override = getattr(request, 'transport_rate_override', 0.0)

        ind_quote = _calculate_individual(fake_req, built_days, pricing, now, num_days, num_nights)

        # Use the selected hotel tier for group pricing
        tier = request.hotel_tier
        total = getattr(ind_quote, f"final_total_{tier.replace('star', '')}star",
                        ind_quote.final_total_3star)

        per_person = round(total / paying_pax, 0)
        # Round up to nearest $25 (commercial practice)
        per_person = round_up_to_25(per_person)

        group_rows.append(GroupPricingRow(
            min_pax=min_pax,
            max_pax=max_pax,
            foc_count=request.foc_per_group,
            vehicle=request.group_vehicle,
            price_per_person=per_person,
            sgl_supplement=_calculate_sgl_supplement(
                request.hotel_tier, built_days, pricing, request,
            ),
        ))

        if i == 0:
            first_row_items = ind_quote.line_items[:]
            first_row_acc_3 = ind_quote.accommodation_3star
            first_row_acc_4 = ind_quote.accommodation_4star
            first_row_acc_5 = ind_quote.accommodation_5star
            first_row_non_acc = ind_quote.non_accommodation_subtotal

    return Quote(
        tour_type="group",
        line_items=first_row_items,
        accommodation_3star=first_row_acc_3,
        accommodation_4star=first_row_acc_4,
        accommodation_5star=first_row_acc_5,
        non_accommodation_subtotal=first_row_non_acc,
        markup_percent=request.office_markup_percent,  # legacy field — stores office %
        office_markup_percent=request.office_markup_percent,
        margin_markup_percent=request.margin_markup_percent,
        final_total_3star=0,
        final_total_4star=0,
        final_total_5star=0,
        per_person_3star=0,
        per_person_4star=0,
        per_person_5star=0,
        group_rows=group_rows,
        prices_snapshot=_snapshot(pricing, request),
        generated_at=now,
        num_people=0,
        num_days=num_days,
        num_nights=num_nights,
    )


def round_up_to_25(amount: float) -> float:
    """Rounds a price up to the nearest $25 increment."""
    import math
    return math.ceil(amount / 25) * 25


def _calculate_sgl_supplement(tier: str, built_days: list, pricing: dict,
                              request) -> float:
    """
    Single-room supplement = sum over overnight cities of
    (single_rate - double_rate/2) * nights, with dual markup applied.
    """
    hotel_tiers = pricing.get("hotel_tiers", {})
    city_nights: dict[str, int] = {}
    for bd in built_days:
        if bd.night_number is not None and bd.template.overnight_city:
            city = bd.template.overnight_city
            city_nights[city] = city_nights.get(city, 0) + 1
    supp = 0.0
    for city, nights in city_nights.items():
        td = hotel_tiers.get(city, {}).get(tier, {})
        supp += (td.get("single", 0) - td.get("double", 0) / 2) * nights
    supp *= _effective_multiplier(request)
    return round(supp, 2)


def _snapshot(pricing: dict, request: TourRequest) -> dict:
    """Returns a frozen copy of the pricing data used, for the quote log."""
    snap = {
        "exchange_rate": request.exchange_rate,
        "office_markup_percent": request.office_markup_percent,
        "margin_markup_percent": request.margin_markup_percent,
        "markup_percent": request.markup_percent,  # legacy
        "settings": dict(pricing["settings"]),
        "hotel_tiers_used": {},
        "tickets_used": [],
    }
    return snap
