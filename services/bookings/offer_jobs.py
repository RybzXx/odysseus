"""
services/bookings/offer_jobs.py

Pricing a website registration, without ever learning who made it.

An operator presses a button in the admin panel, the website writes a job row,
and this module answers it. The direction is unusual: every other exchange with
Bil Weekend has Odysseus posting a record to a site that can read it. This one
has the site leaving work where Odysseus already looks, because Odysseus runs on
a phone with no inbound route (ws-bd D5).

Why the job carries no customer
-------------------------------
Odysseus arms an external-context gate the moment a run reads untrusted text,
and a run past that point may not act. A run that read a registrant's name could
price the tour and would then be forbidden to write the answer back.

So the job names a tour, a party size and the day codes. This module reasons
about none of the customer. `_PricingRequest` below carries no name by
construction, and the document is titled from the tour. The greeting is added by
`templates.render_quote`, which is `str.replace` and not a model call, and the
website supplies the name at that moment (ws-bd D6).

The matcher does not run
------------------------
`generator.execute_generation` previews first, which asks the matcher to choose
days. A booking already knows its days. Running the matcher to discard its
answer would spend the work and would also attach gap notes about a route nobody
asked for, so this builds the document from the codes directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from services.bookings.templates import render_quote
from services.bookings.tour_day_codes import day_codes_for, shortfall_for

logger = logging.getLogger(__name__)

# What a registration is assumed to want, where the form does not ask.
#
# A registration names a tour and a party size and nothing else. The pricer
# needs a hotel tier and a vehicle, and these are the values every observed
# quote was built on. They are assumptions, and a quote that turns out wrong is
# corrected by the operator before it is sent, not by this module guessing
# harder.
DEFAULT_HOTEL_TIER = "3star"
DEFAULT_TOUR_TYPE = "individual"

# Which vehicle a party of this size travels in.
#
# Read from the pricing data's own vehicle names. A party that outgrows a van
# takes a coaster; nothing here books a VIP bus, which is a group-departure
# vehicle and a group departure never reaches this module.
def _vehicle_for(pax: int) -> str:
    if pax <= 3:
        return "SMALL_CAR"
    if pax <= 10:
        return "VAN"
    return "COASTER"


@dataclass(frozen=True)
class _PricingRequest:
    """
    The subset of a request that `build_tour_request` reads.

    Inv: holds no name, no email, no phone and no customer text. It is a
    separate type from `NormalizedRequest` for exactly that reason — the full
    one has a `customer_name` field, and a field that exists is a field somebody
    fills.
    """
    pax: int
    start_date: Optional[date] = None
    tour_type: str = DEFAULT_TOUR_TYPE
    hotel_tier: str = DEFAULT_HOTEL_TIER
    vehicle_type: str = "SMALL_CAR"


@dataclass
class OfferJobOutcome:
    """
    What a run has to say about one job.

    `email_subject` and `email_body` still hold `{first_name}` and
    `{full_name}`. The run has no name to fill and must not learn one, so the
    website substitutes both from the registration it is already showing
    (ws-bd D6, D7).
    """
    email_subject: str = ""
    email_body: str = ""
    itinerary_url: str = ""
    price_usd: Optional[float] = None
    price_per_person_usd: Optional[float] = None
    shortfall: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def as_result_payload(self) -> dict:
        """Post: the body for POST /api/agent/ops/jobs/{id}/result."""
        return {
            "emailSubject": self.email_subject or None,
            "emailBody": self.email_body or None,
            "itineraryUrl": self.itinerary_url or None,
            "priceUsd": self.price_usd,
            "pricePerPersonUsd": self.price_per_person_usd,
            "shortfall": self.shortfall or None,
            "error": self.error or None,
        }


def codes_for_job(job: dict) -> tuple[str, ...]:
    """
    Post: the day codes to price, in order. Empty when neither source names any.

    Pre:  `job` is one row from GET /api/agent/ops/jobs.

    The website sends the tour's own `templateCodes`, which is empty for every
    tour today. The default map answers then (ws-bd D4).
    """
    return day_codes_for(job.get("tourSlug", ""), job.get("templateCodes") or None)


def price_and_build(job: dict) -> OfferJobOutcome:
    """
    Price one job's days and build its document.

    Pre:  `job` names a tourSlug and a partySize of 1 or more. It carries no
          customer text, and this function reads no field that could.
    Post: an outcome holding a document link and a price, or an error naming
          what stopped it.
    Inv:  never raises. A job that cannot be priced must close with a reason an
          operator can read, because the alternative is a button that spins.

    Blame: an empty code list is a caller bug — the website refuses to queue a
    tour with no days, and the map covers every tour it does queue.
    """
    from services.itinerary import generator

    codes = codes_for_job(job)
    if not codes:
        return OfferJobOutcome(
            error=f"No day templates are mapped for '{job.get('tourSlug')}'.")

    pipeline = generator._PIPELINE or generator._ensure_pipeline_imported()
    if not pipeline:
        return OfferJobOutcome(error="The itinerary pipeline failed to import.")

    pax = max(1, int(job.get("partySize") or 1))
    request = _PricingRequest(pax=pax, vehicle_type=_vehicle_for(pax))

    # The document is named for the tour and the party, never for a person.
    # `build_tour_request` falls back to `req.customer_name` when this is None,
    # and `_PricingRequest` has no such field to fall back to.
    doc_name = f"{job.get('tourSlug') or 'Tour'} - {len(codes)} Days ({pax} PAX)"

    try:
        tour_request = generator.build_tour_request(
            request, list(codes), doc_name=doc_name)
        result = pipeline["generate_document"](tour_request)
    except Exception as exc:
        logger.exception("offer job %s failed to build", job.get("id"))
        return OfferJobOutcome(error=f"Document build failed: {exc}")

    if not result.get("ok"):
        errors = result.get("errors") or ["Document rendering failed."]
        return OfferJobOutcome(error="; ".join(str(e) for e in errors))

    quote = _quote_summary(result.get("quote"))

    # The wording, with the greeting left open. A single-day tour asks for
    # nothing; anything longer asks for passports and a date (ws-bd D3).
    reply = render_quote(
        tour_name=job.get("tourName") or job.get("tourSlug") or "your tour",
        party_size=pax,
        ask_to_confirm=len(codes) > 1,
        operator=job.get("operator") or "",
    )

    return OfferJobOutcome(
        email_subject=reply.subject,
        email_body=reply.body,
        itinerary_url=result.get("doc_url") or "",
        price_usd=quote.get("total_usd"),
        price_per_person_usd=quote.get("per_person_usd"),
        shortfall=shortfall_for(job.get("tourSlug", "")),
    )


def _quote_summary(quote: Any) -> dict:
    """
    Post: total and per-person in US dollars, or {} when the quote is absent.

    Reads the three-star fields, matching DEFAULT_HOTEL_TIER. A quote whose
    tier and whose request disagree is a number nobody can explain.
    """
    if not quote:
        return {}
    try:
        return {
            "total_usd": round(float(getattr(quote, "final_total_3star", 0.0)), 2),
            "per_person_usd": round(float(getattr(quote, "per_person_3star", 0.0)), 2),
        }
    except Exception:
        logger.warning("offer job quote could not be read", exc_info=True)
        return {}
