"""Install the three reviewed corrections without rewriting their evidence.

Pre: the release regressions passed and the data directory has a verified backup.
Post: each matching comment links to an executable check. All history survives.
A changed comment is a caller precondition failure and is left unprocessed.
"""
from __future__ import annotations

import hashlib

CORRECTIONS = {
    "cm-e718545a765a": {
        "sha256": "55978621aeb5cfdbb21f56623fb5f9138c08fe1b792cd1e6b99a9dff4478dd07",
        "statement": "Use SAFA only as a Baghdad excursion when the itinerary does not continue north. Use connected transit templates for Mosul and Erbil.",
        "enforced_by": "sequence_check.northbound_excursion",
        "regression": "test_safa_cannot_replace_northbound_transit",
    },
    "cm-14e3f1d7da6a": {
        "sha256": "f7665c57102586d6367beaf69f5f735fcfbdce4d1f159cc3ca736b58eec79a10",
        "statement": "A Central and Southern Iraq request must reach Nasiriyah and the marshes, then return to Baghdad. Measure region coverage from the bound itinerary.",
        "enforced_by": "sequence_check.region_coverage and southern_return",
        "regression": "test_baghdad_days_do_not_satisfy_a_southern_request",
    },
    "cm-5915b4cb9765": {
        "sha256": "e32ab7f6aaf76a1160d86233c68367ec05741d02e068f155465df03210408da3",
        "statement": "When regions are absent, apply the operator default: Baghdad, then south, then Mosul, then departure from Erbil. Validate the requested length and report unsupported connections.",
        "enforced_by": "sequence_check.default_route",
        "regression": "test_missing_regions_use_the_operator_default",
    },
}


def apply_reviewed_corrections() -> dict:
    """Write rules before changing comment state. Repeated calls are idempotent."""
    from services.itinerary.drafts import iter_comments, set_comment_rule_state, RULE_STATE_DRAFTED
    from services.offers.rule_book import (
        JudgedRule, load_judged_rule, rule_id_for_comment, save_judged_rule)

    report = {"processed": [], "unchanged": [], "mismatch": [], "retired": []}
    for comment in iter_comments():
        correction = CORRECTIONS.get(comment["comment_id"])
        if correction is None:
            continue
        if hashlib.sha256(comment["text"].encode()).hexdigest() != correction["sha256"]:
            report["mismatch"].append(comment["comment_id"])
            continue
        rule_id = rule_id_for_comment(comment["comment_id"])
        stored = load_judged_rule(rule_id)
        if stored and stored.enforced_by == correction["enforced_by"] and stored.statement == correction["statement"]:
            report["unchanged"].append(rule_id)
        else:
            save_judged_rule(JudgedRule(
                rule_id=rule_id, statement=correction["statement"],
                comment_id=comment["comment_id"], comment_text=comment["text"],
                draft_id=comment["draft_id"], request_id=comment["request_id"],
                enforced_by=correction["enforced_by"]))
            report["processed"].append(rule_id)
        if comment["rule_state"] != RULE_STATE_DRAFTED:
            set_comment_rule_state(comment["draft_id"], comment["comment_id"], RULE_STATE_DRAFTED)
    obsolete = load_judged_rule("judged--safa-with-samo")
    if obsolete and obsolete.status != "retired":
        # Preserve the original statement, comment, acceptance date, and sync state.
        obsolete.status = "retired"
        obsolete.enforced_by = "sequence_check.site_repeat supersedes this exception"
        save_judged_rule(obsolete)
        report["retired"].append(obsolete.rule_id)
    return report
