"""
services/bookings/templates.py

The two emails a website registration gets, and the rule that picks between
them.

Both texts are transcribed from `book@bilweekend.com`, read on 2026-09-09.
Operations types them by hand into Gmail today, and the wording here is theirs,
not a rewrite of it. Where two sends of one template disagreed, the more common
form won and the difference is noted at the constant.

`tourType` picks the template and nothing else does (ws-bd D1). It predicted the
template on 11 of the 12 threads read. The twelfth is a Private Trips tour that
received the group template, complete with an offer of a shared room to a party
of two — the kind of substitution a stored template does not make.

`price` cannot pick it. Four Group Expedition tours price at 0, and choosing on
price sends them the quote.

Substitution takes six values and no more (ws-bd 6.3):

    first_name  tour_name  month_year  party_size  price  itinerary_link

None of the six needs judgement, so filling them is `str.replace` and never a
model call. That is what keeps the external-context gate shut: a run that
prices a tour reads no customer text, and the name arrives after the reasoning
is over (ws-bd D6).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# What the two templates are called.
#
# `deposit` asks for money and papers against a published price. `quote` sends
# a price that did not exist until Odysseus computed it. They are different
# acts, and the names say which.
TEMPLATE_DEPOSIT = "deposit"
TEMPLATE_QUOTE = "quote"

# `tourType` to template. The keys are the values the website stores.
#
# `Group Expedition` sells a scheduled departure at a published price, so the
# customer is asked for a deposit. The other two are quoted for the party that
# asked, so they are sent a price.
TEMPLATE_BY_TOUR_TYPE: dict[str, str] = {
    "group expedition": TEMPLATE_DEPOSIT,
    "private trips": TEMPLATE_QUOTE,
    "experience": TEMPLATE_QUOTE,
}

# What a Group Expedition asks for in advance, in US dollars.
#
# Both observed sends said $350. It is a business term rather than a
# calculation, so it sits here where an operator can find it.
DEPOSIT_USD = 350

# Where a deposit is paid. Customer-facing on every send, so not a secret.
#
# Transcribed as sent. An operator changing the account changes this block.
PAYMENT_DETAILS = """Beneficiary
Ali Al Makhzoomi

IBAN
GB34 REVO 0099 7049 5646 21

BIC / SWIFT code
REVOGB21

Address
Revolut Ltd
7 Westferry Circus, E14 4HD, London, United Kingdom

Correspondent BIC
CHASGB2L"""

# The deposit request, for a scheduled group departure.
#
# One observed send asked for a visa photo and another for a WhatsApp number.
# Both are here: the two sends were nine days apart and neither operator
# dropped a line the other thought necessary.
DEPOSIT_BODY = """Dear {first_name},

I hope this email finds you well. We are writing regarding your request to join {tour_name} in Iraq in {month_year}. Kindly let us know the following information to proceed with the booking:

   - Your choice of single or shared room
   - A scan of your passport
   - A personal photo with a white background for your visa application
   - A valid phone number with WhatsApp, for updates about the tour
   - A ${deposit} deposit is required in advance to secure your booking

Please see below the account details where you can make the payment:

{payment_details}

Additionally, please see the itinerary of the tour attached to this email.

Feel free to let us know if you have any other questions. I look forward to hearing from you soon.

Best regards,

{signature}"""

# The quote, for a tour priced for the party that asked.
#
# Three of the four observed quotes opened "We are contacting you regarding
# your request", so that opening won. The fourth opened by naming the operator,
# and its signature says the same thing further down.
#
# `{rate_line}` and `{confirm_block}` are the two parts that come and go. A day
# trip for one person needs neither.
QUOTE_BODY = """Dear {first_name},

I hope this email finds you well. We are contacting you regarding your request for {tour_name}.

Please find the requested itinerary and pricing attached.{rate_line}{confirm_block}

If you have any questions, please do not hesitate to contact us.

Best regards,

{signature}"""

# Asked for on every quote that expects a booking to follow.
#
# Left out of a single-day Experience, where the observed send asked for
# nothing (ws-bd D3).
CONFIRM_BLOCK = """

To confirm the booking, please send us the following information:

   - A clear scan of your passports
   - The intended date of the tour"""

# Who signed. Keyed by the lowercase start of the operator name the worklist
# stores, because the worklist says 'Nooriya' where the signature says
# 'Noor Ahmed'.
SIGNATURES: dict[str, str] = {
    "noor": """Noor Ahmed

Operations Department

Rehlat Al-Utla Travel Co. / Bil Weekend

+964 780 495 5885

noor.ahmed@bilweekend.iq

www.bilweekend.com""",
    "mustafa": "Mustafa Simani",
}

# Signed with when the row names no operator, or names one with no signature.
#
# The company rather than a person: a draft that invents a colleague's name is
# worse than one an operator has to sign.
SIGNATURE_WHEN_UNKNOWN = """Bil Weekend

Operations Department

Rehlat Al-Utla Travel Co. / Bil Weekend

