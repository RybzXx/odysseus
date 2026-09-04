"""
BilWeekend — Document Assembler
Takes built itinerary days, a quote, and request details,
and returns an ordered list of DocumentSection objects ready for rendering.
"""
from services.itinerary.pipeline.models import DocumentSection, TourRequest, Quote
from services.itinerary.pipeline.builder import format_day_header, format_overnight_line
from services.itinerary.pipeline import config


def _combined_markup_mult(request: TourRequest) -> float:
    """Combined office × margin multiplier (≥ 1.0)."""
    office = (1 + request.office_markup_percent / 100) if request.apply_office_markup else 1.0
    margin = (1 + request.margin_markup_percent / 100) if request.apply_margin_markup else 1.0
    return office * margin


def assemble(request: TourRequest, built_days: list, quote: Quote,
             general_info: dict, pricing: dict,
             include_breakdown_in_doc: bool = False,
             hotel_overrides: dict | None = None,
             triple_rooms: int = 0) -> list:
    sections = []

    # 1. Document Title
    sections.append(DocumentSection(
        section_type="title",
        content={"text": request.doc_name},
    ))

    # 2. Day-by-day itinerary
    for built_day in built_days:
        tmpl = built_day.template
        day_header = format_day_header(built_day)
        overnight_line = format_overnight_line(built_day)

        sections.append(DocumentSection(
            section_type="day",
            content={
                "header": day_header,
                "bullet_lines": [line for line in tmpl.full_text.split("\n") if line.strip()],
                "overnight": overnight_line,
            },
        ))

    # 3. End of tour
    sections.append(DocumentSection(
        section_type="end_of_tour",
        content={"text": "End of Tour"},
    ))

    # 4. Pricing section
    sections.append(DocumentSection(
        section_type="pricing",
        content=_build_pricing_content(
            request, quote,
            include_breakdown=include_breakdown_in_doc,
            built_days=built_days,
            hotel_overrides=hotel_overrides or {},
            triple_rooms=triple_rooms,
            hotels_by_code=pricing.get("_hotels_by_code", {}),
        ),
    ))

    # 4b. Hotel options by tier (suppressed in no-hotels mode)
    if not getattr(request, 'no_hotels_mode', False):
        sections.append(DocumentSection(
            section_type="hotel_options",
            content=_build_hotel_options_content(
                request, built_days, quote, pricing,
                hotel_overrides=hotel_overrides or {},
            ),
        ))

    # 5. Includes
    sections.append(DocumentSection(
        section_type="includes",
        content=_build_includes_content(request, quote),
    ))

    # 6. Payment notes
    sections.append(_build_payment_notes_section())

    # 7. General information section
    sections.extend(_build_general_info_sections(general_info))

    return sections


def _build_hotel_options_content(request: TourRequest, built_days: list, quote: Quote,
                                  pricing: dict, hotel_overrides: dict | None = None) -> dict:
    hotel_defaults = pricing.get("hotel_defaults", {})
    hotel_rates = pricing.get("hotel_tiers", {})
    hotels_by_code = pricing.get("_hotels_by_code", {})
    overrides = hotel_overrides or {}

    output_mode = getattr(request, 'pricing_output_mode', 'selected_only')
    tier_label_map = {"3star": "3-star", "4star": "4-star", "5star": "5-star"}
    selected_label = tier_label_map.get(request.hotel_tier, request.hotel_tier.replace('star', '-star'))

    city_hotel_rows = []
    seen_cities = set()
    for built_day in built_days:
        city = built_day.template.overnight_city
        if not city or city in seen_cities:
            continue
        seen_cities.add(city)
        city_hotel_rows.append(_build_city_hotel_row(city, hotel_defaults, hotel_rates))

    # Build custom block first so we know whether to suppress tier blocks
    custom_block = None
    if overrides:
        custom_lines = []
        for row in city_hotel_rows:
            city = row["city"]
            code = overrides.get(city)
            if code and code in hotels_by_code:
                h = hotels_by_code[code]
                name = h.get("hotel_name", code)
                custom_lines.append(f"{city}: {name}")
            else:
                custom_lines.append(f"{city}: (default {selected_label})")
        if custom_lines:
            custom_block = {"title": "Selected Hotels", "lines": custom_lines}

    # Summary lines: only shown in all_tiers mode as a tier comparison (not for custom or selected_only
    # since the pricing section already shows the total)
    summary_lines = []
    if not custom_block and output_mode == "all_tiers" and request.tour_type == "individual":
        summary_lines = [
            f"3-star total: ${quote.final_total_3star:,.0f} | per person: ${quote.per_person_3star:,.0f}",
            f"4-star total: ${quote.final_total_4star:,.0f} | per person: ${quote.per_person_4star:,.0f}",
            f"5-star total: ${quote.final_total_5star:,.0f} | per person: ${quote.per_person_5star:,.0f}",
        ]

    # Tier blocks: suppressed when custom overrides are in use
    tier_blocks = []
    tier_labels = {"3star": "3-star Hotels", "4star": "4-star Hotels", "5star": "5-star Hotels"}
    if not custom_block:
        tiers_to_show = ("3star", "4star", "5star") if output_mode == "all_tiers" else (request.hotel_tier,)
        for tier in tiers_to_show:
            lines = [f"{row['city']}: {row[tier]}" for row in city_hotel_rows]
            tier_blocks.append({"title": tier_labels.get(tier, tier), "lines": lines})

    if custom_block:
        header = "Selected Hotels"
    elif output_mode == "all_tiers":
        header = "Hotel Options by Star Tier"
    else:
        header = f"{selected_label} Hotels"

    return {
        "header": header,
        "summary_lines": summary_lines,
        "tier_blocks": tier_blocks,
        "custom_block": custom_block,
    }


