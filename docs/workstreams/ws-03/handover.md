# ws-03 handover — 2026-09-05

For an agent starting with no memory of this work. Read `spec.md` beside this
file for the full record; this is what you need to resume.

> **Superseded in part, later the same day.** An audit tested every claim below
> against the artifacts on disk. Four did not hold. Read
> `state-audit.md` beside this file first, then the section
> "Second pass — 2026-09-05 afternoon" at the end of this file. Where the two
> disagree, the later text is the measured one.

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

---

# Second pass — 2026-09-05 afternoon

What an audit found, what was built after it, and what is still open. Every
number here was measured. The audit's own working is in `state-audit.md`.

## What the audit corrected

| Claim above | What is true |
|---|---|
| 332 offers | **335.** The fourth pass was still running while the audit ran, and it completed at 11:24 |
| Five commits unpushed | **Zero.** They were on the remote already |
| Gap summary stale at 68 offers | **It held a measurement over 2 offers**, written 48 minutes after the queue |
| Three sibling checkouts | **Three worktrees of one repository**, per `git worktree list` |

The pass that finished at 11:24 recovered three offers the parser fix `5a1ea4c`
had just made readable: `Baghdad and The South in 7 days` twice and
`in 8 days` once. They left the failure record as they entered the corpus,
which took it from 331 rejections to 328.

## What was built

**Derived artifacts now carry the corpus they came from.**
`corpus_fingerprint()` in `offer_store.py` stats every `offer.json` and returns
`{count, fingerprint, stamped_at}`. It costs 4 ms over 335 offers.
`corpus_provenance()` reads a stamp back and answers `current`, `stale` or
`unknown`. An artifact with no stamp is unknown, never current.

It stats rather than reads because `reparse_stored()` rewrites `offer.json` in
place and leaves the set of offers the same. A hash over membership would call a
reparsed corpus unchanged, and a reparse did happen on 2026-09-04 at 21:00.

**The stamp is on the gap summary, on every proposal, and on the failure
record.** The failure record changed from a bare list to an object holding
`corpus`, `scope` and `failures`. Its scope names the months, the accounts and
the run's start and end. A run with no failures now writes an empty list, where
before it skipped the write and left an older record that no reader could tell
from a current one.

**The review page shows the number and the warning together.** A stale coverage
figure is not withheld, because the figure is what tells a reviewer how far the
queue has drifted.

**The queue and the gap summary were rebuilt over all 335 offers.** The gap pass
took about 19 minutes of CPU for 2424 days, not the three minutes per 4000 days
this file estimated earlier.

## Two defects the page had all along

**The review page had never run in a browser.** The app sends
`script-src 'self' 'nonce-…'` on every response, and `/offers` is a
`FileResponse` that carries no nonce, so Chrome refused the inline `<script>`
block. The page held its "loading" placeholder and the console said nothing.
The script now lives in `static/js/offersReview.js`, which is how every other
page here loads its code. The handler tests passed throughout, because
`TESTING_STANDARD.md` drives handlers directly and no test opens a browser.

**One evidence lookup read the whole corpus.** `get_evidence_day` walked all 335
records to find one day, at 14.7 seconds a call and 12 calls per card. A day key
names its message, so `offers_of_message()` matches the directory by slug prefix
and reads only that offer. The same call takes 0.006 seconds.

The queue also renders 25 cards at a time. 257 cards in one write locked a phone
browser.

## State now

| | |
|---|---|
| Corpus | 335 offers, 128 MB, 2424 days, final for the 24-month window |
| Failure record | 328 rejections, still in the old bare-list shape until the next recovery run |
| Review queue | 257 pending — 236 stamped current, 21 unstamped from the 68-offer run |
| Gap summary | 335 offers, 35.6% coverage, stamped and current |
| Tests | 158 across five `tests/test_offers_*.py` files |
| Commits | `89c2d44`, `6b27bdf`, `e21035b` on `daily-driver`, and on the phone |

**Coverage fell from 47.7% to 35.6%.** The earlier figure was measured over 68
offers. The larger corpus holds many more days the catalogue cannot express.

## How the review page is reached

The Windows instance serves it. `APP_BIND=0.0.0.0` is set in `.env`, and the
phone opens `http://100.82.8.53:7001/offers` over Tailscale. The phone's own
Odysseus has no offer corpus; its data directory is
`/data/data/com.termux/files/home/odysseus-data`.

