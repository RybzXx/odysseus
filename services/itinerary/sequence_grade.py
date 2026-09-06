"""
services/itinerary/sequence_grade.py

Scoring a proposed day-code sequence against the offer that was actually sent.

The sent offer is the answer key. It is what a human wrote and a customer
received, so a proposal can be marked against it rather than only set beside a
second proposal (ws-03 D27).

The comparison is on overnight cities, not on day codes. A sent offer carries
the city each day ends in, because extraction reads it from the day's own text.
It carries no codes: it was written by hand, before the catalogue existed in
this form. A proposed code does carry a city, through the template it names. So
the two meet at the city, and nothing here guesses a code the offer never had.

Nothing in this module calls a model. It scores an answer a model or the rules
already gave.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# What one position is worth. A position is one night of the trip.
POSITION_SAME = "same"              # the proposal and the offer name one city
POSITION_DIFFER = "differ"          # both name a city, and the two disagree
POSITION_ONLY_PROPOSED = "only_proposed"   # the proposal runs past the offer
POSITION_ONLY_SENT = "only_sent"    # the offer runs past the proposal
POSITION_UNKNOWN = "unknown"        # the proposed code names no overnight city


@dataclass
class GradedPosition:
    """One night, as the proposal had it and as the offer had it."""
    night: int                      # 1-based, counting the nights that were named
    verdict: str
    proposed_code: str = ""
    proposed_city: str = ""
    sent_city: str = ""


@dataclass
class SequenceGrade:
    """
    One proposal marked against one sent offer.

    `matched` counts the nights the proposal put in the right city. It is a
    count and a denominator, like every other measurement in this workstream, so
    a reader can check it without the code that produced it.
    """
    source: str = ""                # which proposer answered
    offer_message_id: str = ""
    offer_attachment: str = ""
    positions: list = field(default_factory=list)
    matched: int = 0
    nights_sent: int = 0
    nights_proposed: int = 0
    unknown_codes: list = field(default_factory=list)

    @property
    def share(self) -> float:
        """Post: matched over the nights the offer actually named."""
        return self.matched / self.nights_sent if self.nights_sent else 0.0

    @property
    def day_count_agrees(self) -> bool:
        return self.nights_proposed == self.nights_sent

    @property
    def statement(self) -> str:
        return (f"{self.source or 'the proposal'} put {self.matched} of "
                f"{self.nights_sent} night(s) in the city the offer used")


def _overnight_city_of(template) -> str:
    """Post: the template's overnight city, or "" for a day trip or departure."""
    from services.itinerary.propose_sequence import field_of

    return str(field_of(template, "overnight_city", "") or "").strip()


def _normalise(city: str) -> str:
    """
    Post: one city name, comparable across the two sources.

    The offer's city comes from `rule_counter.canonical_city`, which already
    merges the corpus's 38 spellings into about a dozen places. The template's
    city is the catalogue spelling. Passing both through one reader is what
    stops "Sulaymaniya" and "Sulaymaniyah" reading as two different nights.
    """
    from services.offers.rule_counter import canonical_city

    return (canonical_city(city) or city.strip()).casefold()


def grade_sequence(day_codes, templates: dict, offer,
                   source: str = "") -> SequenceGrade:
    """
    Mark one proposed sequence against one sent offer.

    Pre:  `day_codes` is the proposal, in order. `templates` maps code to the
          template row it names. `offer` is a stored SentOffer, whose days carry
          the overnight city extraction read from them.
    Post: one verdict per night, and a count of the nights the proposal placed
          in the city the offer used. The offer is never changed.

    Blame: a code the catalogue does not hold is named in `unknown_codes` and
    its night reads `unknown`, rather than counting as a miss. A missing
    template is a catalogue problem, and scoring it as a wrong answer would
    blame the proposer for it.
    """
    sent_cities = [day.overnight_city for day in offer.days if day.overnight_city]
    grade = SequenceGrade(
        source=source,
        offer_message_id=offer.message_id,
        offer_attachment=offer.attachment_name,
        nights_sent=len(sent_cities),
    )

    proposed = []
    for code in (day_codes or []):
        template = templates.get(code)
        if template is None:
            grade.unknown_codes.append(code)
            proposed.append((code, None))
            continue
        city = _overnight_city_of(template)
        # A day trip and a departure day carry no overnight city, so they are
        # not nights and do not take a position in this comparison.
        if city:
            proposed.append((code, city))
    grade.nights_proposed = sum(1 for _, city in proposed if city)

    nights = [(code, city) for code, city in proposed if city]
    for index in range(max(len(nights), len(sent_cities))):
        night = index + 1
        has_proposed = index < len(nights)
        has_sent = index < len(sent_cities)
        if has_proposed and has_sent:
            code, city = nights[index]
            sent = sent_cities[index]
            same = _normalise(city) == _normalise(sent)
            if same:
                grade.matched += 1
            grade.positions.append(GradedPosition(
                night=night,
                verdict=POSITION_SAME if same else POSITION_DIFFER,
                proposed_code=code, proposed_city=city, sent_city=sent))
        elif has_proposed:
            code, city = nights[index]
            grade.positions.append(GradedPosition(
                night=night, verdict=POSITION_ONLY_PROPOSED,
                proposed_code=code, proposed_city=city))
        else:
            grade.positions.append(GradedPosition(
                night=night, verdict=POSITION_ONLY_SENT,
                sent_city=sent_cities[index]))

    for code in grade.unknown_codes:
        grade.positions.append(GradedPosition(
            night=0, verdict=POSITION_UNKNOWN, proposed_code=code))
    return grade


