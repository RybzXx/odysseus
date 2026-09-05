"""
services/offers/recover.py

Command-line recovery of the sent-offer corpus.

    python -m services.offers.recover --months 7
    python -m services.offers.recover --dry-run
    python -m services.offers.recover --account book@bilweekend.com

Re-runnable by design: an offer already in the store is skipped, so a run that
dies half way costs only the messages it had not reached yet.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone

from src.constants import APP_DB, OFFER_CORPUS_DIR, RECOVERY_FAILURES_FILE

from services.offers.offer_store import (
    build_routes_json,
    corpus_fingerprint,
    reextract_stored,
    reparse_stored,
)
from services.offers.sent_offers import fetch_sent_offers

# Only Bil Weekend's own accounts hold sent offers; the two personal accounts on
# this instance are out of scope by ws-03 WP0.8.
OFFER_ACCOUNTS = ("book@bilweekend.com", "mahdi@bilweekend.iq")


def write_failure_record(failures: list, scope: dict, path: str | None = None) -> str:
    """
    Post: the record on disk holds this run's rejections, the corpus the run
          left behind, and the scope the run covered. Written atomically.

    The scope is not decoration. This write replaces the whole file, so a run
    over one account replaces a full-corpus record with a partial one. Before
    the scope was recorded, nothing on disk said which of the two a reader held.

    The path is resolved at call time. A default argument would capture the
    constant at import and make the location impossible to redirect, which is
    how a test comes to overwrite the real record.
    """
    path = path or RECOVERY_FAILURES_FILE
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    record = {"corpus": corpus_fingerprint(), "scope": scope, "failures": failures}
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    return path


def load_failure_record(path: str | None = None) -> dict | None:
    """
    Post: {"corpus": …, "scope": …, "failures": [...]}, or None when no record
          exists.

    A record written before this shape existed is a bare list. It loads with a
    corpus and a scope of None, which reads as unknown provenance. It does not
    read as a record of the current corpus.
    """
    path = path or RECOVERY_FAILURES_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(loaded, list):
        return {"corpus": None, "scope": None, "failures": loaded}
    return loaded


def _print_stage_progress(started_at: float):
    """
    Post: a callback for `analyse_catalogue_gap` that prints how far a stage has
          got, on one line per report.

    Scoring costs the same for every day, so the time left is a straight
    extrapolation and is printed. Clustering compares each day against every
    pattern found so far, so its cost per day rises as it runs. Extrapolating
    that would under-state the wait every time, so the pattern count is printed
    instead and no estimate is given.
    """
    def report(stage: str, done: int, total: int, note: str) -> None:
        elapsed = time.monotonic() - started_at
        share = done / total if total else 1.0
        line = f"  {stage} {done}/{total} ({share:.0%}) after {elapsed:.0f}s - {note}"
        if stage == "scoring" and done and done < total:
            line += f"; about {elapsed / done * (total - done):.0f}s left in this stage"
        print(line, flush=True)

    return report


def _accounts(only: str | None) -> list[tuple]:
    """
    Post: [(account_id, owner, imap_user)] for the enabled Bil Weekend accounts,
          or just the one named by `only`.
    """
    connection = sqlite3.connect(f"file:{APP_DB}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id, owner, imap_user FROM email_accounts WHERE enabled=1"
        ).fetchall()
    finally:
        connection.close()
    wanted = (only,) if only else OFFER_ACCOUNTS
    return [row for row in rows if row[2] in wanted]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Recover sent offers into the offer corpus.")
    parser.add_argument("--months", type=int, default=7, help="how far back to look (default 7)")
    parser.add_argument("--account", help="restrict to one imap_user")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be fetched; store nothing")
    parser.add_argument("--routes-json", help="also write the corpus in routes.json schema")
    parser.add_argument("--refetch", action="store_true",
                        help="re-fetch offers already in the store")
    parser.add_argument("--reparse", action="store_true",
                        help="re-split stored offers from their saved text; no mail is read")
    parser.add_argument("--reextract", action="store_true",
                        help="read the stored attachments again where the saved text lost its "
                             "spaces; no mail is read")
    parser.add_argument("--prune", action="store_true",
                        help="with --reparse, discard stored documents that hold no itinerary")
    parser.add_argument("--rebuild-proposals", action="store_true",
                        help="re-derive the review queue and the gap summary; no mail is read")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.rebuild_proposals:
        # The same work the review page's button does, without a request
        # timeout over it. A gap pass costs about 3 minutes on a full corpus,
        # which no HTTP handler should hold open.
        from services.offers.gap_report import save_summary, summarise
        from services.offers.proposals import queue_summary, save
        from services.offers.propose import propose_new_templates, propose_revisions
        from services.offers import analyse_catalogue_gap, iter_offers, load_template_texts

        # Stamped before the analysis, not after. A stamp taken afterwards would
        # describe the corpus at the end of a pass that takes minutes, and would
        # claim the run measured offers it never saw.
        corpus = corpus_fingerprint()
        offers = [offer for offer in iter_offers() if offer.day_count]
        if not offers:
            print("the offer corpus is empty - recover it first", file=sys.stderr)
            return 2
        texts = load_template_texts()
        print(f"measuring {len(offers)} offers against {len(texts)} templates "
              f"(corpus {corpus['fingerprint']}, {corpus['count']} stored)...", flush=True)
        report = analyse_catalogue_gap(
            offers, texts, on_progress=_print_stage_progress(time.monotonic()))
        drafted = (propose_revisions(offers, report, texts, corpus=corpus)
                   + propose_new_templates(report, texts, corpus=corpus))
        for proposal in drafted:
            save(proposal)
        save_summary(summarise(report, len(offers), corpus=corpus))
        print(f"days {report.total_days}: matched {report.matched} "
              f"({report.coverage:.1%}), edited {report.near_miss}, "
              f"uncovered {report.unmatched}")
        print(f"patterns {len(report.patterns)}, recurring {len(report.recurring_patterns)}")
        print(f"drafted {len(drafted)} proposals; queue {queue_summary()}")
        return 0

    if args.reextract:
        outcome = reextract_stored()
        print(f"examined {outcome['examined']} stored offers; "
              f"{outcome['unspaced']} had text that lost its spaces")
        print(f"repaired {outcome['repaired']}")
        if outcome["still_unspaced"]:
            print(f"still unspaced after a second read: {len(outcome['still_unspaced'])}")
            for name in outcome["still_unspaced"][:20]:
                print(f"  - {name}")
        if outcome["unreadable"]:
            print(f"attachment could not be read: {len(outcome['unreadable'])}")
            for name in outcome["unreadable"][:20]:
                print(f"  - {name}")
        if outcome["repaired"]:
            print("the queue and the gap summary now describe an older corpus; "
                  "re-derive with --rebuild-proposals")
        return 0

    if args.reparse:
        outcome = reparse_stored(prune=args.prune)
        print(f"reparsed {outcome['reparsed']} stored offers: "
              f"{outcome['days_before']} days -> {outcome['days_after']}")
        print(f"documents holding no itinerary: {len(outcome['no_itinerary'])}"
              f"{f', pruned {outcome["pruned"]}' if args.prune else ' (use --prune to discard)'}")
        for name in outcome["no_itinerary"][:20]:
            print(f"  - {name}")
        return 0
    before = date.today() + timedelta(days=1)
    since = before - timedelta(days=31 * args.months)

    accounts = _accounts(args.account)
    if not accounts:
        print("no matching enabled account", file=sys.stderr)
        return 2

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    totals = {"scanned": 0, "stored": 0, "skipped": 0, "failed": 0}
    all_failures = []
    for account_id, owner, imap_user in accounts:
        print(f"\n=== {imap_user}  {since} .. {before} ===", flush=True)
        manifest = fetch_sent_offers(
            account_id=account_id,
            owner=owner,
            since=since,
            before=before,
            skip_stored=not args.refetch,
            dry_run=args.dry_run,
        )
        totals["scanned"] += manifest["messages_scanned"]
        totals["stored"] += manifest["offers_stored"]
        totals["skipped"] += manifest["offers_skipped"]
        totals["failed"] += len(manifest["failures"])
        all_failures.extend(dict(failure, account=imap_user)
                            for failure in manifest["failures"])
        print(f"scanned {manifest['messages_scanned']}  "
              f"{'would store' if args.dry_run else 'stored'} {manifest['offers_stored']}  "
              f"skipped {manifest['offers_skipped']}  "
              f"failed {len(manifest['failures'])}", flush=True)
        for failure in manifest["failures"][:20]:
            print("  ! " + json.dumps(failure, ensure_ascii=False), flush=True)
        if len(manifest["failures"]) > 20:
            print(f"  ... {len(manifest['failures']) - 20} more, see the failures file",
                  flush=True)

    print(f"\ntotals: {totals}")
    print(f"corpus: {OFFER_CORPUS_DIR}")

    # In full, never truncated, and written even when the list is empty. The
    # console list is capped at 20 per account, and that cap once hid 369 of 409
    # rejections. Of the 40 that happened to be visible, 25 were real offers a
    # parser fix later recovered — evidence that only existed because the cap
    # missed them. A run that finds nothing writes an empty list, because a
    # skipped write leaves an old record that no reader can tell from a new one.
    written = write_failure_record(all_failures, {
        "months": args.months,
        "accounts": [imap_user for _, _, imap_user in accounts],
        "since": since.isoformat(),
        "before": before.isoformat(),
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": bool(args.dry_run),
        "refetch": bool(args.refetch),
    })
    print(f"failures: {len(all_failures)} recorded in {written}")

    if args.routes_json and not args.dry_run:
        print(f"routes.json: {build_routes_json(args.routes_json)} routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