def _round_to_nearest_50(value: float) -> int:
    return int(((value + 25) // 50) * 50)


def _compute_custom_acc(built_days: list, hotel_overrides: dict, triple_rooms: int,
                        sgl_rooms: int, dbl_rooms: int, hotels_by_code: dict) -> float:
    """Compute total accommodation cost using custom hotel overrides."""
    city_nights: dict[str, int] = {}
    for bd in built_days:
        if bd.night_number is not None and bd.template.overnight_city:
            city = bd.template.overnight_city
            city_nights[city] = city_nights.get(city, 0) + 1

    total = 0.0
    for city, nights in city_nights.items():
        code = hotel_overrides.get(city)
        if code and code in hotels_by_code:
            h = hotels_by_code[code]
            total += (
                sgl_rooms * h.get("single_rate", 0.0)
                + dbl_rooms * h.get("double_rate", 0.0)
                + triple_rooms * h.get("triple_rate", 0.0)
            ) * nights
    return total


def _build_pricing_content(request: TourRequest, quote: Quote, include_breakdown: bool = False,
                           built_days: list | None = None, hotel_overrides: dict | None = None,
                           triple_rooms: int = 0, hotels_by_code: dict | None = None) -> dict:
    num_days = quote.num_days
    num_nights = quote.num_nights

    if request.tour_type == "group":
        return {
            "header": f"Pricing — Twin Room BB Basis",
            "validity_note": f"*These prices are for the {config.PRICE_VALIDITY}.",
            "tour_summary": f"{num_days} Days / {num_nights} Nights",
            "table_type": "group",
            "rows": [
                {
                    "pax_range": f"{r.min_pax}-{r.max_pax} PAX + {r.foc_count}",
                    "vehicle": r.vehicle,
                    "price_per_person": f"${int(r.price_per_person)}",
                    "sgl_supplement": f"${int(r.sgl_supplement)}" if r.sgl_supplement else "",
                }
                for r in quote.group_rows
            ],
        }
    else:
        lines = []
        if include_breakdown:
            for li in quote.line_items:
                lines.append(f"{li.description}: ${li.total:,.0f}")

        tier = request.hotel_tier
        acc = getattr(quote, f"accommodation_{tier}")
        final = getattr(quote, f"final_total_{tier}")
        rounded_final = _round_to_nearest_50(final)

        # Issue 2: pricing output mode
        output_mode = getattr(request, 'pricing_output_mode', 'selected_only')
        if output_mode == "all_tiers":
            all_tiers_line = (
                f"3-star total: ${_round_to_nearest_50(quote.final_total_3star):,}"
                f"  (${quote.per_person_3star:,.0f} / person)\n"
                f"4-star total: ${_round_to_nearest_50(quote.final_total_4star):,}"
                f"  (${quote.per_person_4star:,.0f} / person)\n"
                f"5-star total: ${_round_to_nearest_50(quote.final_total_5star):,}"
                f"  (${quote.per_person_5star:,.0f} / person)"
            )
            final_total_line = all_tiers_line
            per_person_line = ""
        else:
            final_total_line = f"Total (rounded to nearest $50): ${rounded_final:,.0f}"
            per_person_line = ""

        # Issue 3: SUV upgrade optional note
        suv_note = ""
        suv_total = getattr(quote, 'suv_upgrade_total', 0.0)
        if request.show_optional_suv_upgrade and suv_total > 0:
            suv_note = f"Optional 4×4 SUV upgrade: +${suv_total:,.0f} to total"

        # Compute custom total if hotel overrides were applied (not applicable in no-hotels mode)
        custom_total_line = ""
        if hotel_overrides and built_days and hotels_by_code is not None and not getattr(request, 'no_hotels_mode', False):
            custom_acc = _compute_custom_acc(
                built_days, hotel_overrides, triple_rooms,
                request.single_rooms, request.double_rooms,
                hotels_by_code,
            )
            raw = quote.non_accommodation_subtotal + custom_acc
            combined_mult = _combined_markup_mult(request)
            custom_final = _round_to_nearest_50(raw * combined_mult)
            custom_ppp = round(custom_final / max(request.num_people, 1), 0)
            custom_total_line = (
                f"Total with custom hotels (rounded): ${custom_final:,.0f} "
                f"(${custom_ppp:,.0f} / person)"
            )

        return {
            "header": f"Pricing for {num_days} Days / {num_nights} Nights",
            "validity_note": f"*These prices are for the {config.PRICE_VALIDITY}.",
            "tour_summary": f"{num_days} Days / {num_nights} Nights — {request.num_people} person(s)",
            "table_type": "individual",
            "breakdown_lines": lines,
            "accommodation_cost": f"Accommodation ({tier}): ${acc:,.0f}" if include_breakdown else "",
            "subtotal": f"Subtotal (before markup): ${quote.non_accommodation_subtotal + acc:,.0f}" if include_breakdown else "",
            "markup": f"Service & management: included" if include_breakdown else "",
            "final_total": final_total_line,
            "custom_total": custom_total_line,
            "suv_note": suv_note,
            "per_person": per_person_line,
        }


def _build_includes_content(request: TourRequest, quote: Quote) -> dict:
    # Transportation description
    vehicle_map = {
        "SMALL_CAR": "a comfortable private car",
        "LARGE_CAR": "a large 4x4 vehicle",
        "TOYOTA_COASTER": "a 28-seater Toyota Coaster in cities and a 32-seater VIP Bus "
                          "when travelling between cities",
        "VIP_BUS": "a 32-seater VIP Bus",
    }
    veh = request.selected_vehicle if request.tour_type == "individual" else request.group_vehicle
    transport_desc = vehicle_map.get(veh, f"transportation ({veh})")

    # All possible include items indexed by key
    all_possible = {
        "visa_transfers": "Fast track visa & airport transfers.",
        "evisa": "eVisa assistance (applied prior to travel).",
        "guide": (
            "A knowledgeable tour guide, including at least one female member to arrange access "
            "to the holy shrines for females. In addition to local coordinators and guides in "
            "each city to facilitate running the tour."
        ),
        "entry_tickets": "Entry tickets to all mentioned sites.",
        "tours": "Tours and activities.",
        "transport": f"Transportation, using {transport_desc}.",
        "accommodation": "Accommodation in hotels as per the selection.",
        "shrine_help": "Shrine access support and facilitation.",
        "logistics": "Logistical services.",
        "foc_single_room": "Free of Charge spot in a single room.",
        "lunch_marshes": "Lunch in the marshes.",
        "full_board_meals": "Full board meals throughout the trip.",
        "half_board_meals": "Half board meals throughout the trip.",
    }

    selected_keys = getattr(request, 'selected_include_keys', [])
    if selected_keys:
        # Explicit selection from the web GUI checkboxes
        items = [all_possible[k] for k in selected_keys if k in all_possible]
    else:
        # Auto-select based on request flags (legacy / Tkinter / CLI behaviour)
        items = [
            all_possible["visa_transfers"] if request.include_transfers else all_possible["evisa"],
            all_possible["guide"],
            all_possible["entry_tickets"],
            all_possible["tours"],
            all_possible["transport"],
            all_possible["accommodation"],
        ]
        if request.include_shrine_help:
            items.append(all_possible["shrine_help"])
        if request.tour_type == "group":
            items.append(all_possible["foc_single_room"])
        items.append(all_possible["logistics"])

    optional = None
    if request.include_food and request.food_tier:
        food_prices = {"1": 10, "2": 15, "3": 20}
        price = food_prices.get(str(request.food_tier), "")
        optional = (
            f"Full board of local food, refreshments and snacks throughout the trip "
            f"(${price * quote.num_days}/PAX)" if price else
            "Full board of local food, refreshments and snacks throughout the trip."
        )

    return {"items": items, "optional": optional}


def _build_city_hotel_row(city: str, hotel_defaults: dict, hotel_rates: dict) -> dict:
    row = {"city": city}
    for tier in ("3star", "4star", "5star"):
        hotel_name = hotel_rates.get(city, {}).get(tier, {}).get("hotel_name")
        if not hotel_name:
            hotel_name = hotel_defaults.get(city, {}).get(tier, "")
        if not hotel_name:
            hotel_name = "TBD"
        row[tier] = hotel_name
    return row


def _build_payment_notes_section() -> DocumentSection:
    return DocumentSection(
        section_type="payment_notes",
        content={
            "bank_transfer_note": (
                f"If you would like to pay by bank transfer, kindly add "
                f"{config.BANK_TRANSFER_SURCHARGE_PCT}% to your total. "
                "However cash is welcomed and we can receive with no increase or change "
                "to the agreed amount in your total."
            ),
            "cash_note": (
                "If you would like to pay cash, kindly make sure to bring 100$ notes or 50$ "
                "notes as they are most preferable to pay with in Iraq. However our team can "
                "receive any other smaller notes but they should not be more than 30% of the "
                "total amount. Make sure that the 100$ bills are printed after 2006 as older "
                "ones will not be accepted in all of Iraq."
            ),
        },
    )


def _build_general_info_sections(general_info: dict) -> list:
    """Returns a list of general_info_section DocumentSections."""
    sections = []
    general_info_sections = general_info.get("sections", [])
    if general_info_sections:
        body_parts = []
        for section in general_info_sections:
            body = section.get("body", "").strip()
            if body:
                body_parts.append(body)
        if body_parts:
            sections.append(DocumentSection(
                section_type="general_info_section",
                content={
                    "heading": "General Information",
                    "body": "\n\n".join(body_parts),
                },
            ))
    return sections


def assemble_day_trips(
    doc_name: str,
    trips_data: list,
    general_info: dict,
    pricing: dict,
    include_breakdown_in_doc: bool = False,
) -> list:
    """
    Assemble a multi-trip document from a list of fully-resolved trip dicts.

    Each element of trips_data must have:
        name          str               — displayed as a HEADING_1 trip title
        request       TourRequest
        built_days    list[BuiltDay]
        quote         Quote
        hotel_overrides  dict[str, str]  (may be empty)
        triple_rooms  int

    Document structure:
        title
        for each trip:
            trip_section_title
            day × N
            end_of_tour
            pricing
            hotel_options  (unless no_hotels_mode)
            includes
            payment_notes
        general_info_section × M
    """
    sections = []

    # 1. Document title
    sections.append(DocumentSection(
        section_type="title",
        content={"text": doc_name},
    ))

    # 2. One block per trip
    for trip in trips_data:
        name = trip["name"]
        request = trip["request"]
        built_days = trip["built_days"]
        quote = trip["quote"]
        hotel_overrides = trip.get("hotel_overrides") or {}
        triple_rooms = trip.get("triple_rooms", 0)

        # 2a. Trip section title
        sections.append(DocumentSection(
            section_type="trip_section_title",
            content={"text": name},
        ))

        # 2b. Day-by-day itinerary
        for built_day in built_days:
            tmpl = built_day.template
            sections.append(DocumentSection(
                section_type="day",
                content={
                    "header": format_day_header(built_day),
                    "bullet_lines": [l for l in tmpl.full_text.split("\n") if l.strip()],
                    "overnight": format_overnight_line(built_day),
                },
            ))

        # 2c. End of tour
        sections.append(DocumentSection(
            section_type="end_of_tour",
            content={"text": "End of Tour"},
        ))

        # 2d. Pricing
        sections.append(DocumentSection(
            section_type="pricing",
            content=_build_pricing_content(
                request, quote,
                include_breakdown=include_breakdown_in_doc,
                built_days=built_days,
                hotel_overrides=hotel_overrides,
                triple_rooms=triple_rooms,
                hotels_by_code=pricing.get("_hotels_by_code", {}),
            ),
        ))

        # 2e. Hotel options (suppressed in no_hotels_mode)
        if not getattr(request, "no_hotels_mode", False):
            sections.append(DocumentSection(
                section_type="hotel_options",
                content=_build_hotel_options_content(
                    request, built_days, quote, pricing,
                    hotel_overrides=hotel_overrides,
                ),
            ))

        # 2f. Includes
        sections.append(DocumentSection(
            section_type="includes",
            content=_build_includes_content(request, quote),
        ))

        # 2g. Payment notes (once per trip)
        sections.append(_build_payment_notes_section())

    # 3. General information (once at end)
    sections.extend(_build_general_info_sections(general_info))

    return sections