**Authentication is off instance-wide.** `.env` sets `AUTH_ENABLED=false`, so
`require_admin` returns for every caller from any address. The owner was told
and chose to expose the port anyway.

**The firewall does not restrict the port.** Four pre-existing rules allow
`python.exe` and `pythonw.exe` inbound on the Private and Public profiles, so
7001 also answers on the Ethernet LAN at `192.168.0.x` and on ZeroTier at
`10.54.117.x`. A scoped rule needs an elevated shell and has not been added.
`-RemoteAddress` takes no `!` negation, so the rule has to block the other
ranges rather than exclude the tailnet.

## Still open

**Day-tour offers do not parse.** 328 rejections remain. How many are real
offers is not recorded anywhere: the failure record stores a reason, not a
document class, and matching filenames gives 131 as an upper bound that includes
24 copies of a catalogue PDF and several guide biographies.

**21 proposals carry no corpus stamp.** They come from the 68-offer run and the
new analysis did not re-propose them. They are shown as unknown rather than
deleted, because no verdict was given on them.

**The reconciliation has never been persisted.** `reconcile()` computes and
`format_reconciliation()` prints. The "128 legacy offers with no surviving
source" figure exists only in this file.

**A corpus watermark was designed and parked.** A fingerprint answers which
corpus. It cannot answer whether the recovery window was wide enough, because a
corpus recovered with `--months 7` has a perfectly valid fingerprint.

## What was learned the hard way, this pass

**An artifact that records its result and not its conditions forces the next
reader to infer.** The audit inferred that the recovery pass had died, from a
failure-record timestamp. The pass was alive and finished during the audit. The
guard at `recover.py:143` was the reason the timestamp said nothing: a run with
no failures wrote nothing at all.

**A passing test suite is not a working page.** 138 tests passed against a page
whose JavaScript a browser had always refused to run.

**A slow page is not always a slow server.** The measurements said 0.03 s for
the page and 0.46 s for the queue, from the phone, while the page showed
"loading" forever.

---

## Owner input — 2026-09-05, after the second pass

Four items the owner raised after reading the rebuilt queue. Recorded as given.
None is designed or built.

### 1. Remove the dates from day text

The owner wants the dates out.

**They are in the text now.** A proposed template in the queue starts
`Sunday April 20`, and the `MO1` revision diff strikes `Sunday Feb 1` as the
difference between the catalogue text and the sent day. A date that changes on
every offer makes the same day look like a new one.

This file already lists embedded dates as one of three things a model would
strip, with prices and client names. Invariant 1.4 forbids a model over the
corpus before the owner's verdict, so a date rule and a model pass are two
different questions.

Not decided: whether the date is removed at parse time, at proposal time, or
only from what a reviewer sees.

### 2. Group days by similarity, and merge the ones that match

The owner wants similar itinerary days categorised and merged.

**Clustering exists and grouping already happens.** The last rebuild reported
738 patterns and 220 recurring ones over 2424 days, and `cluster_days` picks a
dominant variant inside a near-miss group. The queue still came out at 257
proposals.

Not decided: what counts as the same day for merging, whether merging joins
proposals or joins the days behind them, and what happens to the evidence keys
of a merged pair.

### 3. Propose the catalogue code for each day

The owner wants the system to suggest the code, not only the text.

**The reviewer types it by hand today.** The card carries an empty Code box with
the placeholder `e.g. MO2`, and a proposal cannot be approved without one. The
nearest existing template and its score are already shown beside every card.

Not decided: what a code is derived from, and how a suggestion avoids colliding
with a code the catalogue already holds.

### 4. Some itinerary days carry no spaces at all

The owner reports day text with every space missing.

**Space loss is known and partly handled.** Commit `2dd1180` recovers offers
whose PDF lost every space, and this file records three variants found by
opening rejected files by name: `Day 1` spaced, `TheOriginalTourDay1` glued to a
title, and `Day1SaturdayMarch1` glued to a weekday. That work made the day
*number* readable.

The owner's report is about the day *text*, which is a different thing from the
day number that a splitter looks for.

Not decided: whether the spaceless text is repaired, flagged, or left as it is.
