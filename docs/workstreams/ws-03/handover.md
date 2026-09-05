# ws-03 handover — 2026-09-05

For an agent starting with no memory of this work. Read `spec.md` beside this
file for the full record; this is what you need to resume.

---

## What this is

Bil Weekend answers travel enquiries by hand-writing offers. Those offers exist
only as attachments in sent mail. An itinerary program maker exists and can only
express a minority of what the offers actually say.

The workstream recovers the offers from mail, measures what the day-template
catalogue is missing, and puts the difference in front of a human as a review
queue. Nothing reaches the catalogue without a human verdict.

## Where the work is

Branch `main` in `D:\ai_projects_2026\odysseuswork\odysseus-agent-1`.
Remote `daily-driver` on `github.com/RybzXx/odysseus`.

**Five commits are unpushed**: `d12dbfb`, `de66b5a`, `2dd1180`, `0b2d970`,
`5a1ea4c`. Everything through `c446240` is on the remote.

No code or data path reaches outside the repository. The Bil Weekend pipeline is
vendored at `services/itinerary/pipeline`; the day catalogue is vendored at
`services/offers/data`. `BILWEEKEND_REPO_ROOT` is gone.

**One file must be placed by hand on a new machine.** The vendored pipeline
reads a Google service account from `data/bilweekend_service_account.json`, or
from the path in `BILWEEKEND_GOOGLE_CREDENTIALS`. That file is gitignored and
does not travel with a clone. Without it, template and pricing loading still
work — they read the vendored data — but anything touching Google Docs or
Sheets fails. On the machine this was built on it was copied from the
`WebOperationsBilW` checkout's `mahdi1.json`.

The standalone `WebOperationsBilW` checkout is a separate git repo and received
two changes early in this work: the autojunk fix and the ranked matcher, with
its near-miss band and ambiguity margin. They are committed there as `c4170ae`
on `master`, unpushed. Odysseus is the authoritative copy of that logic now —
`services/offers/day_match` is the single implementation, and the vendored
`itinerary_reader` imports it — but that checkout is what Render deploys, so the
fix matters there on its own account.

That repo also carries two unrelated modified files, `data/pricing/entry_tickets.json`
and `data/pricing/new_hotels.json`, which predate this work and were deliberately
left uncommitted.

## State as of this handover

| | |
|---|---|
| Corpus | 332 offers, 126 MB, in `data/offer_corpus` (gitignored) |
| Tests | 138 passing across the four `tests/test_offers_*.py` files |
| Review queue | 48 pending proposals — **stale**, built from a 68-offer corpus |
| Gap summary | **stale** — `data/catalogue_gap.json` measured on 68 offers |
| Recovery | A fourth pass was running detached when this was written |

**The queue and the gap summary are both stale.** They describe the 68-offer
corpus, not the 332-offer one. Rebuild before showing them to anyone:

```
python -m services.offers.recover --rebuild-proposals
```

That takes about three minutes per 4000 days. Do not use the review page's
button for a full corpus — it holds an HTTP request open and will time out.

## Owner decisions already made

| # | Decision |
|---|---|
| D1 | Push to `daily-driver` |
| D2 | **No model has been approved.** The owner reviews the proposals first |
| D3 | 24-month mail window, with older wording weighted down |
| D4 | Documents holding no itinerary are discarded, not stored |
| D5 | `MATCH_THRESHOLD` is 0.80, and small deviations must be visible |
| D6 | The review page stays a separate page, not a sidebar panel |

Invariant 1.4 forbids running any model over the corpus before the owner
agrees. That has not happened. Proposal text is verbatim sent prose with layout
debris removed; what a model would still strip is embedded dates, prices and
client names.

## Commands

```
python -m services.offers.recover --months 24        # recover from mail; resumable
python -m services.offers.recover --dry-run          # report, store nothing
python -m services.offers.recover --reparse          # re-split from stored text; no mail
python -m services.offers.recover --reparse --prune  # and discard non-itineraries
python -m services.offers.recover --rebuild-proposals
```