www.bilweekend.com"""


class UnfilledPlaceholder(Exception):
    """A rendered body still holds a placeholder.

    Raised rather than returned. A draft reading 'Dear {first_name}' is worse
    than no draft, and the job that produced it should report an error the
    reviewer can see.
    """


@dataclass(frozen=True)
class ReplyTemplate:
    """One template, as it travels to the website and back."""
    name: str
    subject: str
    body: str


def template_for_tour_type(tour_type: str) -> Optional[str]:
    """
    Post: TEMPLATE_DEPOSIT, TEMPLATE_QUOTE, or None when the type is unknown.

    Pre:  `tour_type` is the website's `Tour.tourType`.

    None is a real answer and callers must show it rather than guess. A tour
    with a type nobody has seen gets no draft and says so, because the wrong
    template asks a private traveller to share a room.
    """
    return TEMPLATE_BY_TOUR_TYPE.get(str(tour_type or "").strip().lower())


def signature_for(operator: str) -> str:
    """
    Post: the operator's signature block, or the company one.

    Pre:  `operator` is the follow-up row's operator, which is often empty.
    """
    key = str(operator or "").strip().lower()
    for prefix, block in SIGNATURES.items():
        if key.startswith(prefix):
            return block
    return SIGNATURE_WHEN_UNKNOWN


def first_name_of(full_name: str) -> str:
    """
    Post: the name to greet with. "" when the input holds no word.

    Pre:  `full_name` is the registration's name, as typed by the customer.

    Every observed send greeted by first name, including the ones where the
    customer typed their name in capitals. Title case is applied for that
    reason: 'CARLOS GUIDO TRAMUTOLA' was answered 'Dear Carlos'.
    """
    words = [w for w in re.split(r"\s+", str(full_name or "").strip()) if w]
    if not words:
        return ""
    first = words[0]
    return first if not first.isupper() else first.title()


def raw_templates() -> tuple[ReplyTemplate, ReplyTemplate]:
    """
    Post: both templates with their placeholders unfilled, deposit first.

    The website shows these in the Overview tab before any pricing has run, and
    fills the deposit one itself — a group departure is priced already, so
    waiting for Odysseus would buy nothing (ws-bd 8.1).
    """
    return (
        ReplyTemplate(
            name=TEMPLATE_DEPOSIT,
            subject="{tour_name} {month_year} - {full_name}",
            body=DEPOSIT_BODY.replace("{deposit}", str(DEPOSIT_USD))
                             .replace("{payment_details}", PAYMENT_DETAILS),
        ),
        ReplyTemplate(
            name=TEMPLATE_QUOTE,
            subject="{tour_name} for {party_size} PAX - {full_name}",
            body=QUOTE_BODY,
        ),
    )


# The two placeholders a pricing run is not allowed to fill.
#
# A run reads a tour and a party size and never a person, so it cannot know
# either of these — see the gate note in `offer_jobs`. It leaves them, and the
# website substitutes them from the registration it is already displaying.
NAME_PLACEHOLDERS = ("{first_name}", "{full_name}")


def render_quote(*, tour_name: str, party_size: int, ask_to_confirm: bool,
                 first_name: Optional[str] = None,
                 full_name: Optional[str] = None,
                 operator: str = "") -> ReplyTemplate:
    """
    Post: the quote, filled except for the names the caller withheld.

    Pre:  `party_size` is 1 or more, and `tour_name` is not empty.

    Post: the body holds no placeholder except the name ones the caller left
          by passing None. An unfilled placeholder reaching a customer is worse
          than an error here.

    Pass `first_name=None` from a pricing run. The run has no name to fill and
    must not acquire one: reading the registrant would arm the external-context
    gate and forbid the same run from reporting its answer (ws-bd D6). The
    website fills both before an operator copies the text.

    The price is not a parameter. It rides in the attached itinerary, as every
    observed send did. A number in the body that disagrees with the document is
    a number the customer will find.
    """
    keep_names = first_name is None
    rate_line = ""
    if party_size > 1:
        rate_line = f" The rates are for {party_size} passengers (PAX)."
    body = (QUOTE_BODY
            .replace("{first_name}", "{first_name}" if keep_names else first_name)
            .replace("{tour_name}", tour_name)
            .replace("{rate_line}", rate_line)
            .replace("{confirm_block}", CONFIRM_BLOCK if ask_to_confirm else "")
            .replace("{signature}", signature_for(operator)))

    left = set(re.findall(r"\{[a-z_]+\}", body))
    if keep_names:
        left -= set(NAME_PLACEHOLDERS)
    if left:
        raise UnfilledPlaceholder(
            f"quote body still holds {', '.join(sorted(left))}")

    subject = tour_name
    if party_size > 1:
        subject = f"{tour_name} for {party_size} PAX"
    who = "{full_name}" if keep_names else (full_name or "").strip()
    if who:
        subject = f"{subject} - {who}"
    return ReplyTemplate(name=TEMPLATE_QUOTE, subject=subject, body=body)
