"""
BilWeekend Itinerary Generator
Data models for tour requests, itinerary templates, pricing, and document assembly.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class DayTemplate:
    code: str
    title: str
    city: str
    region: str
    overnight_city: str          # empty string if no overnight (day trip or departure day)
    full_text: str               # client-facing activity content (no "Day N" header, no "Overnight:" line)
    included_sites: list         # site_codes from entry_tickets.json
    pricing_tags: list           # e.g. ["guide_day", "transport_day", "hotel_night"]
    active: bool
    needs_review: bool
    internal_notes: str


@dataclass
class BuiltDay:
    """A DayTemplate resolved into a specific position in an itinerary."""
    day_number: int
    night_number: Optional[int]  # None if no overnight
    date: Optional[date]
    template: DayTemplate


@dataclass
class TourRequest:
    doc_name: str
    day_codes: list              # ordered list of day template codes
    start_date: Optional[date]   # first day date; None = no dates shown
    tour_type: str               # "individual" or "group"

    # Individual / FIT pricing fields
    num_people: int
    single_rooms: int
    double_rooms: int
    hotel_tier: str              # "3star", "4star", or "5star"
    selected_vehicle: str        # vehicle_code from transport.json
    guide_days_override: Optional[int]      # None = auto-count from pricing_tags
    transport_days_override: Optional[int]  # None = auto-count from pricing_tags
    include_transfers: bool
    include_shrine_help: bool
    include_food: bool
    food_tier: Optional[int]     # 1, 2, or 3
    apply_markup: bool
    markup_percent: float
    exchange_rate: float         # IQD per 1 USD — required, no default

    # Group pricing fields
    group_sizes: list            # list of (min_pax, max_pax) tuples for the pricing table
    foc_per_group: int           # how many FOC per group tier (usually 1)
    group_vehicle: str           # "TOYOTA_COASTER" or "VIP_BUS"
    sgl_supplement: float        # single room supplement for group pricing
    transport_rate_override: float = 0.0  # manual daily rate when vehicle rate is 0

    # ── Dual markup (web GUI; replaces single apply_markup / markup_percent) ──
    apply_office_markup: bool = True          # operational/overhead markup
    office_markup_percent: float = 20.0
    apply_margin_markup: bool = True          # profit margin on top
    margin_markup_percent: float = 10.0

    # ── Pricing output mode ───────────────────────────────────────────────────
    # "selected_only" → show only the chosen tier in the document
    # "all_tiers"     → show 3-star, 4-star, and 5-star lines side-by-side
    pricing_output_mode: str = "selected_only"

    # ── Optional SUV upgrade (individual tours only) ──────────────────────────
    show_optional_suv_upgrade: bool = False
    suv_upgrade_daily_rate: float = 100.0

    # ── Document includes control ─────────────────────────────────────────────
    # Empty list = auto-select based on request flags (legacy behaviour).
    # Non-empty = only the listed keys appear in the Includes section.
    # Recognised keys: visa_transfers, evisa, guide, entry_tickets, tours,
    #                  transport, accommodation, shrine_help, logistics
    selected_include_keys: list = field(default_factory=list)

    # ── No-hotels mode ────────────────────────────────────────────────────────
    # When True, room costs are excluded; only the per-night team_fee is kept.
    no_hotels_mode: bool = False

    # ── Extra staff (guides, photographers, etc.) ─────────────────────────────
    extra_staff_enabled: bool = False
    extra_staff_count: int = 1
    extra_staff_days: Optional[int] = None   # None = same number as guide_days
    extra_staff_daily_rate: float = 70.0


@dataclass
class QuoteLineItem:
    category: str
    description: str
    unit_price: float
    quantity: float
    total: float


@dataclass
class GroupPricingRow:
    min_pax: int
    max_pax: int
    foc_count: int
    vehicle: str
    price_per_person: float
    sgl_supplement: float


@dataclass
class Quote:
    tour_type: str               # "individual" or "group"

    # Individual quote fields
    line_items: list             # list of QuoteLineItem
    accommodation_3star: float
    accommodation_4star: float
    accommodation_5star: float
    non_accommodation_subtotal: float
    markup_percent: float
    final_total_3star: float
    final_total_4star: float
    final_total_5star: float
    per_person_3star: float
    per_person_4star: float
    per_person_5star: float

    # Group quote fields
    group_rows: list             # list of GroupPricingRow

    # Common
    prices_snapshot: dict        # frozen copy of all prices used at generation time
    generated_at: str
    num_people: int
    num_days: int
    num_nights: int

    # Markup breakdown (for display in preview and document)
    office_markup_percent: float = 0.0
    margin_markup_percent: float = 0.0

    # Optional extras totals (separate from the main quote total)
    suv_upgrade_total: float = 0.0
    extra_staff_total: float = 0.0


@dataclass
class DocumentSection:
    section_type: str   # "title", "day", "end_of_tour", "pricing", "includes",
                        # "payment_notes", "general_info", "contacts"
    content: dict       # structured content for this section type
