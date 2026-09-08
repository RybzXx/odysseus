"""
services/itinerary/offer_run.py

One press of the create button: seven steps, and a record of all of them.

The steps are read, extract, brief, candidates, check, rank, review. Four are
deterministic and three call a model. Every step writes what it did into the
run record, whether it ran or not, so a reader can tell an itinerary that was
reasoned about from one that was not (ws-03 D42, D43).

No step here builds a document. Button 1 makes a proposal and button 2 makes
the document, which is why the create button never reaches Drive (item 23.1).

Layer 2 chooses. Layer 3 comments and never stops anything (ws-03 D41). The
human is the gate, which is D15.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

RANK_TIMEOUT_SECONDS = 180
REVIEW_TIMEOUT_SECONDS = 180

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


class RankError(Exception):
    """Layer 2 could not choose, and the reason is stated."""


class ReviewError(Exception):
    """Layer 3 could not read the result, and the reason is stated."""


@dataclass
class Ranking:
    """Which candidate layer 2 chose, and why."""
    index: int                # 1-based, into the candidate list
    reason: str = ""
    where: str = ""
    chose_by_default: bool = False   # the layer did not run, so candidate 1 stands


@dataclass
class RunOutcome:
    """Everything one press produced."""
    run: object                       # ItineraryRun
    draft: object                     # ItineraryDraft
    brief: Optional[object] = None    # RequestBrief
    candidate_set: Optional[object] = None
    ranking: Optional[Ranking] = None
    review_note: str = ""
    chosen_codes: list = field(default_factory=list)


# ── layer 2, the ranking ─────────────────────────────────────────────────────

def what_the_customer_asked_for(brief) -> dict:
    """
    Post: the brief's named fields, as a reader of a prompt receives them.

    Pre:  `brief` is a RequestBrief, or None when layer 1 did not run.

    The named fields and not the prose. Layer 1 answers the fields the same way
    every time at temperature zero, and it writes a different paragraph on
    every call: one prompt gave three different summaries across three
    processes while the day count, the party size and the eight named sites
    were identical (measured 2026-09-08). A decision routed through the
    paragraph therefore moved with the paragraph, and the itinerary changed
    with it.

    The summary is still carried, because a reviewer reads it. It is no longer
    the only thing layer 2 has.
    """
    if brief is None:
        return {}
    named = {
        "days_asked": getattr(brief, "day_count", None),
        "travellers": getattr(brief, "party_size", None),
        "regions_named": list(getattr(brief, "regions", []) or []),
        "places_named": list(getattr(brief, "must_see_sites", []) or []),
        "interests": list(getattr(brief, "interests", []) or []),
        "start_date": getattr(brief, "start_date", "") or "",
        "in_their_own_words": getattr(brief, "summary", "") or "",
    }
    return {key: value for key, value in named.items()
            if value not in (None, "", [])}


def build_rank_prompt(brief, candidate_set) -> list:
    """
    Post: the messages layer 2 receives.

    Pre:  `brief` is a RequestBrief, or None when layer 1 did not run.

    Every candidate arrives with its day codes, its day shortfall and its
    faults. A ranker that received the sequences and not the faults would rank
    on wording, and the checks are the work phase four did.
    """
    rows = []
    for candidate in candidate_set.candidates:
        check = candidate.check
        rows.append({
            "candidate": candidate.index,
            "route": candidate.route_name,
            "days_delivered": len(candidate.day_codes),
            "days_asked": candidate.asked_days,
            "days_short": candidate.day_shortfall,
            "day_codes": list(candidate.day_codes),
            "faults": [f.statement for f in getattr(check, "faults", []) or []],
            "flags": [f.statement for f in getattr(check, "flags", []) or []],
            "not_covered": list(candidate.gap_notes),
        })
    system = (
        "You choose one itinerary from a numbered list for a tour operator in "
        "Iraq. Every itinerary was built by the operator's own rules, so every "
        "day code is real and you never invent one.\n\n"
        "Answer with one JSON object and nothing else:\n"
        '  {"candidate": <number>, "reason": "<one paragraph>"}\n\n'
        "Judge on three things, in this order:\n"
        "1. How well it answers what the customer asked for.\n"
        "2. How many days it delivers against the days they asked for. An "
        "itinerary three days short is a worse offer.\n"
        "3. The faults and flags. A fault is a repeat or a drive the operator "
        "does not make. A flag is worth stating and is not a refusal.\n\n"
        "Choose the number of one candidate on the list. Choose nothing else."
    )
    asked = what_the_customer_asked_for(brief)
    user = (f"What the customer asked for:\n"
            f"{json.dumps(asked, ensure_ascii=False, indent=2) if asked else '(no brief)'}"
            f"\n\nThe candidates:\n"
            f"{json.dumps(rows, ensure_ascii=False, indent=2)}\n\nChoose one.")
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def parse_ranking(raw: str, candidate_count: int) -> Ranking:
    """
    Post: a Ranking naming a candidate inside the list.

    Blame: an answer outside the range is a model error and raises. The caller
    records the failure and keeps candidate 1, which the record states (item
    20.3). A silent substitution would read as a choice nobody made.
    """
    found = _JSON_BLOCK.search(raw or "")
    if not found:
        raise RankError("layer 2 did not answer with JSON")
    try:
        answer = json.loads(found.group(0))
    except json.JSONDecodeError as exc:
        raise RankError(f"layer 2's JSON did not parse: {exc}") from exc
    named = answer.get("candidate")
    # `int(True)` is 1 and `int(1.9)` is 1, so a boolean and a float both read
    # as candidate 1. A model that answered either did not choose a candidate,
    # and reading it as the first one is a choice nobody made.
    if isinstance(named, bool) or not isinstance(named, (int, str)):
        raise RankError(f"layer 2 named {named!r}, which is not a candidate "
                        f"number")
    try:
        index = int(str(named).strip())
    except (TypeError, ValueError) as exc:
        raise RankError(
            f"layer 2 named {named!r}, which is not a candidate number") from exc
    if not 1 <= index <= candidate_count:
        raise RankError(f"layer 2 chose candidate {index} of {candidate_count}")
    return Ranking(index=index, reason=str(answer.get("reason") or "").strip())


def rank_candidates(brief, candidate_set,
                    owner: Optional[str] = None) -> tuple:
    """
    Ask layer 2 to choose one candidate.

    Pre:  `candidate_set` holds at least one candidate.
    Post: (the ranking, the prompt, the raw answer).

    Blame: an unconfigured layer raises RankError with the refusal as its
    message. The caller keeps candidate 1 and records the step untested.
    """
    from services.itinerary.layer_access import LAYER_RANK, resolve_layer
    from src.llm_core import llm_call

    access = resolve_layer(LAYER_RANK, owner=owner)
    if not access.may_run:
        raise RankError(access.refusal)

    messages = build_rank_prompt(brief, candidate_set)
    try:
        raw = llm_call(access.url, access.model, messages,
                       headers=access.headers, temperature=0.0,
                       timeout=RANK_TIMEOUT_SECONDS)
    except Exception as exc:
        raise RankError(f"{access.where} did not answer: {exc}") from exc

    ranking = parse_ranking(raw, len(candidate_set.candidates))
    ranking.where = access.where
    return ranking, json.dumps(messages, ensure_ascii=False), raw or ""


# ── layer 3, the reading ─────────────────────────────────────────────────────

def build_review_prompt(brief, chosen, templates: dict) -> list:
    """
    Post: the messages layer 3 receives.

    It holds the brief and the chosen itinerary. It holds no other candidate,
    because layer 3 reads the result against the request and does not re-run
    the choice (item 21.1).
    """
    from services.itinerary.propose_sequence import field_of

    days = []
    for position, code in enumerate(chosen.day_codes, start=1):
        template = templates.get(code)
        days.append({
            "day": position,
            "code": code,
            "title": str(field_of(template, "title", "") or "") if template else "",
            "city": str(field_of(template, "city", "") or "") if template else "",
            "overnight": (str(field_of(template, "overnight_city", "") or "")
                          if template else ""),
        })
    system = (
        "You read one itinerary against one customer request for a tour "
        "operator in Iraq, and you say whether it answers the request.\n\n"
        "Answer with one JSON object and nothing else:\n"
        '  {"answers_the_request": true|false, "problems": ["..."], '
        '"note": "<one paragraph a reviewer reads>"}\n\n'
        "Name what the customer asked for and did not get. Name nothing else. "
        "You do not refuse this itinerary and you do not rewrite it. A human "
        "decides whether to build it."
    )
    asked = what_the_customer_asked_for(brief)
    user = (f"What the customer asked for:\n"
            f"{json.dumps(asked, ensure_ascii=False, indent=2) if asked else '(no brief)'}"
            f"\n\nThe itinerary that was chosen:\n"
            f"{json.dumps(days, ensure_ascii=False, indent=2)}\n\n"
            f"Does it answer the request?")
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def parse_review(raw: str) -> tuple:
    """
    Post: (the note a reviewer reads, the problems named).

    Blame: unparsable text is a model failure and raises. A review that cannot
    be read is not a review, and a caller that kept the raw text would put a
    model's whole answer into the notes card.
    """
    found = _JSON_BLOCK.search(raw or "")
    if not found:
        raise ReviewError("layer 3 did not answer with JSON")
    try:
        answer = json.loads(found.group(0))
    except json.JSONDecodeError as exc:
        raise ReviewError(f"layer 3's JSON did not parse: {exc}") from exc
    problems = answer.get("problems") or []
    if isinstance(problems, str):
        problems = [problems]
    problems = [str(p).strip() for p in problems if str(p).strip()]
    note = str(answer.get("note") or "").strip()
    if not note and problems:
        note = "; ".join(problems)
    return note, problems


def review_choice(brief, chosen, templates: dict,
                  owner: Optional[str] = None) -> tuple:
    """
    Ask layer 3 whether the chosen itinerary answers the request.

    Post: (the note, the problems, the prompt, the raw answer).
    Inv:  layer 3 never stops a build. Its answer becomes a note and nothing
          else reads it as a gate (ws-03 D41, item 21.3).
    """
    from services.itinerary.layer_access import LAYER_REVIEW, resolve_layer
    from src.llm_core import llm_call

    access = resolve_layer(LAYER_REVIEW, owner=owner)
    if not access.may_run:
        raise ReviewError(access.refusal)

    messages = build_review_prompt(brief, chosen, templates)
    try:
        raw = llm_call(access.url, access.model, messages,
                       headers=access.headers, temperature=0.0,
                       timeout=REVIEW_TIMEOUT_SECONDS)
    except Exception as exc:
        raise ReviewError(f"{access.where} did not answer: {exc}") from exc

    note, problems = parse_review(raw)
    return note, problems, json.dumps(messages, ensure_ascii=False), raw or ""


# ── the run ──────────────────────────────────────────────────────────────────

def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def create_offer(draft, templates: dict, owner: Optional[str] = None,
                 force_read: bool = False) -> RunOutcome:
    """
    Run the seven steps for one draft, and record every one of them.

    Pre:  `draft` exists and holds the raw submitted record. `templates` holds
          only active codes.
    Post: a RunOutcome. The chosen sequence is on the draft with
          `source=model`, layer 3's note is on `notes`, and the run record is
          sealed. No document is built and Drive holds no new file.
    Inv:  a step that could not run records itself and the run continues
          (ws-03 D43). A request whose conversation was never read produces a
          proposal, and the record says the conversation was never read
          (invariant 3.5).

    Blame: this raises only when the draft cannot be saved. A shut folder, an
    unconfigured layer and a model that answers badly are all recorded and the
    run finishes, because every conversation folder answered 404 until the
    owner shared them and a run that refused would refuse every request.
    """
    from services.itinerary import run_record as runs

    run = runs.start_run(draft.draft_id, request_key=draft.request_id)
    outcome = RunOutcome(run=run, draft=draft)
    try:
        return _run_the_steps(outcome, draft, templates, owner, force_read)
    finally:
        # Whatever happened, the record closes. An unsealed record would sit
        # with its steps and no finish time, and it would accept more steps
        # forever (invariant 3.7). A step that raised is already recorded.
        if not run.is_sealed:
            runs.seal(run)


def _run_the_steps(outcome: RunOutcome, draft, templates: dict,
                   owner: Optional[str], force_read: bool) -> RunOutcome:
    """
    The seven steps. `create_offer` owns the record and seals it.

    Pre:  `outcome.run` is open, and the caller seals it whatever this raises.
    Post: the RunOutcome. This never seals, because a caller that sealed here
          and raised later would have two places to keep in step.
    """
    from services.itinerary import run_record as runs
    from services.itinerary.candidates import (
        build_candidates,
        candidate_set_to_dict,
        check_candidates,
    )
    from services.itinerary.conversation_reader import (
        conversation_link_of,
        read_conversation,
    )
    from services.itinerary.drafts import (
        NOTE_SOURCE_MODEL,
        SOURCE_MODEL,
        ProposedSequence,
        add_note,
        add_run_id,
        add_sequence,
    )
    from services.itinerary.normalizer import normalize_from_dict
    from services.itinerary.request_brief import (
        BriefError,
        apply_brief,
        brief_to_dict,
        write_brief,
    )

    run = outcome.run
    request = normalize_from_dict(draft.draft_id, draft.request_row,
                                  source=draft.origin)

    # 1. the link ────────────────────────────────────────────────────────────
    link = conversation_link_of(draft.request_row)
    if link:
        runs.record_step(run, runs.STEP_READ_LINK, runs.OUTCOME_DONE,
                         statement=f"the request points at {link}",
                         result={"link": link})
    else:
        runs.untested_step(run, runs.STEP_READ_LINK,
                           "the request carries no conversation link")

    # 2. the screenshots ─────────────────────────────────────────────────────
    started = time.perf_counter()
    conversation = read_conversation(draft.request_row, owner=owner,
                                     force=force_read)
    if conversation.was_read:
        runs.record_step(
            run, runs.STEP_EXTRACT, runs.OUTCOME_DONE,
            statement=conversation.statement,
            where=next((i.where for i in conversation.images if i.where), ""),
            answer=conversation.text, ms=_elapsed_ms(started),
            result={"images": len(conversation.images),
                    "untested": conversation.untested})
    else:
        runs.untested_step(
            run, runs.STEP_EXTRACT,
            "; ".join(conversation.untested) or "no screenshot was read")

    # 3. layer 1 ─────────────────────────────────────────────────────────────
    started = time.perf_counter()
    try:
        brief, prompt, raw = write_brief(request, conversation.text, owner=owner)
        apply_brief(brief, request, draft.request_row)
        outcome.brief = brief
        runs.record_step(run, runs.STEP_BRIEF, runs.OUTCOME_DONE,
                         statement=brief.statement, where=brief.where,
                         prompt=prompt, answer=raw, ms=_elapsed_ms(started),
                         result=brief_to_dict(brief))
    except BriefError as exc:
        runs.untested_step(run, runs.STEP_BRIEF, str(exc))
    except Exception as exc:                       # noqa: BLE001
        logger.exception("layer 1 failed")
        runs.record_step(run, runs.STEP_BRIEF, runs.OUTCOME_FAILED,
                         statement=str(exc), ms=_elapsed_ms(started))

    # The brief itself reaches layers 2 and 3, not its prose. Its named
    # fields repeat at temperature zero and its paragraph does not.

    # 4. the candidates, and 5. the checks ───────────────────────────────────
    started = time.perf_counter()
    candidate_set = build_candidates(request, templates)
    outcome.candidate_set = candidate_set
    if candidate_set.is_empty:
        runs.untested_step(run, runs.STEP_CANDIDATES,
                           "; ".join(candidate_set.untested) or "no candidate")
        runs.untested_step(run, runs.STEP_CHECK, "there is no candidate to check")
        runs.untested_step(run, runs.STEP_RANK, "there is no candidate to choose")
        runs.untested_step(run, runs.STEP_REVIEW, "there is no itinerary to read")
        return outcome

    runs.record_step(run, runs.STEP_CANDIDATES, runs.OUTCOME_DONE,
                     statement=candidate_set.statement, ms=_elapsed_ms(started),
                     result={"tied_routes": candidate_set.tied_routes,
                             "built": len(candidate_set.candidates),
                             "untested": candidate_set.untested})

    started = time.perf_counter()
    check_candidates(candidate_set, templates, start_date=request.start_date,
                     request_row=draft.request_row, day_count=request.day_count)
    runs.record_step(run, runs.STEP_CHECK, runs.OUTCOME_DONE,
                     statement=(f"{len(candidate_set.candidates)} candidate(s) "
                                f"checked"),
                     ms=_elapsed_ms(started),
                     result=candidate_set_to_dict(candidate_set))

    # 6. layer 2 ─────────────────────────────────────────────────────────────
    started = time.perf_counter()
    ranking = Ranking(index=1, reason="", chose_by_default=True)
    try:
        ranking, prompt, raw = rank_candidates(outcome.brief, candidate_set,
                                               owner=owner)
        runs.record_step(run, runs.STEP_RANK, runs.OUTCOME_DONE,
                         statement=(f"chose candidate {ranking.index} of "
                                    f"{len(candidate_set.candidates)}"),
                         where=ranking.where, prompt=prompt, answer=raw,
                         ms=_elapsed_ms(started),
                         result={"candidate": ranking.index,
                                 "reason": ranking.reason})
    except RankError as exc:
        runs.untested_step(
            run, runs.STEP_RANK,
            f"{exc}. Candidate 1 stands, because the rules ordered it first")
    except Exception as exc:                       # noqa: BLE001
        logger.exception("layer 2 failed")
        runs.record_step(run, runs.STEP_RANK, runs.OUTCOME_FAILED,
                         statement=f"{exc}. Candidate 1 stands",
                         ms=_elapsed_ms(started))

    outcome.ranking = ranking
    chosen = candidate_set.candidates[ranking.index - 1]
    outcome.chosen_codes = list(chosen.day_codes)

    # 7. layer 3 ─────────────────────────────────────────────────────────────
    started = time.perf_counter()
    try:
        note, problems, prompt, raw = review_choice(outcome.brief, chosen,
                                                    templates, owner=owner)
        outcome.review_note = note
        runs.record_step(run, runs.STEP_REVIEW, runs.OUTCOME_DONE,
                         statement=(f"{len(problems)} problem(s) named"),
                         prompt=prompt, answer=raw, ms=_elapsed_ms(started),
                         result={"note": note, "problems": problems})
    except ReviewError as exc:
        runs.untested_step(run, runs.STEP_REVIEW, str(exc))
    except Exception as exc:                       # noqa: BLE001
        logger.exception("layer 3 failed")
        runs.record_step(run, runs.STEP_REVIEW, runs.OUTCOME_FAILED,
                         statement=str(exc), ms=_elapsed_ms(started))

    # what the run leaves on the draft ───────────────────────────────────────
    #
    # A draft somebody deleted mid-run raises DraftError here. `create_offer`
    # seals the record in its own `finally`, so the failure reaches the caller
    # and the record still closes.
    reason = ranking.reason or (
        "the rules ordered this candidate first, and layer 2 did not run")
    draft = add_sequence(draft.draft_id, ProposedSequence(
        source=SOURCE_MODEL,
        day_codes=list(chosen.day_codes),
        note=f"candidate {ranking.index} of {len(candidate_set.candidates)}. "
             f"{chosen.statement}. {reason}",
        model=ranking.where, endpoint=""))
    draft = add_run_id(draft.draft_id, run.run_id)
    if outcome.review_note:
        draft = add_note(draft.draft_id, outcome.review_note, NOTE_SOURCE_MODEL)
    outcome.draft = draft
    return outcome
