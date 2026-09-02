"""
services/itinerary/reply_builder.py

Builds structured, personalized customer email and WhatsApp reply drafts for custom itineraries.
"""
from __future__ import annotations

from typing import Optional
from services.itinerary.models import NormalizedRequest, ItineraryPreviewResult


def compose_email_reply(
    req: NormalizedRequest,
    preview: ItineraryPreviewResult,
    doc_url: Optional[str] = None,
    quote: Optional[dict] = None,
) -> dict[str, str]:
    destinations = ", ".join(req.requested_regions) if req.requested_regions else "Iraq"
    days = preview.delivered_day_count or req.day_count

    subject = f"Bil Weekend - Custom {days}-Day Iraq Tour Proposal for {req.customer_name}"

    q = quote or preview.estimated_quote or {}
    total_price = q.get("total_usd")
    pp_price = q.get("per_person_usd")

    pricing_section = ""
    if total_price and pp_price:
        pricing_section = (
            f"\n💰 **Trip Investment**:\n"
            f"• Total Package: ${total_price:,.2f} USD\n"
            f"• Rate per Person: ${pp_price:,.2f} USD (for {req.pax} traveler{'s' if req.pax > 1 else ''})\n"
        )

    doc_section = ""
    if doc_url:
        doc_section = f"\n📄 **Full Detailed Proposal & Day-by-Day Itinerary**:\n{doc_url}\n"

    date_str = ""
    if req.start_date:
        date_str = f"starting on {req.start_date.strftime('%B %d, %Y')}"
    elif req.travel_month:
        date_str = f"in {req.travel_month} {req.travel_year}".strip()

    body_text = f"""Dear {req.customer_name},

Thank you for contacting Bil Weekend! We are delighted to share your tailored {days}-day Iraq itinerary proposal {date_str}.

🗺️ **Trip Overview**:
• Destinations: {destinations}
• Duration: {days} Days / {max(days - 1, 1)} Nights
• Group Size: {req.pax} Traveler{'s' if req.pax > 1 else ''}
• Accommodation: {req.hotel_tier.capitalize()} Hotels
• Transport: Dedicated private vehicle with professional driver & licensed tour leader
{pricing_section}{doc_section}
✨ **Included in Your Tour**:
• All boutique/selected hotel accommodations with daily breakfast
• Private air-conditioned transportation throughout the itinerary
• Dedicated English/Arabic-speaking professional tour guide
• All site entrance fees, museum permits, and local boat excursions
• 24/7 Bil Weekend operations & checkpoint clearance support

Please review the attached itinerary proposal. We can adjust the pacing, add specific cultural stops, or customize hotel options according to your preferences.

Looking forward to welcoming you to Iraq!

Warm regards,

**Bil Weekend Operations Team**
Baghdad, Iraq
https://bilweekend.iq
"""

    body_html = f"""<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #222; line-height: 1.6;">
  <p>Dear <strong>{req.customer_name}</strong>,</p>
  <p>Thank you for contacting <strong>Bil Weekend</strong>! We are delighted to share your tailored <strong>{days}-day Iraq itinerary proposal</strong> {date_str}.</p>
  
  <div style="background: #f8f9fa; border-left: 4px solid #e8a33d; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
    <h4 style="margin: 0 0 8px 0; color: #111;">🗺️ Trip Overview</h4>
    <ul style="margin: 0; padding-left: 20px;">
      <li><strong>Destinations:</strong> {destinations}</li>
      <li><strong>Duration:</strong> {days} Days / {max(days - 1, 1)} Nights</li>
      <li><strong>Group Size:</strong> {req.pax} Traveler{'s' if req.pax > 1 else ''}</li>
      <li><strong>Accommodation:</strong> {req.hotel_tier.capitalize()} standard</li>
      <li><strong>Vehicle:</strong> Private dedicated transport</li>
    </ul>
  </div>
"""
    if total_price and pp_price:
        body_html += f"""
  <div style="background: #f0f7f4; border-left: 4px solid #2e7d32; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
    <h4 style="margin: 0 0 8px 0; color: #111;">💰 Trip Investment</h4>
    <p style="margin: 0;"><strong>Total Package:</strong> ${total_price:,.2f} USD &nbsp;|&nbsp; <strong>Per Person:</strong> ${pp_price:,.2f} USD</p>
  </div>
"""
    if doc_url:
        body_html += f"""
  <p style="margin: 20px 0;">
    <a href="{doc_url}" target="_blank" style="background: #e8a33d; color: #111; font-weight: bold; text-decoration: none; padding: 10px 18px; border-radius: 6px; display: inline-block;">
      📄 View Detailed Itinerary & Document
    </a>
  </p>
"""
    body_html += """
  <p>Please feel free to reply with any adjustments or questions. We look forward to hosting you!</p>
  <p style="margin-top: 24px; color: #666; font-size: 13px;">
    <strong>Bil Weekend Operations Team</strong><br>
    Baghdad, Iraq | <a href="https://bilweekend.iq" style="color: #e8a33d;">bilweekend.iq</a>
  </p>
</div>
"""

    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
    }


def compose_whatsapp_reply(
    req: NormalizedRequest,
    preview: ItineraryPreviewResult,
    doc_url: Optional[str] = None,
    quote: Optional[dict] = None,
) -> str:
    days = preview.delivered_day_count or req.day_count
    destinations = ", ".join(req.requested_regions) if req.requested_regions else "Iraq"

    q = quote or preview.estimated_quote or {}
    total_price = q.get("total_usd")

    price_line = f"• Total Price: ${total_price:,.2f} USD\n" if total_price else ""
    doc_line = f"\n📄 Detailed Proposal:\n{doc_url}\n" if doc_url else ""

    return f"""Hello {req.customer_name}! 🇮🇶

Here is your customized *{days}-Day Bil Weekend Tour* proposal for {destinations}:

• Duration: {days} Days
• Guests: {req.pax}
• Hotel Tier: {req.hotel_tier.capitalize()}
{price_line}{doc_line}
Please let us know if you would like to adjust any dates or destinations! ✨"""