Recovery is resumable: the store skips every offer it already holds, so an
interrupted run costs only the messages it had not reached. Run it detached —
background tasks in this harness were killed three times.

The review page is at `/offers`. Set `PYTHONIOENCODING=utf-8` before any command
that prints corpus text; the console codepage cannot encode the bullet glyphs.

## What is still open

**Day-tour offers do not parse.** Roughly 26 rejected attachments are real
offers — `Babylon Day Tour`, `Day trip in Baghdad`, `Babylon & Karbala Day
Tour`. They use named days or no day numbering at all, so there is nothing for a
day-number splitter to find. This needs a different parser, not another regex.
It is the next real design question.

**`BANMEB` and `BAEB` score 0.850 against each other.** The owner chose to
differentiate them. It will surface in the review queue.

**Route retrieval must never apply the recency weight.** Wording ages; routing
does not. WP2 is not built; the rule is recorded where the weight is defined.

**The reconciliation is stale.** On the 7-month corpus, 128 legacy offers had no
surviving source. The 24-month window should reduce that sharply. Re-run it.

## Things that were learned the hard way

**`difflib.SequenceMatcher` has an autojunk heuristic** that discards any element
in more than 1% of a sequence longer than 200 elements. Over characters that is
the space and most common letters, and every template is longer than 200
characters. It also junks only the second argument, so the score depended on
argument order. Disabling it moved catalogue coverage from 35.0% to 47.7% on the
same days. Every threshold measured before that fix is void.

**Each PDF generation drops spaces differently.** Three variants were found, each
invisible until a rejected file was opened by name: `Day 1` spaced,
`TheOriginalTourDay1` glued to a title, `Day1SaturdayMarch1` glued to a weekday.
A pass whose counts look plausible is not evidence that it worked.

**A reversed route scores 0.836.** Token overlap is blind to order and carries
half the score, so at a 0.80 threshold the catalogue would accept a journey as
its own mirror. A reordered pair is now neither a match nor an edit — calling it
an edit was tried and was worse, because it proposed replacing the mirror
template with the reversed wording.

**Truncated reporting hid a defect.** The recovery printed at most 20 failures
per account, which concealed 369 of 409 rejections. The parser defect was found
only because 25 of the 40 that happened to be visible were real offers. Failures
are now written in full to `data/offer_recovery_failures.json`.

**A default argument captures its constant at import.** `save_summary(path=
GAP_SUMMARY_FILE)` made the path impossible to redirect, so a test pointed at a
tmp_path silently read the real corpus. Persisted paths are resolved at call
time.

**`rglob` descends before any filter runs.** `test_tls_overrides_scope` walked
the repository and filtered afterwards, so it entered `data/` — 40,310 `.py`
files of unrelated checkouts on a working machine — and never finished, hanging
the whole suite at ~90%. Pruning during the walk took it from never-finishing to
0.45 seconds.

**The full suite has 123 pre-existing failures** on an unmodified checkout, all
environmental (macOS, Docker, JS). That is the number to compare against, not
zero.

## Two claims that were wrong and were corrected

**"Nine templates are used by no offer."** Measured as *never winning the
argmax*, which is not the same claim. Four of the nine clear the threshold and
simply lose to a closer template. After the autojunk fix only two are genuinely
unreferenced.

**"Failures are now recorded in full."** The write block never reached the file;
a patch had not matched. The claim appeared in a commit message and in a report
to the owner while the behaviour was unchanged. Fixed in `0b2d970`.

**"Moved the workstream record into the repository it describes."** `c446240`
copied the spec rather than moving it, and left a duplicate in the outer working
directory. Both copies were identical, so nothing had diverged, but a second
copy of a living document is a copy that will. The duplicate was deleted on
2026-09-05; `docs/workstreams/` in the outer directory still holds
`00-PROTOCOL.md` and `ws-01`, which predate this work.

The pattern in all three: a claim was made from the intent of an edit rather
than from its result. Checking the file afterwards would have caught every one.
