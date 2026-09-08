"""The review pass: a model re-reads how the rules categorised recent mail.

The pass never assigns a category. It raises contests -- questions a human
answers -- so the rules stay the only thing that decides membership without a
human in the loop. Two kinds of doubt reach the queue:

  * an organiser claims an email and the reviewer disagrees (an asserted claim
    the human can reject), and
  * no organiser claims an email and the reviewer names one (a proposed claim
    the human can confirm).

Only a cloud endpoint may serve the pass. A local model runs on the same
machine as the mail index, and this is the one workload that reads whole
inboxes on a schedule rather than on request.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import or_

from core.database import (
    CategorisationContest,
    MessageReview,
    ModelEndpoint,
    utcnow_naive,
)
from services.organisers.contests import (
    ASSERTED,
    OPEN,
    PROPOSED,
    SOURCE_REVIEW,
    load_contests,
)
from services.organisers.match_detail import evaluate_rules

logger = logging.getLogger(__name__)

# How many messages one pass sends. The reviewer reads the residue and the weak
# matches, not the whole corpus, so this bounds a bad day rather than a normal
# one.
MAX_REVIEW_BATCH = 80

# How much of a message the reviewer sees. Enough to judge what it is about.
SNIPPET_CHARS = 300


class ReviewUnavailable(RuntimeError):
    """The pass cannot run as configured. Carries a reason fit to show a user."""


def rules_digest(organisers: Iterable[Any]) -> str:
    """A short fingerprint of the taxonomy a verdict was made against.

    Post: the same string for the same rules whatever order the organisers
          arrive in, and a different one after any edit to slugs or rules.
    Inv:  this is the whole test for whether a past review still applies. It
          covers what the reviewer was shown -- the slugs and their rules --
          and nothing else, so cosmetic edits like a colour do not force a
          re-read that would cost tokens and change no verdict.
    """
    parts = []
    for org in organisers:
        try:
            rules = json.loads(org.rules_json or "{}")
        except (TypeError, ValueError):
            rules = {}
        parts.append({
            "slug": org.slug,
            "senders": sorted(rules.get("senders") or []),
            "domains": sorted(rules.get("domains") or []),
            "keywords": sorted(rules.get("keywords") or []),
        })
    parts.sort(key=lambda p: p["slug"])
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def load_reviewed(db, owner: Optional[str], digest: str) -> Set[Tuple[str, str]]:
    """The messages already reviewed against this taxonomy.

    Pre:  digest is rules_digest over the current organisers.
    Post: the (account_key, uid) pairs whose review still applies. A row made
          against different rules is absent, so the pass reads that message
          again rather than trusting a verdict about rules that have changed.
    """
    keys: Set[Tuple[str, str]] = set()
    try:
        rows = db.query(MessageReview.account_key, MessageReview.uid).filter(
            or_(MessageReview.owner == owner, MessageReview.owner == None),
            MessageReview.rules_digest == digest,
        ).all()
    except Exception:
        # The table postdates some databases; absent it, nothing was reviewed.
        return keys
    for account_key, uid in rows:
        keys.add((account_key or "", uid or ""))
    return keys


def record_reviews(
    db,
    owner: Optional[str],
    keys: Iterable[Tuple[str, str]],
    digest: str,
) -> int:
    """Mark these messages as examined against this taxonomy.

    Pre:  every key was in a batch the reviewer actually answered about.
    Post: one row per message, created or refreshed; returns how many were
          touched. Recorded whatever the verdict was, including agreement,
          because "looked at and accepted" is the fact the states need.
    """
    touched = 0
    for account_key, uid in keys:
        if not uid:
            continue
        row = db.query(MessageReview).filter(
            MessageReview.owner == owner,
            MessageReview.account_key == account_key,
            MessageReview.uid == uid,
        ).first()
        if row is None:
            db.add(MessageReview(
                id=uuid.uuid4().hex,
                owner=owner,
                account_key=account_key,
                uid=uid,
                reviewed_at=utcnow_naive(),
                rules_digest=digest,
            ))
        else:
            row.reviewed_at = utcnow_naive()
            row.rules_digest = digest
        touched += 1

    if touched:
        db.commit()
    return touched


def is_cloud_endpoint(base_url: str, endpoint_kind: Optional[str] = None) -> bool:
    """Whether calls to this endpoint leave the machine.

    Reuses the route classification the cost tracker already applies, which is
    the same question asked for a different reason: it returns False for
    loopback, ``.local``, private ranges and endpoints marked local, and True
    for a globally routable API. Duplicating the check here would let the two
    answers drift.
    """
    from src.endpoint_resolver import endpoint_cost_tracked

    return endpoint_cost_tracked(base_url, endpoint_kind)


def cloud_endpoints(db, owner: Optional[str]) -> List[ModelEndpoint]:
    """The endpoints a user may choose for the pass.

    Pre:  db is an open session.
    Post: enabled LLM endpoints that are cloud-routable, newest first. A local
          endpoint is absent from the list, so it cannot be selected at all.
    """
    from src.auth_helpers import owner_filter

    query = db.query(ModelEndpoint).filter(
        ModelEndpoint.is_enabled == True,
        ModelEndpoint.model_type != "image",
    )
    if owner:
        query = owner_filter(query, ModelEndpoint, owner)
    return [
        ep for ep in query.all()
        if is_cloud_endpoint(ep.base_url or "", ep.endpoint_kind)
    ]


def resolve_review_route(db, owner: Optional[str]) -> Tuple[str, str, Dict[str, str]]:
    """Resolve the endpoint, model and headers the pass will call.

    Pre:  settings name an endpoint id and model for the pass.
    Post: a chat URL, a model, and headers for a cloud endpoint.
    Raises ReviewUnavailable when the pass is off, unconfigured, or points at
    an endpoint that is not cloud -- all of which are configuration faults the
    caller should report rather than work around.
    """
    from src.endpoint_resolver import (
        build_chat_url,
        build_headers,
        resolve_endpoint_runtime,
    )
    from src.settings import get_user_setting, load_settings

    settings = load_settings()
    owner_str = owner or ""

    def _stg(key: str, default: Any = "") -> Any:
        return get_user_setting(key, owner_str, settings.get(key, default))

    if not _stg("organiser_review_enabled", False):
        raise ReviewUnavailable("The organiser review pass is switched off in settings.")

    endpoint_id = (_stg("organiser_review_endpoint_id") or "").strip()
    model = (_stg("organiser_review_model") or "").strip()
    if not endpoint_id or not model:
        raise ReviewUnavailable("No endpoint and model are chosen for the organiser review pass.")

    endpoint = db.query(ModelEndpoint).filter(
        ModelEndpoint.id == endpoint_id,
        ModelEndpoint.is_enabled == True,
    ).first()
    if endpoint is None:
        raise ReviewUnavailable("The chosen review endpoint no longer exists or is disabled.")

    # Checked again here, not only in the picker: an endpoint can be edited to
    # point at a local server after it was selected.
    if not is_cloud_endpoint(endpoint.base_url or "", endpoint.endpoint_kind):
        raise ReviewUnavailable(
            f"'{endpoint.name}' is a local endpoint. The review pass runs on cloud models only."
        )

    base, api_key = resolve_endpoint_runtime(endpoint, owner=owner)
    return build_chat_url(base), model, build_headers(api_key, base)


def select_review_batch(
    emails: List[Dict[str, Any]],
    organisers: Iterable[Any],
    overrides: Dict[Tuple[str, str], Dict[str, Any]],
    *,
    limit: int = MAX_REVIEW_BATCH,
    already_reviewed: Optional[Set[Tuple[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """The messages worth spending tokens on.

    Pre:  organisers carry rules_json and target_accounts as stored;
          already_reviewed holds keys whose review still applies to the current
          rules, as load_reviewed returns.
    Post: messages that no rule claims, or that only a weak rule claims, up to
          `limit`. Excluded are messages a human has judged, strong matches --
          a sender or domain rule is not worth re-reading -- and messages
          already reviewed against these same rules.
    Inv:  a message appears at most once however many organisers touch it. A
          message re-enters the batch only when the rules it was judged against
          have changed, which is what keeps a steady state costing nothing.
    """
    parsed = []
    for org in organisers:
        try:
            parsed.append((
                org,
                json.loads(org.rules_json or "{}"),
                json.loads(org.target_accounts or "[]"),
            ))
        except (TypeError, ValueError):
            continue

    reviewed = already_reviewed or set()
    batch: List[Dict[str, Any]] = []
    for email in emails:
        if len(batch) >= limit:
            break
        key = (
            str(email.get("account_key") or email.get("account_id") or ""),
            str(email.get("uid") or ""),
        )
        if key in reviewed:
            continue
        entry = overrides.get(key)
        if entry and entry.get("assigned"):
            continue

        strongest = "none"
        for org, rules, accounts in parsed:
            if entry and org.id in entry.get("excluded", ()):
                continue
            match = evaluate_rules(email, accounts, rules)
            if match.strength == "strong":
                strongest = "strong"
                break
            if match.is_weak:
                strongest = "weak"

        if strongest != "strong":
            batch.append(email)

    return batch


def build_review_prompt(
    emails: List[Dict[str, Any]],
    organisers: Iterable[Any],
) -> List[Dict[str, str]]:
    """The messages sent to the reviewer.

    Post: a system prompt that asks only for verdicts on existing categories,
          and a user turn holding the taxonomy and the batch.
    Inv:  the schema offers no way to invent a category. The reviewer judges
          the taxonomy the human built; proposing a new one is a separate
          decision the calibration studio already owns.
    """
    taxonomy = []
    for org in organisers:
        try:
            rules = json.loads(org.rules_json or "{}")
        except (TypeError, ValueError):
            rules = {}
        taxonomy.append({
            "slug": org.slug,
            "name": org.name,
            "description": org.description or "",
            "rules": rules,
        })

    batch = [
        {
            "account_key": str(e.get("account_key") or ""),
            "uid": str(e.get("uid") or ""),
            "from_name": e.get("from_name") or "",
            "from_address": e.get("from_address") or "",
            "subject": e.get("subject") or "",
            "snippet": (e.get("snippet") or "")[:SNIPPET_CHARS],
            "folder": e.get("folder") or "INBOX",
        }
        for e in emails
    ]

    system = (
        "You review how a set of deterministic rules categorised a person's email.\n"
        "The rules decide; you do not. Your output is a list of doubts a human will settle.\n\n"
        "For each message, decide whether it belongs to one of the existing categories.\n"
        "Report a verdict ONLY when you have a clear view. Say nothing about a message you "
        "cannot judge from what you were given -- silence is the correct answer for those.\n\n"
        "Return ONLY a JSON object matching this schema:\n"
        "{\n"
        '  "verdicts": [\n'
        "    {\n"
        '      "account_key": "...",\n'
        '      "uid": "...",\n'
        '      "category_slug": "one of the slugs given to you",\n'
        '      "belongs": true,\n'
        '      "reason": "one clear sentence saying why"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Use belongs=true to say a message should be in that category. "
        "Use belongs=false to say a message should NOT be, when a rule has put it there wrongly."
    )

    user = (
        f"CATEGORIES:\n{json.dumps(taxonomy, ensure_ascii=False, indent=2)}\n\n"
        f"MESSAGES ({len(batch)}):\n{json.dumps(batch, ensure_ascii=False, indent=2)}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Pull one JSON object out of a model's reply.

    Pre:  raw_text is whatever the model returned.
    Post: the parsed object, or an empty dict when nothing parses. Handles a
          fenced block and surrounding prose, both of which models emit even
          when asked not to.
    """
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start:end + 1])
    except (TypeError, ValueError) as e:
        logger.warning("Organiser review returned unparsable JSON: %s", e)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def raise_review_contests(
    db,
    owner: Optional[str],
    raw_text: str,
    emails: List[Dict[str, Any]],
    organisers: Iterable[Any],
    overrides: Dict[Tuple[str, str], Dict[str, Any]],
) -> int:
    """Turn a reviewer's verdicts into contests a human can settle.

    Pre:  raw_text is the reply to build_review_prompt over `emails`.
    Post: an open contest per verdict that disagrees with the rules and has no
          verdict already; returns how many were opened. Nothing is written for
          a verdict that merely agrees with what the rules already do.
    Inv:  no category is assigned here. A contest records a question; only
          resolve_contest changes membership, and only on a human's word.
    """
    parsed = extract_json_object(raw_text)
    verdicts = parsed.get("verdicts")
    if not isinstance(verdicts, list):
        return 0

    org_by_slug = {org.slug: org for org in organisers}
    email_by_key = {
        (str(e.get("account_key") or ""), str(e.get("uid") or "")): e
        for e in emails
    }
    existing = {
        (c.account_key or "", c.uid or "", c.organiser_id)
        for contests in load_contests(db, owner, state=None).values()
        for c in contests
    }

    opened = 0
    for item in verdicts:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("category_slug") or "").strip()
        org = org_by_slug.get(slug)
        if org is None:
            continue

        key = (str(item.get("account_key") or ""), str(item.get("uid") or ""))
        email = email_by_key.get(key)
        if email is None or not key[1] or (key[0], key[1], org.id) in existing:
            continue

        try:
            rules = json.loads(org.rules_json or "{}")
            accounts = json.loads(org.target_accounts or "[]")
        except (TypeError, ValueError):
            continue

        rules_match = evaluate_rules(email, accounts, rules).matched
        belongs = bool(item.get("belongs"))

        # Agreement is not a contest. Only a disagreement is worth a question.
        if belongs == rules_match:
            continue

        db.add(CategorisationContest(
            id=uuid.uuid4().hex,
            owner=owner,
            account_key=key[0],
            uid=key[1],
            organiser_id=org.id,
            claim=ASSERTED if rules_match else PROPOSED,
            source=SOURCE_REVIEW,
            evidence_json=json.dumps(
                {"belongs": belongs, "rules_match": rules_match}, ensure_ascii=False,
            ),
            reason=str(item.get("reason") or "").strip()[:500]
                   or ("The reviewer disagrees with the rule that claims this message."
                       if rules_match else
                       "The reviewer places this message here, where no rule reaches it."),
            state=OPEN,
        ))
        existing.add((key[0], key[1], org.id))
        opened += 1

    if opened:
        db.commit()
    return opened