def format_grade(grade: SequenceGrade) -> str:
    """The grade as a reader marks it, night by night."""
    lines = [
        f"{grade.statement}"
        f"  ({grade.share:.0%}, {grade.nights_proposed} night(s) proposed)"
    ]
    if not grade.day_count_agrees:
        lines.append(f"  the day count disagrees: proposed {grade.nights_proposed}, "
                     f"sent {grade.nights_sent}")
    for position in grade.positions:
        if position.verdict == POSITION_SAME:
            lines.append(f"  {position.night:2d}. same    {position.proposed_code} "
                         f"-> {position.sent_city}")
        elif position.verdict == POSITION_DIFFER:
            lines.append(f"  {position.night:2d}. differ  {position.proposed_code} "
                         f"-> {position.proposed_city}, the offer used {position.sent_city}")
        elif position.verdict == POSITION_ONLY_PROPOSED:
            lines.append(f"  {position.night:2d}. extra   {position.proposed_code} "
                         f"-> {position.proposed_city}, the offer had no such night")
        elif position.verdict == POSITION_ONLY_SENT:
            lines.append(f"  {position.night:2d}. missing the offer used "
                         f"{position.sent_city}, the proposal had no such night")
        else:
            lines.append(f"      unknown {position.proposed_code} "
                         f"is not in the catalogue")
    return "\n".join(lines)


def thread_as_text(thread, limit: int = 12) -> str:
    """
    Post: the recovered turns as plain text, oldest first, each labelled with
          the level it was quoted at.

    Oldest first, because a read works forward through a conversation. The HTML
    the parser returns is stripped here rather than stored stripped, so the
    turns keep their markup for any reader that wants it.
    """
    import html as _html
    import re as _re

    lines = []
    for turn in sorted(thread.quote_turns, key=lambda t: -t.level)[:limit]:
        text = _re.sub(r"<[^>]+>", " ", turn.body_html or "")
        text = _html.unescape(_re.sub(r"\s+", " ", text)).strip()
        if not text:
            continue
        who = turn.attribution or "unattributed"
        lines.append(f"[level {turn.level} | {who}] {text}")
    return "\n\n".join(lines)


def open_graded_draft(offer, thread=None):
    """
    Open the thread a graded read is recorded on.

    Pre:  `offer` is a stored SentOffer whose thread recovered.
    Post: a draft carrying the conversation and the offer's identity, with
          origin ORIGIN_GRADED. Re-opening the same offer returns the same
          thread, so a second grading pass adds to the record rather than
          starting a new one beside it.

    A graded draft is not a request. It exists so the human's correction lands
    on `comments` like every other piece of feedback, which is what puts it in
    front of the judged rule book (ws-03 10.6). `iter_drafts` leaves this origin
    out of the desk's request list.
    """
    from services.itinerary.drafts import ORIGIN_GRADED, open_draft
    from services.offers.offer_store import offer_slug
    from services.offers.offer_thread import thread_of

    thread = thread or thread_of(offer.message_id, offer.attachment_name)
    request_id = f"graded:{offer_slug(offer.message_id, offer.attachment_name)}"
    row = {
        "graded_offer": offer.message_id,
        "attachment": offer.attachment_name,
        "subject": offer.subject,
        "sent_at": offer.sent_at.isoformat() if offer.sent_at else "",
        "day_count": str(offer.day_count),
        "sent_nights": " -> ".join(offer.city_sequence),
        "thread": thread_as_text(thread) if thread else "",
    }
    return open_draft(row, origin=ORIGIN_GRADED, request_id=request_id)


def gradeable_offers(since=None) -> list:
    """
    The offers a read can be graded against.

    Pre:  the corpus holds the offers, and `fetch_sent_threads` captured their
          bodies.
    Post: offers that answered a request and whose thread recovered, so a read
          has an inbound message to work from and an answer key to be marked
          against.

    A first-contact offer is left out. It carries no request to read, so read
    one has nothing to take and the grade would score a proposal against a
    question nobody asked (ws-03 9.6).

    An offer that names no overnight city is left out too. It is the answer key,
    and a key with no answers scores every proposal at zero out of zero. Two of
    the 47 read that way: a one-day marshes tour, and a routing proposal whose
    days name no city at all.
    """
    from services.offers.offer_store import iter_offers
    from services.offers.offer_thread import thread_of

    ready = []
    for offer in iter_offers():
        if since is not None and (offer.sent_at is None or offer.sent_at < since):
            continue
        if not offer.days or not offer.city_sequence:
            continue
        thread = thread_of(offer.message_id, offer.attachment_name)
        if thread is None or not thread.recovered:
            continue
        ready.append(offer)
    return ready


READ_ONE = "read one: the first inbound turn alone"
READ_TWO = "read two: every turn before the offer"


def record_read(offer, day_codes, templates: dict, read: str,
                thread=None):
    """
    Store one read against a graded offer, with its grade.

    Pre:  `read` is READ_ONE or READ_TWO, and `day_codes` is the answer that
          read gave. `templates` maps code to template row.
    Post: the graded draft holds the read as a sequence, whose note is the grade
          night by night. The draft is created if this is the first read on it.

    Returns (draft, grade).

    Blame: the caller owes it that the read never saw the offer. Nothing here
    can check that, because the read happens in a session (ws-03 10.3, 10.7).
    """
    from services.itinerary.drafts import SOURCE_MODEL, ProposedSequence, add_sequence

    if read not in (READ_ONE, READ_TWO):
        raise ValueError(f"unknown read: {read!r}")

    draft = open_graded_draft(offer, thread)
    grade = grade_sequence(day_codes, templates, offer, source=read)
    draft = add_sequence(draft.draft_id, ProposedSequence(
        source=SOURCE_MODEL,
        day_codes=list(day_codes),
        note=format_grade(grade),
        in_reply_to=read,
    ))
    return draft, grade
