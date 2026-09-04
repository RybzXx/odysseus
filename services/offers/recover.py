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
import sqlite3
import sys
from datetime import date, timedelta

from src.constants import APP_DB, OFFER_CORPUS_DIR

from services.offers.offer_store import build_routes_json, reparse_stored
from services.offers.sent_offers import fetch_sent_offers

# Only Bil Weekend's own accounts hold sent offers; the two personal accounts on
# this instance are out of scope by ws-03 WP0.8.
OFFER_ACCOUNTS = ("book@bilweekend.com", "mahdi@bilweekend.iq")


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

        offers = [offer for offer in iter_offers() if offer.day_count]
        if not offers:
            print("the offer corpus is empty - recover it first", file=sys.stderr)
            return 2
        texts = load_template_texts()
        print(f"measuring {len(offers)} offers against {len(texts)} templates...", flush=True)
        report = analyse_catalogue_gap(offers, texts)
        drafted = propose_revisions(offers, report, texts) + propose_new_templates(report, texts)
        for proposal in drafted:
            save(proposal)
        save_summary(summarise(report, len(offers)))
        print(f"days {report.total_days}: matched {report.matched} "
              f"({report.coverage:.1%}), edited {report.near_miss}, "
              f"uncovered {report.unmatched}")
        print(f"patterns {len(report.patterns)}, recurring {len(report.recurring_patterns)}")
        print(f"drafted {len(drafted)} proposals; queue {queue_summary()}")
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

    totals = {"scanned": 0, "stored": 0, "skipped": 0, "failed": 0}
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
        print(f"scanned {manifest['messages_scanned']}  "
              f"{'would store' if args.dry_run else 'stored'} {manifest['offers_stored']}  "
              f"skipped {manifest['offers_skipped']}  "
              f"failed {len(manifest['failures'])}", flush=True)
        for failure in manifest["failures"][:20]:
            print("  ! " + json.dumps(failure, ensure_ascii=False), flush=True)

    print(f"\ntotals: {totals}")
    print(f"corpus: {OFFER_CORPUS_DIR}")
    if args.routes_json and not args.dry_run:
        print(f"routes.json: {build_routes_json(args.routes_json)} routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