async def run_review_pass(
    db,
    owner: Optional[str],
    emails: List[Dict[str, Any]],
    organisers: List[Any],
    overrides: Dict[Tuple[str, str], Dict[str, Any]],
) -> Dict[str, Any]:
    """Run one review pass end to end.

    Pre:  the pass is enabled and points at a cloud endpoint.
    Post: contests exist for every disagreement the reviewer found, and every
          message in the batch is recorded as examined; returns a summary.
    Inv:  a failure leaves every existing contest, override and review record
          untouched. The pass either adds questions or does nothing -- nothing
          is marked reviewed unless the reviewer actually answered.

    Raises ReviewUnavailable on a configuration fault.
    """
    from src.llm_core import llm_call_async

    digest = rules_digest(organisers)
    reviewed = load_reviewed(db, owner, digest)
    batch = select_review_batch(
        emails, organisers, overrides, already_reviewed=reviewed,
    )
    if not batch:
        return {
            "examined": 0,
            "opened": 0,
            "reason": "Nothing new to review: every message is either strongly matched or already read.",
        }

    url, model, headers = resolve_review_route(db, owner)
    messages = build_review_prompt(batch, organisers)

    raw = await llm_call_async(
        url,
        model,
        messages,
        headers=headers,
        temperature=0,
        workload="background",
    )
    if isinstance(raw, tuple):
        raw = raw[0]

    opened = raise_review_contests(db, owner, raw, batch, organisers, overrides)

    # Recorded after the reply lands, so a failed call leaves the batch
    # unreviewed and the next pass reads it again.
    record_reviews(
        db, owner,
        [(str(e.get("account_key") or ""), str(e.get("uid") or "")) for e in batch],
        digest,
    )
    return {"examined": len(batch), "opened": opened, "model": model}
