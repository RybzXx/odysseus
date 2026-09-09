# ws-03 handover — 2026-09-05

For an agent starting with no memory of this work. Read `spec.md` beside this
file for the full record. This is what you need to resume.

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
vendored at `services/itinerary/pipeline`. The day catalogue is vendored at
`services/offers/data`. `BILWEEKEND_REPO_ROOT` is gone.

**One file must be placed by hand on a new machine.** The vendored pipeline
reads a Google service account from `data/bilweekend_service_account.json`, or
from the path in `BILWEEKEND_GOOGLE_CREDENTIALS`. That file is gitignored and
does not travel with a clone. Without it, template and pricing loading still
work — they read the vendored data — but anything touching Google Docs or
Sheets fails. On the machine this was built on it was copied from the
`WebOperationsBilW` checkout's `mahdi1.json`.

The standalone `WebOperationsBilW` checkout is a separate git repo and received
two changes early in this work: the autojunk repair and the ranked matcher, with
its near-miss band and ambiguity margin. They are committed there as `c4170ae`
on `master`, unpushed. Odysseus is the authoritative copy of that logic now —
`services/offers/day_match` is the single implementation, and the vendored
`itinerary_reader` imports it — but that checkout is what Render deploys, so the
repair matters there on its own account.

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
debris removed. What a model would still strip is embedded dates, prices and
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
that prints corpus text. The console codepage cannot encode the bullet glyphs.

## What is still open

**Day-tour offers do not parse.** Roughly 26 rejected attachments are real
offers — `Babylon Day Tour`, `Day trip in Baghdad`, `Babylon & Karbala Day
Tour`. They use named days or no day numbering at all, so there is nothing for a
day-number splitter to find. This needs a different parser, not another regex.
It is the next real design question.

**`BANMEB` and `BAEB` score 0.850 against each other.** The owner chose to
differentiate them. It will surface in the review queue.

**Route retrieval must never apply the recency weight.** Wording ages. Routing
does not. WP2 is not built. The rule is recorded where the weight is defined.

**The reconciliation is stale.** On the 7-month corpus, 128 legacy offers had no
surviving source. The 24-month window should reduce that sharply. Re-run it.

## Things that were learned the hard way

**`difflib.SequenceMatcher` has an autojunk heuristic** that discards any element
in more than 1% of a sequence longer than 200 elements. Over characters that is
the space and most common letters, and every template is longer than 200
characters. It also junks only the second argument, so the score depended on
argument order. Disabling it moved catalogue coverage from 35.0% to 47.7% on the
same days. Every threshold measured before that repair is void.

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

## Two claims that were wrong, and the repairs

**"Nine templates are used by no offer."** Measured as *never winning the
argmax*, which is not the same claim. Four of the nine clear the threshold and
simply lose to a closer template. After the autojunk repair only two are genuinely
unreferenced.

**"Failures are now recorded in full."** The write block never reached the file.
A patch had not matched. The claim appeared in a commit message and in a report
to the owner while the behaviour was unchanged. Repaired in `0b2d970`.

**"Moved the workstream record into the repository it describes."** `c446240`
copied the spec rather than moving it, and left a duplicate in the outer working
directory. Both copies were identical, so nothing had diverged, but a second
copy of a living document is a copy that will. The duplicate was removed on
2026-09-05. `docs/workstreams/` in the outer directory still holds
`00-PROTOCOL.md` and `ws-01`, which predate this work.

The pattern in all three: a claim was made from the intent of an edit rather
than from its result. Checking the file afterwards would have caught every one.

---

# Second pass — 2026-09-05 afternoon

What an audit found, what was built after it, and what is still open. Every
number here was measured. The audit's own working is in `state-audit.md`.

## What the audit repaired

| Claim above | What is true |
|---|---|
| 332 offers | **335.** The fourth pass was still running while the audit ran, and it completed at 11:24 |
| Five commits unpushed | **Zero.** They were on the remote already |
| Gap summary stale at 68 offers | **It held a measurement over 2 offers**, written 48 minutes after the queue |
| Three sibling checkouts | **Three worktrees of one repository**, per `git worktree list` |

The pass that finished at 11:24 recovered three offers the parser repair `5a1ea4c`
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
Odysseus has no offer corpus. Its data directory is
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
removed, because no verdict was given on them.

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

---

## Third pass — 2026-09-05 evening

The owner's items 2 and 4 were designed and built. Items 1 and 3 were not
started. Recorded while the rebuild that measures the result is still running.

### The spaceless days are repaired

**543 of 2424 days had lost every space.** They arrived as
`Meetandgreet,andfasttrackvisafromtheairport`. Not one could match a template:
0 of a 70-day sample reached the 0.80 threshold, against 53% of days that kept
their spaces. That was 38% of everything the catalogue did not cover.

**pypdf drops the spaces on some files and reads the rest correctly.** PyMuPDF
reads the same files with spaces, on 12 of 12 sampled documents. It was already
installed, so nothing new was required.

pypdf stays the first reader. PyMuPDF is asked only about a document whose text
looks unspaced, and its answer is taken only when it is better. Reading every
file twice would change text that is already right, and every proposal id with
it.

`python -m services.offers.recover --reextract` reads the stored attachments
again. This is what invariant 1.1 is for: `source.<ext>` is kept for the life of
the corpus and never written, so every derivative of it can be made again.

| | Before | After |
|---|---|---|
| Unspaced days | 543 of 2424 | 1 of 2449 |
| Median space ratio | 0.161 | 0.165 |
| Days found | 2424 | 2449 |

The 25 extra days appeared because re-splitting better text finds day headings
the mangled text hid.

**One day resists both readers.** `ATC Nowruz Itinerary - March 2025.pdf` day 3
loses spaces irregularly — `Visit theSulaymaniyahMuseum, atreasuretroveof
Kurdishhistory` — and pypdf and PyMuPDF return it the same way. It is named in
the run's report rather than guessed at. One day in 2449 did not justify the
word-list segmenter the design had held in reserve.

### Two repairs came from running it

**The first test asked about the whole document, and the day is the unit that
gets matched.** One document scores 0.094 across the whole file while its third
day is unreadable. One damaged day now sends the document back to its
attachment.

**A day reading `Arrival` has no spaces because it is one word.** Five such days
in one `.docx` were sent for repair by a ratio test that judged text too short to
judge. The test now says nothing about text under 80 characters. The shortest
damaged day measured is 196.

### Near-duplicates group in the queue

**Nothing is merged.** All 257 proposals stay, no id changes, and no rebuild is
needed. Near-duplicates render as one block with an optional single verdict, and
a control on the page moves the line while a reviewer reads.

| Threshold | Blocks | Groups |
|---|---|---|
| 0.95 | 254 | 3 |
| 0.80 | 242 | 13 |
| 0.70 (default) | 223 | 17 |
| 0.60 | 188 | 26 |
| 0.50 | 144 | 27 |

It is computed in the page. The response already carries every proposal's text,
so the server would send the same bytes and answer one threshold.

**A group verdict decides one proposal at a time.** Each still needs its own
code, and a proposal the server refuses does not take the others down with it.

### A gap pass now says how far it has got

**It printed one line, then nothing, for about fifteen minutes.** The only sign
it was alive was CPU time climbing.

`gap_report` measures and never prints, so the caller supplies a callback. The
command prints it. The HTTP handler passes nothing.

**An estimate appears only for scoring.** Every day costs the same to score, so
the time left is a straight extrapolation. Clustering compares each day against
every pattern found so far, so its cost per day rises as it runs. The pattern
count is printed instead, because a rising count is what explains the slowdown.

### The provenance work caught its own change

Re-extraction rewrote 90 records and left the count at 335. The fingerprint moved
from `05070bcc80d845de` to `610ffc253276eb19` while the count did not, and the
page said so. A hash over membership alone would have called that corpus
unchanged.

The warning was reworded. `335 offers then, 335 now` reads as no change at all,
so a stale artifact whose count is unchanged now says the text has changed
instead.

### What the repair was worth

**Coverage went from 35.6% to 49.5%.** The rebuild took 17 minutes over the
repaired corpus.

| | Before the repair | After |
|---|---|---|
| Days | 2424 | 2449 |
| Matched | 863 (35.6%) | **1213 (49.5%)** |
| Edited | 138 | 180 |
| Uncovered | 1423 | 1056 |
| Patterns | 738, 220 recurring | 562, 177 recurring |

The figure recorded before the run as the inference to test was about 47.5%. The
measured result is 49.5%.

**The queue grew rather than shrank.** The rebuild drafted 195 proposals, and the
queue holds 338 pending: 195 stamped current, 122 stale from the pre-repair run,
and 21 unstamped from the 68-offer run. A proposal that a later analysis does not
re-propose stays on disk, because no verdict was ever given on it. The queue has
gone 48, then 257, then 338 across three rebuilds.

The stamps make each group visible on the page, and the reviewer sees which
corpus each proposal came from.

### State at the time of writing

| | |
|---|---|
| Corpus | 335 offers, 2449 days, 1 day still unspaced |
| Tests | 172 across five `tests/test_offers_*.py` files |
| Review queue | 338 pending — 195 current, 122 stale, 21 unknown |
| Gap summary | 49.5% over 2449 days, stamped and current |
| Commits | `50ca3b8`, `06b63a1`, `b79c6da` |

### Owner items, disposition

| Item | State |
|---|---|
| 1. Remove the dates | Not started. The owner's reason is catalogue text quality, not matching. Removing the date line moved the mean score by +0.004. It moved no day across the threshold |
| 2. Group similar days | Built as a view |
| 3. Suggest the code | Not started. The code abbreviates the places named in a template's title, and a new proposal has no title |
| 4. Spaceless days | Repaired, 543 to 1 |

---

## Owner directive — 2026-09-05, evening

**The operations sheet is canon.** Anything already in it is settled and is not
re-proposed, re-worded, or argued with.

    https://docs.google.com/spreadsheets/d/1EiNUPoI3526-3Coxkjno_CesVc4UT2LhO8RebUKwn4w/edit?gid=0

**The objective is to append to that sheet.** Not to rewrite it.

Given as part of the New Operations work. Not yet read, and not yet checked
against the catalogue this workstream already loads.

**The queue is too long and too repetitive.** 338 pending, and the owner asked
for it shorter.

---

## Owner decision — 2026-09-05, evening: a model may read the corpus

**Invariant 1.4 is lifted.** It forbade running any model over the corpus before
the owner agreed. The owner agreed today. No model had run until now, and the
workstream was built so that none had to.

**Two properties are traded away, both knowingly.**

The proposed wording stops being a sent day. `propose.py` states the old
property: every proposed wording is a verbatim day a human actually sent, so the
evidence trail is exact. A cleaned text is derived from a sent day rather than
being one. The card shows both, so the original is not lost.

The day text leaves the machine. The owner chose the app default,
`gemma4:31b-cloud`, reached through the local endpoint at
`100.82.8.53:11434/v1`. The `-cloud` suffix says Ollama relays it to their
servers. Read from the name, not tested. The day text carries client names,
dates and prices. A local model was available and was not chosen.

**What the model is asked for.** Four things: `title`, `city`,
`included_sites`, and a cleaned wording. Nothing else.

**What it is not asked for.** Pricing tags follow a rule. Canon carries
`guide_day` on 28 of 28 rows, `transport_day` on 28 of 28, and `hotel_night` on
26 of 28 — the two without it are the two with no overnight city. That is a
rule, and asking a model for it only adds a way to be wrong.

**Where the answer lives.** A `suggested` block on the proposal, beside the
drafted fields and marked as machine text. Nothing merges it into `fields`. Only
the owner's accept moves a value across, through the verdict path that already
exists.

**Two accepts, not one.** The fields and the cleaned text are accepted
separately, so a bad rewrite does not cost a good set of fields.

**The cleaner is gated.** Canon's 28 texts carry no formatting faults: no
leading or trailing space, no double space, no carriage return, no triple
newline, no space before a newline or before punctuation. A cleaner that works has
nothing to change in them. It ships only when all 28 come back unchanged, so the
fields half and the text half ship independently.

**Unsure fields are filled and marked.** Each suggested field carries `high` or
`low` confidence. The owner chose a marked guess over an empty box.

---

## Fourth pass — 2026-09-06: the catalogue grew

**The 32 approved rows reached the sheet.** The `templates` tab holds 60 rows
where it held 28. Verified by reading it: every new row carries
`active: FALSE` and `needs_review: TRUE`, which is invariant 1.3 working.

    ARREB, ArrSU, BAMaMNV, BANA, BGNJURUKNA, ChHkEB, DaMOZKDU, EB, EBKOSU,
    EBNEWROZ, FREEBG, HABISU, KABBBG, KANJ, MUCTAGKDHBG, MaMEB, MaMJEFADU,
    NJ, NJUkKA, QOLANOW, SHAKSOEB, SHAMBASO, SHRINESBG, SHSOKO, SUEBDEP,
    SUKOYEB, SUSOEB, SUtEBt, UrErNA, UrukErUR, UrukNJ, ZuBA

**The vendored copy still holds 28.** It is a snapshot, and it has not been
taken again since the write. Anything reading `services/offers/data/templates`
is reading the catalogue as it was before this.

### The columns were filled by hand, once

The owner asked for one pass without the configured model. Titles, cities and
site codes were read from each day's own text. Every site code was checked
against `entry_tickets` before it was written, and the script refuses to run if
one is not in that list.

`KABBBG` was approved while the pass ran and was included.

### Two rows were still run together, and the reason was a blind spot

A ratio test finds a day that lost every space. It cannot find one that lost
some. `ATC Nowruz Itinerary - March 2025.pdf` reads at 0.12 overall and holds
`Meet andGreet andtransfer fromtheairport`, so both re-extraction passes walked
past it. It supplied `ARREB` and `SHAMBASO`.

**`looks_unspaced` now counts two more shapes.** An eaten boundary is a
lowercase run straight into a capitalised word, anchored at a word start so
`MondayMar` splits at `Monday` and not at `onday`. An overlong run is thirteen
letters or more. Three signs together are required, so a genuine long word never
triggers a repair on its own.

**Thirteen, measured.** At fourteen the test finds 4 damaged days, at thirteen
11, and at twelve 216 — real words start there, and `accommodation` and
`approximately` are twelve.

**`word_split` puts the spaces back where no reader can.** The lexicon is the
corpus's own spaced days, so it holds Qaimer, mashoof and Rawanduz. Only spaces
are inserted, and the repair refuses to write text whose letters changed.

**The run threshold is nine, measured.** Six was tried: it repaired not one day
more, and it broke real words the lexicon happens not to hold, turning `within`
into `with in` and `infamous` into `in famous`. Every piece of those splits is a
known word, so the unknown-piece guard cannot catch them. The length line is the
only defence.

### The first repair attempt did nothing, and the cause is the same class

The lexicon was built from days the ratio test called healthy, so it learned
`fromtheairport` as a word. A lexicon that knows the run-together form can never
split it again. One detector now serves both the repair pass and the lexicon
filter.

### A wording becomes a catalogue row at the verdict

**Not at draft time, and not on a pending row.** A proposal id is the hash of
its text. Measured: all 324 pending ids matched their text exactly. Cleaning at
draft time would have re-identified every one and stopped the 224 rejections
suppressing their days, orphaning every verdict already given. Cleaning a
pending row is worse: the next rebuild redraws it from the corpus under the
original id, retires the cleaned one, and puts a dirty duplicate beside it.

`as_catalogue_text` strips the date heading and the overnight trailer and puts
one sentence on one line. `record_verdict` calls it when a proposal is approved.
A rejected row keeps the wording as sent, because it is evidence rather than a
row.

Two rows of the thirty-two were refreshed from the repaired corpus. The other
thirty were left alone: the newer reading of some documents puts the
`Overnight:` trailer and a pricing footnote back, and reads `Uruk` as `Euruk` in
one. A refresh is not an improvement by default.

### State after the rebuild

| | |
|---|---|
| Catalogue | 60 rows in the sheet, 28 active, 32 awaiting activation |
| Corpus | 335 offers, 2449 days |
| Coverage | 49.6% — 1215 matched, 182 edited, 1052 uncovered |
| Queue | 329 pending, 32 approved, 224 rejected, 142 retired |
| Retired this run | 2, against 140 the run before |
| Tests | 249 across seven files |

**Retirement fell from 140 to 2.** The earlier run cleared a backlog from three
older corpora. This one found almost the same set it drafted before, which is
what a settled queue looks like.

**The space repair moved coverage by four days.** It touched 11 days of 2449, so
that is the size it should be. Its value was the two approved rows.

### The itinerary desk

**A request now becomes a day-code sequence at `/itinerary`.** The model reads
the request and answers with codes. The vendored rules run beside it, matching
the request against the routes actually sold and binding that route's days to
live templates. The desk shows both and marks their difference position by
position. Neither decides.

A comment moves the model's answer and never the rules answer. The rules are
deterministic, and an unchanging second opinion across a whole thread is what makes
them worth running.

`curated` is vendored from `OperationsAutomationSrv` at `3944ecc`, with its
pipeline coupling rewritten to this repository's own vendored pipeline.
`BILWEEKEND_REPO_ROOT` stays gone. `runner.py` and `sheets_client.py` are
deliberately absent: they write six cells back to the operations sheet, and that
write must not arrive as a side effect of an import.

Verified on an 8-day request for Kurdistan and Central Iraq. The rules matched
`Giovanbattista - 8 Days in Iraq.docx` at 1.00. The model answered with eight
valid codes and a reason, invented nothing, and agreed on arrival and Mosul.

### What is open

**The 32 new rows are inactive.** `active_template_texts` filters on that field,
so the itinerary desk still chooses from 28 codes. Activating them is a separate
deliberate act that nothing in this workstream performs.

**The vendored template snapshot is stale.** 28 rows against the sheet's 60.

**The operations-sheet list on the desk is not built.** A request is pasted.

**Generation from the desk is untested.** It renders a real Google Doc.

**The text cleaner is off.** It failed the canon round trip at 11 of 28, and
most of its changes were real repairs to canon's own spelling.

**Day tours still do not parse.** 328 rejections, and how many are real offers
is unknown.

**Port 7001 answers with no login on the LAN and on ZeroTier.** `AUTH_ENABLED`
is false and the firewall rule has not been added.

---

## Phase two — 2026-09-06: AI automations and the rule set

The owner activated all 60 catalogue rows and cleared `needs_review` on every
one. Verified by reading the sheet. The itinerary desk now chooses from 60 codes
rather than 28.

The owner also made an `AIRules` tab. It is empty, so its header is ours to
choose.

### I built a duplicate, and a search would have found it first

`services/itinerary` already held a normalizer, a matcher, a binder and a
generator. This session vendored `curated` from `OperationsAutomationSrv` on top
of it. Two implementations of one job then sat in one repository.

| Job | Already there | What this session added |
|---|---|---|
| Read a request | `normalizer.normalize_from_dict` | `curated.normalize.normalize_row` |
| Match a route | `matcher.find_best_route` | `curated.scorer.best_match` |
| Bind days to codes | `binder.bind_route_to_templates` | `curated.binder.bind_route` |
| Build and generate | `generator.execute_generation` | `curated.request_builder.build_request` |

**Both scorers carry identical weights**: region 0.5, day count 0.35, tour type
0.15. The two are the same algorithm.

**The search missed it because it looked for the wrong word.** It searched for
"rule" and "automation" across three project trees and the git history. It found
nothing, and reported that no prior work existed. The prior work was there under
"itinerary".

**`services/itinerary` is the survivor.** `app.py` registers its routes, it
exposes `/preview`, `/generate` and `/stage-reply`, and it already reads the
Operations panel's four sources: booking, contact, curated and queue. Its
`NormalizedRequest` carries 17 fields to the vendored copy's 14, including
`key`, `source` and `raw_record`.

**The vendored copy holds two constants the survivor lacks.**
`MATCH_MIN_SCORE` 0.30 says when a match is weak. `DAYTRIP_MIN_SIMILARITY` 0.12
governs binding a day trip. The merge carries both across.

`drafts.py` and `propose_sequence.py` are not duplicates. The draft thread, the
two proposers and the position-by-position comparison have no counterpart, so
they move rather than end.

### Rules come out of the corpus by counting

**A rule of this kind is a count, not a judgement.** Measured over the 302
offers of three days or more, using the overnight city each day already carries:

| | |
|---|---|
| Starts in Baghdad | 194 of 302 |
| Starts in Basra | 46 |
| Ends in Erbil | 107 |
| Ends in Mosul | 66 |
| Ends in Baghdad | 60 |

The commonest moves: Baghdad to Mosul 171, Baghdad to Karbala 116, Karbala to
Nasiriyah 104, Nasiriyah to Baghdad 102, Mosul to Duhok 61, Mosul to Erbil 51.

Day counts cluster at 8 days 50 times, 5 days 43, 7 days 35, 10 days 27.

**"194 of 302 trips start in Baghdad" is checkable by anyone.** A model saying
the same thing is not, and it can be wrong in a way nobody notices.

### The owner's decisions

| # | Decision |
|---|---|
| D7 | The counter finds the rule. The model words it and proposes a reason. The count sits beside both |
| D8 | Rules describe the whole corpus, not a slice |
| D9 | The page owns the rule record. `AIRules` holds a copy |
| D10 | A sync runs both ways, and names every addition, change and removal before it moves anything |
| D11 | A rule changed on both sides since the last sync is refused. The rest of the sync still applies |
| D12 | A new workstation page. The desk at `/itinerary` stays |
| D13 | Merge the vendored copy into `services/itinerary`, then remove it |

**A reason is a claim the counting does not support, and it goes into the
prompt.** The owner chose that knowing it. The page must therefore show the
reason apart from its count, so a reader can accept the statement and turn down
the reason without losing the rule.

### The operations sheet does not hold requests in the shape curated expects

`curated.settings` reads a tab named `main`. The operations sheet is titled
`26-27 Upcoming Tours / Season of 2026/2027` and holds eleven tabs, none of them
`main`. The read failed on exactly that.

The owner named the Operations panel inside Odysseus instead. It already carries
Curated and Queue sources, and the workstation reads those.

### What is open

**The merge is not done.** Two implementations still sit side by side.

**The rule families are measured but not built.** First night, last night, move
and trip length all exist in the corpus. How many rules each produces is
unknown until the first run.

**The vendored template snapshot is stale.** 28 rows against the sheet's 60.

**Port 7001 answers with no login on the LAN and on ZeroTier.**

---

## 2026-09-06: the merge, and the rule counter

Two work packages landed. WP1 merged the duplicate. WP2 built the rule counter.

Commits: `6aeabe1` for the merge, `936506a` for the counter.

### WP1 — one itinerary module

`services/curated` is gone. Nothing imports it.

`drafts.py` and `propose_sequence.py` moved into `services/itinerary`. They hold
the draft thread, the two proposers, and the position-by-position comparison.
The survivor had no counterpart for any of the three.

`MATCH_MIN_SCORE` 0.30 came across with them. It says when a route match is weak.

The merge exposed three faults. A duplicate had hidden each one.

**The two normalizers were not one reader.** The survivor reads the live web
form keys, such as `tripDays` and `numberOfPeople`. The desk posted sheet
headers, such as `days` and `pax`. Every typed request fell to the defaults. An
8-day request built a 5-day trip, and nothing said so. The desk form and its
tests now use the live keys.

**The desk gave dicts to a binder that reads objects.** The overnight index came
back empty. The binder bound 0 days of 8 and reported every day as uncovered.
`active_day_templates` now reads through the generation pipeline's own loader.
The desk therefore proposes over what the generator can build. `field_of` reads
either shape.

**`as_catalogue_text` removed the hour from a day.** Its date rule made every
part optional, so the trailing year matched a bare number alone. "7 AM Start the
day" became "AM Start the day". `MaMEB` reached the sheet without its hour. The
rule now needs a weekday or a month name.

### Repairs to the sheet

Three cells changed. Each one repairs damage from the earlier push of approved
rows. Each write was read back.

| Row | Was | Now |
|---|---|---|
| `MaMEB` | `AM after Breakfast...` | `8 AM after Breakfast...` |
| `ArrSU` | `Monastery ,` | `Monastery,` |
| `KANJ` | `rest .` and `check -in` | `rest.` and `check-in` |

The corpus holds one opening for the `MaMEB` day, so the hour is not in doubt.

`as_catalogue_text` now closes a space before a mark and inside a hyphen.

### The template snapshot is current

`services/offers/refresh_snapshot.py` reads the `templates` tab and writes the
vendored snapshot. It plans before it writes. It never removes a row.

The snapshot went 28 to 60. The 32 approved rows are therefore proposable. The
rules proposer already uses `KABBBG` and `SUEBDEP`.

**Two site cells hold text that is not JSON.** `BA0` holds `[TRF_FEE]` and
`URUK` holds `["NA_URUK","]`. The reader recovers the codes and reports both.
Before this, the pipeline priced those two days without their sites. The two
cells remain malformed in the sheet. The owner decides whether to repair them,
because a repair changes what those days cost.

### WP2 — rules by counting

`services/offers/rule_counter.py` counts four families over the sent offers.
No model reads the corpus here. D7 gives the wording to the model later.

Measured on 2026-09-06: 39 rules from 289 offers, 2057 nights named, 4 refused.

| Family | Rules | Strongest |
|---|---|---|
| first night | 2 | Baghdad 199 of 289 |
| last night | 3 | Erbil 107 of 289 |
| move | 24 | Erbil to Erbil 52 of 71 |
| trip length | 10 | 8 days 49 of 289 |

**A move counts against the nights spent in the city it leaves.** The rule
answers one question: given a night here, where next. A share of all 1752
transitions answers a question nobody asks.

**A second night in one city counts as a move to itself.** 369 of 709 nights
after Baghdad are another Baghdad night. That is the largest single fact in the
corpus. Without it a planner reads every night as a change of city.

**Trip length takes no share floor.** A share floor asks whether one outcome
leads the others, and that question needs few outcomes. A trip runs any of 15
lengths, so the commonest holds 17 percent. At a 15 percent floor the family
stated one rule and hid the shape of the demand. It now reports 3 to 12 days,
which covers 268 of 289 trips.

**The floors are 10 observations, then the family's share.** Below ten, one more
offer moves the share by more than ten points.

**The counter refuses to name a city when the cell offers a choice.** `Duhok or
Erbil` names two places. Reading it as either one invents evidence the offer
does not carry. The night drops out and the report names the wording. A dropped
night shortens the trip and joins no move, so no invented move appears.

A normalizer merges punctuation, notes, trailing day numbers, case and spelling.
The corpus holds 38 overnight strings for about a dozen places.

**An offer under two named nights is left out of all four families.** Its first
night is also its last. Counting it would state one fact twice under two family
names. The report names the count: 46 of 335.

### Numbers that moved

The handover above records 194 first-night Baghdad out of 302. The counter says
199 of 289. Two changes explain the difference. The normalizer merges
`Baghdad (Not Included)` and `Baghdad  1` into Baghdad. The population is now
offers with two or more named nights, rather than offers of three or more days.

### Tests

301 pass across nine files: `test_rule_counter`, `test_itinerary_desk`,
`test_itinerary_module`, `test_offers_apply`, `test_offers_module`,
`test_offers_provenance`, `test_offers_reconcile`, `test_offers_routes`,
`test_offers_suggest`.

Every rule-counter test uses a corpus small enough to check by reading it.

Three tests pin the faults above, so none of them returns:
`test_an_hour_at_the_head_of_a_day_survives_the_cleaner`,
`test_a_real_date_is_still_stripped`,
`test_a_space_before_a_mark_is_closed_up`.

`test_every_vendored_template_recovers_itself` pins the snapshot at 60. All 60
recover themselves.

### What is open

**WP3 to WP7 are not built.**

- **WP3** model wording. The model states the rule and proposes a reason. It
  reads the tallies only. No offer reaches the model.
- **WP4** rule record in `data/ai_rules/`. Eleven fields, `synced_at`, and the
  hash at the last sync.
- **WP5** two-way sync with the `AIRules` tab. The sync plans first. A rule
  changed on both sides is refused, and the rest still applies.
- **WP6** workstation page. It lists the Curated and Queue requests in batches
  of ten.
- **WP7** first run. Ten offers, a check, then ten itineraries.

**Two sheet cells hold text that is not JSON.** `BA0` and `URUK`, named above.

**Port 7001 answers with no login on the LAN and on ZeroTier.** The firewall
rule needs an elevated PowerShell, which is the owner's action.

---

## 2026-09-06 and 07: phase three

An audit opened this session. Then WP9, WP6, WP4, WP10 and WP7 landed. The
specification sits beside this file in `phase-three-spec.md`, with decisions
D14 to D27.

Commits `3e1a885` through `4e30a3f`, on `origin/daily-driver` and on the phone.

### The audit of the record above

Most of it held. The rule counter reproduced 39 rules over 289 offers. The
snapshot held 60 rows, all active. The queue held 329 pending, 32 approved, 224
rejected and 142 retired, to the row. 301 tests passed.

Five claims did not hold.

**The firewall rule exists.** `Odysseus 7001 off-tailnet block` is enabled and
blocks TCP 7001 from `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12` and
`169.254.0.0/16`. That covers the LAN and the ZeroTier range. Only
`AUTH_ENABLED=false` still stands.

**`DAYTRIP_MIN_SIMILARITY` never arrived.** The merge record says it came across
with `MATCH_MIN_SCORE`. A search of every `.py` file finds no occurrence.

**Four commits waited, not three.** `origin/daily-driver` sat at `2412ff6`, and
`main` tracked nothing.

**`services/curated` survives on disk.** Git and every import lost it. The
directory keeps a stale `__pycache__` with eight `.pyc` files.

**The WP numbers collide.** `spec.md` uses WP1 to WP5 for Catalogue, Retrieval
index, Generation, Human loop and Cross-cutting. The handover uses WP1 to WP7
for other work. A reader who opens `spec.md` to find WP6 does not find it.

### The relay is real

`gemma4:31b-cloud` leaves the machine. One probe to `100.82.8.53:11434`
returned headers that belong to somebody else's infrastructure:

    Server: Google Frontend
    Via: 1.1 google
    X-Cloud-Trace-Context: 7575d489b56641ce2c3983c7afa03274/954754...

Three facts agree. `/api/ps` held no resident model before the call and none
after. A 32.7B model answered in 0.9 seconds. The daemon stores one model,
`qwen3.8:27b` at 17.7 GB, and 32.7B at BF16 needs about 65 GB.

The endpoint record calls itself `local`, so `endpoint_cost_tracked` reads it as
local and tracks no cost.

### The desk served 28 codes while the disk held 60

Three things stacked up. `uvicorn.run` takes no reloader, so the process froze
its code at start. `catalogue.load_templates` keeps a process-lifetime cache
that only `refresh=True` clears. The pre-merge desk read that cached catalogue,
so both endpoints answered from one stale dict.

A restart moved both to 60. The code on disk needed no change, because the
merge had already moved the desk to an uncached loader.

### WP9 — the thread inside the sent message

The first Sent-folder walk kept the attachment and discarded the message. The
customer's request lives in that message, quoted under the reply, and INBOX
holds nothing older than five weeks.

The walk now stores `body.txt`, `body.html`, `in_reply_to` and `references`
beside the attachment. It never writes `source.<ext>`.

| | |
|---|---|
| Bodies captured, eight-month window | 81 |
| Threads recovered | 47, against a floor of 45 |
| Offers naming an earlier offer of ours | 10 |
| First-contact offers | 33 |

A first-contact offer opened the conversation. It quotes nothing because
nothing came before it. The report used to count all 33 as threads it had
failed to recover.

### Six faults a boundary pass found

A naive cutoff raised on tz-aware records. `offers_of_message` matched
directories by prefix, so a `References` header naming `<abc@x>` answered with
the stored `<abc@xy>`. `Message.walk` descended into `message/rfc822`, so a mail
forwarded as an attachment handed back its sender's words as ours. A reference
id with no angle brackets vanished. An RFC 5322 comment after an id travelled
with it. The walk keyed a message with no `Message-ID` on an IMAP sequence
number, which moves between sessions.

None had reached the live corpus. Every one now has a test.

### WP6 — the desk reads the worklist

The desk lists 43 Curated and Queue requests, whatever their status. 33 of them
carry `Replied`. Pills render ten at a time, above one detail pane that stays in
place.

The pane shows the normalised request beside the submitted record, and it
earned its place on the first request it opened. `normalize_queue_record` read
none of its row: pax was 2 whatever the record said, the hotel tier was 3star,
and it dropped every interest the customer wrote.

A setting gates the model proposer, off by default. The gate sits in
`propose_by_model` rather than at the route. A separate route saves a comment
with no model call.

### WP4 — two rule books

`data/ai_rules/counted/` holds 39 rules, eleven fields each. The content hash
ignores the moment a run counted a rule, so a re-count does not make the sheet
sync rewrite the tab. A rule the corpus stops supporting retires rather than
disappearing.

`data/ai_rules/judged/` stays separate, and its reader refuses the other book's
files. A judged rule carries the comment that produced it, the sequence a
reviewer repaired, and a corpus verdict of agrees, disagrees or silent.

### WP10 — 44 threads graded

Claude read each thread twice and answered before seeing the offer's cities.
Read one took the first inbound turn. Read two took every turn before the offer.

| | |
|---|---|
| Read one | 167 of 349 nights |
| Read two | 168 of 349 |
| The thread helped | 3 threads |
| The thread hurt | 1 thread |
| The thread changed nothing | 40 threads |

**The whole thread is worth one night in 349.** Bil Weekend's replies carry
logistics: payment, rooming, hotel category, visa. The route sits in the
customer's first message or nowhere in the text.

Four threads scored full marks, and every one stated its route outright.

The worst answers repeat one mistake. A request names cities, and the reader
gives each one a night. The offer keeps one base and visits them as day trips.
The counted book already says so, at 369 of 709 nights after Baghdad.

`ORIGIN_GRADED` opens a draft for a trip that was already sold, so the human's
reason lands on `comments` like every other piece of feedback. `iter_drafts`
takes the origins it should return, and the desk asks for open requests only.

### WP7 — the first run

Ten live requests, checked without rendering anything. It built 1 document of
10, and after two repairs it builds 8. Uncovered days fell from 57 to 13.

**The region a customer names never reached the binder.** `REGION_NAME_MAP` had
no entry for the labels the worklist uses, so the binder dropped every day whose
overnight city sat outside the requested region. Measured over 43 live requests:
eight labels, six of them unmapped, and the two commonest were two of the six at
26 and 25 requests.

**`Not Known` was a region.** It filtered every day out of two ten-day trips.

**The pipeline was still imported from `src.`,** where it lived before this
repository vendored it. Every preview lost its quote to a
`ModuleNotFoundError` that the caller recorded as a notice.

Match scores rose with the repair, because region coverage feeds them. One route
moved from 0.70 to 1.00.

### What is open

**The human's reason.** 44 graded drafts hold both reads and the grades. One
comment on one of them becomes a judged rule.

**WP7's ten itineraries.** The ten requests are checked and ready. D15 makes a
generation the owner's act.

**The phone runs the old code.** Its checkout pulled to `4e30a3f`. Its server
has run since 2023 by the process table, and a pull does not reach a running
process.

**Invariant 1.9 has no chokepoint and no test.** D17 and D25 hold it.

**`AUTH_ENABLED` is false.** The firewall now blocks the LAN and ZeroTier, and
the tailnet still reaches port 7001 with no login.

---

## 2026-09-07: the owner's comments, and the map the desk lacks

The owner read the graded drafts and left four comments. All four name routing
faults, and none of them names a wording fault.

### What the four comments say

**`dr-7d5c4865d7b1`, on `curated:cr-mthikj54`.** Sites repeat on days 3 and 4,
then again on 6 and 7. The arrival is Basra, so the sequence should run BANA2,
then URUKNJ, then KABBBG. Mosul sits far from Sulaymaniyah, and the last few
days carry many problems.

**`dr-1d40984884cc`, on `curated:cr-mto8t3ra`.** The request names Western Iraq
and the Nineveh Plains, so the sequence should run SAFA, SAMO, MO1EB.

**`dr-52cf8650ce00`, on `curated:cr-mtgn4c5d`.** A ten-day trip arrives in
Baghdad and BG1CT is right. Every day to day 6 is good. Days 7, 8 and 9 are
wrong. SAFA is a Baghdad day trip, and day 7 leaves Baghdad for Mosul. Samarra
also appears twice, on day 7 and on day 8.

**`dr-f6f387710a8a`, on `queue:qr-mt4jveb4-99906312`.** A standard ten-day
itinerary starts in Baghdad and ends in Erbil.

### Three faults the comments share

**A site appears on two days.** The 60 templates carry 57 distinct site codes
between them, and a site sits in several templates. `ERB_CITD` sits in 9,
`NA_UR` in 7, and `NA_URUK` in 6. A sequence that picks two of those templates
sends a customer to one site twice.

**A day trip carries the day that leaves the city.** SAFA sleeps in Baghdad, so
it cannot be the day the trip drives to Mosul. Four codes carry no overnight
city at all: BANA, BB, MOBKHEB and SUEBDEP.

**Two consecutive codes name cities a car cannot join.** Mosul and Sulaymaniyah
sit at opposite ends of the north.

### The map the desk holds today

The desk knows an overnight city per code, and nothing else about geography.

Twelve cities carry a night, over 60 codes:

    Baghdad 10   Erbil 12   Najaf 7   Nasiriyah 5   Basra 4
    Duhok 4      Mosul 4    Sulaymaniyah 4   Karbala 3
    Korek Mountain 2   Soran 1   and 4 codes with no night

The counted book holds 24 move rules over the sent offers. They say which pairs
the work actually joins, and how often:

    Erbil -> Erbil          52 of 71     Karbala -> Nasiriyah   104 of 186
    Rezan -> Erbil          10 of 14     Mosul -> Mosul         134 of 256
    Sulaymaniyah -> Erbil   19 of 31     Baghdad -> Baghdad     369 of 709
    Nasiriyah -> Baghdad   102 of 196    Najaf -> Karbala        50 of 100
    Basra -> Nasiriyah      36 of 79     Baghdad -> Mosul       171 of 709
    Mosul -> Duhok          61 of 256    Duhok -> Erbil          17 of 66
    Baghdad -> Karbala     118 of 709    Mosul -> Erbil          53 of 256

**No pair joins Mosul to Sulaymaniyah, in either direction.** The corpus holds
no such move, which is the same thing the owner said in words.

### What the desk does not hold

No drive time, and no distance. Nothing in the catalogue or the corpus states
how long a leg takes.

No neighbour list. The move counts say which pairs the work joins, and they say
nothing about a pair the work has never tried.

No site index across a sequence. `included_sites` sits on each template, and
nothing compares two templates in one proposal.

No day-trip marker. A reader tells a day trip from a transit only by reading
the overnight city, and four codes carry none.

## 2026-09-07: the map, the checks, and the tie-break

The owner's four comments named three routing faults. This pass built the data
and the checks that find them, and it wired them to the desk.

`phase-four-spec.md` sits beside this file. It holds decisions D28 to D37 and
work packages WP11 to WP15.

### What was built

Five modules, all new.

`services/itinerary/move_map.py` holds where places are and which pairs the work
joins. 34 places with a coordinate, and the counted moves with no floor applied.
`resolve_place` is the one place-name authority in the repository: four sources
spelled places four ways, and `binder`, `site_index` and `sequence_check` now
all read through it.

`services/itinerary/site_index.py` reads the ticket index. The handover said no
site index exists. It has been in `services/offers/data/pricing/entry_tickets.json`
all along, where 76 sites each carry a city, a region and a closing day. It was
written to price a ticket and it answers a routing question for free.

`services/itinerary/sequence_check.py` finds six faults and raises flags.

`services/itinerary/day_shape.py` says where each template's day starts, where
it ends, and what job it does.

`services/itinerary/named_pair_rules.py` reads a judged rule that names two
template codes.

The desk shows all of it. Each sequence carries a check, the faulty days are
ringed in the chip row, and the machine notes sit in their own card.

### What the owner settled

The catalogue could not say where 21 templates start their day. `SAFA` reads
"Samarra / Baghdad area" and sleeps in Baghdad, and it truly starts in Baghdad
and comes back. Read as a chain it looks like a transit out of Samarra.

The owner read all 21 and gave a start, an end and a role for each. Two answers
changed the shape of the question:

`BB` is a day tour with no start of its own. Babylon sits 44 km from Karbala
and 99 km from Baghdad, and a trip reaches it from either. One named start
would hide it from the other city.

A template needs two fields and not one. The owner's first two corrections named
end cities, and the column asked for a start.

`day_shape.OWNER_SETTLED_SHAPES` holds the 21. Two more templates carry a role
and no start: `ArrSU` reads "Drive to Sulaymaniyah" and `NA1` reads "Drive
South", and nobody has said where either drives from.

### The rules the owner set this pass

A move counts in either direction. The corpus drives Mosul to Duhok 61 times and
Duhok to Mosul never, and that is one road of 69 km. Mosul to Sulaymaniyah is
zero each way and stays refused.

Two or more sites shared by one day pair is a fault. One shared site is a flag.
The unit is the day pair and not the site, so four sites shared by days 3 and 4
is one fault about two days.

The rule reads any two days of the trip. `SAMO` on day 2 and `SAFA` on day 9
send a customer to Samarra twice, and seven days between them changes nothing.

The same template on two days is a fault, whatever the site count.

Two flags on one trip break the cap.

A machine note has its own list. `comments` is the raw material of a judged rule,
and a note there would enter the rule queue and read as the owner's words.

`SAFA` with `SAMO` is a penalty and never a refusal. The penalty lifts when the
request names the west and the north over 7 days, where the days have to be
filled with relevant sites.

### What the numbers say

    codes the binder reaches      48 -> 52 of 60, ceiling 58
    site repeats, ten proposals   14 -> 9
    same-template repeats          4 -> 0
    nights in the offer's city    58 of 116, unchanged
    sites the route text names    44 of 55 by word, 24 by exact string

The nights did not move. Every part of the tie-break picks a better code for a
night the matched route already chose. `find_best_route` returns the first of 5
to 11 routes that tie at the top score, and that holds the larger part of the
50 percent.

### Two things that were learned the hard way

The first tie-break made everything worse. Reach fell from 48 to 45, site
repeats rose from 14 to 15, and flags rose from 6 to 15. The site score had no
memory, so two days that both name Samarra both pulled the Samarra template.
Threading the used sites through the bind loop repaired it, and the numbers
that forced the repair are in the docstring.

The `SAFA` condition was inverted on the first attempt. A 12-day request through
the west and the north came out as a fault, when the owner said `SAFA` is
penalised and never rejected. The rule now always gives a flag, and the flag
says which of the two things happened.

### Five defects found in code written the same day

`leg()` resolved a place for the distance and not for the count, so a leg named
the ticket index's way read as never carried while its distance proved the place
was understood.

`path_between` routed through a place the map does not hold, and resolved no
spelling at all.

`is_clean` ignored `untested`, so a sequence whose closing days were never tested
reported clean.

A sequence with no codes reported clean. Every check passes on nothing.

The desk offered "Generate from this" on a sequence with no codes. The route
answers 409, so the click could never work.

### Two catalogue rows to raise

`BANA` ends in Nasiriyah and its `overnight_city` cell is blank. `MOBKHEB` ends
in Erbil with the same blank cell, and it has the shape of a departure day.
Neither was changed. The sheet is the owner's, and invariant 1.3 binds.

### What is open

Two things rest on Claude's reading and not on the owner's word. The flag cap
ladder is one constant, `FLAG_CAP = 2`. The `SAFA` rule sits in the judged book
on a recommendation.

Three checks are buildable and are not built: a day that starts where the last
night did not end, a leg whose richer template was passed over, and a day trip
used on the day the trip moves on. `day_shape` holds the data all three need.

A flag does not yet lower a candidate's score. No candidate scorer exists.

The judged rule book still has no control on the desk. Three routes are served
and never called: `GET /comments`, `POST /comments/{draft}/{comment}` and
`POST /rules/judged`.

One stored sequence names a live endpoint. `dr-1181c61d5385` carries
`gemma4:31b-cloud` at `http://100.82.8.53:11434/v1/chat/completions`, dated
2026-09-05. It predates `phase-three-spec.md` by one day, so invariant 2.3
stands.

### Tests

125 new tests across five files: `test_move_map.py`, `test_site_index.py`,
`test_sequence_check.py`, `test_day_shape.py` and `test_named_pair_rules.py`.

The 14 files the frame prompt names still pass at 430.

---

## 2026-09-08: the layers, the desk, and the phone

Two phases landed and reached the phone. Phase five built four model layers, a
run record and the guards around them. Phase six rebuilt the desk as a queue
and one detail pane.

`phase-five-spec.md` and `phase-six-spec.md` carry the decisions, the
invariants and the work packages. This section records what happened.

### The four layers

Seven steps run on one press: read the link, extract the screenshots, write a
brief, build the candidates, check them, rank them, and read the result against
the request. Four steps are deterministic and three call a model.

Nothing calls a model today. `itinerary_model_proposals_enabled` is off, and a
layer that cannot run records itself as untested rather than reporting that it
found nothing.

Seven modules are new. `record_paths` gives one record id one file inside one
directory. `run_record` holds the seven steps. `layer_access` says which layer
may run and where it may send. `conversation_reader` turns a Drive screenshot
into text. `request_brief` reads what the customer asked for. `candidates`
builds one itinerary per route that ties at the top score. `offer_run` runs the
seven steps.

### The Drive folders opened

The owner shared the conversation folders on 2026-09-07. All six live links
read, and each names one `image/jpeg` file rather than a folder. That answered
the phase five open item 16.1.

### What the model measured

The owner lifted D17 for one test. Ten offers that were already sold ran
against `gemma4:31b-cloud`.

| Measurement | Value |
|---|---|
| Nights in position, three layers | 40 of 87 |
| Nights in position, the rules alone | 19 of 87 |
| Layer 2 against candidate 1 of the same set | 20 against 10 |
| Runs where layer 2 chose worse | 0 of 10 |
| Brief day count right | 4 of 10 |
| One run, four layers | 4 to 7 seconds |

The rules scored 7 of 87 before the normalizer read a graded row's `day_count`.
That one repair took them to 19.

### The desk

The desk was a dropdown of drafts beside a strip of ten request pills, with a
"Show ten more" button and no filter. It is now a queue and one detail pane.

The filter bar is the Operations bar, with a fifth control for the desk's own
state. `GET /drafts` sends a list: 51,646 bytes became 3,153.

The detail pane carries a strip of input, run and output above sections that
open on their own content. The seven steps render with their timings and their
endpoints. A prompt opens in a drawer, because three steps carry 16,205
characters against under 10,000 bytes of everything else.

One file renders the brief on both pages.

### What the live worklist says

| Fact | Value |
|---|---|
| Tour requests | 43. 37 curated, 6 queue |
| Status New | 9 |
| New rows carrying the risk `confirmed-spam` | 8 |
| New rows that are not spam | 1 |
| Open drafts | 10 |
| Requests carrying no operator | 17 of 43 |
| Requests carrying a next action date | 1 of 43 |

Item 27.5 said one press reaches 9 rows. The cross-tab says 8 of those 9 are
spam, so the count read spam as work. The item carries an amendment and the
figure is 1.

### Nineteen defects found by attacking the code

Five in the first pass over phase five. `PUT /conversations/{file_id}` wrote
wherever the id pointed: three files landed in the repository root and one in
`C:\Windows\Temp`. A run was left unsealed when the draft write failed. Four
presses at once wrote four run records and the draft named one. A screenshot
could close its own fence. A brief number had no ceiling.

Seven in the second. `column_is_blank` called an unknown column blank, so a
brief overwrote a value the record held. The diff said "the conversation says"
when no conversation was read. The model echoed the office's own figures back:
two entirely different requests gave one identical brief. The cache sat behind
Drive. Named cities could not reach candidate generation. The prose summary
varied at temperature zero while the fields did not, and layer 2 decided on the
prose.

Six in the third. A queue row never marked its regions defaulted on one branch
and did on the other. A placeholder read as more certain than a blank. An
unparsable day count read as a value the record gave. A record number had no
ceiling. A human edit on a folder id hid the folder.

Five in the fourth. The shared stylesheet defined seven tokens on bare `:root`,
and 236 call sites across 26 files changed colour. 192 of them read
`var(--accent, var(--red))`, and `theme.js` sets `--red` per theme. A draft that
named no request appeared in no queue row. A queue row read two invented day
codes as two finished days. `run_count` counted ids rather than records. The
brief card raised on a `differences` that was not a list.

Every one is pinned in `test_phase_five_attacks.py` or
`test_phase_five_attacks_two.py`.

### Two things measured that nobody had measured

None of the seven tokens the Operations modal reads is defined in any `:root`
block. The modal has been rendering on CSS fallbacks.

The app links to neither standalone page. `itinerary_desk.html` and
`offers_review.html` share ten CSS tokens and no navigation, and the one walked
path into the desk is the link in the Operations modal.

### The deployment

Four commits went to `origin/daily-driver` at `18d7079..b543292`.

The phone pulled from `4e30a3f` to `b543292`, nine commits, a fast-forward.
Its uvicorn had been up 4 days 23 hours. A SIGTERM to it let
`supervise_services.sh` call `Start_All.sh` within 75 seconds, which is the
restart that design asks for. `/api/itinerary/layers` answers 401 there now
rather than 404.

`data/` is gitignored, so 111 MB went over Tailscale as one archive in 69
seconds, checksum verified on arrival. `tar -k` extracted it, so no existing
file could be overwritten. The phone's `data/` went from 89 MB to 223 MB.

Five entries were held back by the owner's decision: `app.db`,
`scheduled_emails.db`, `projects`, `logs` and `email_urgency_cache`. The phone
keeps its own `app.db` of 839,680 bytes.

Two more were held back on Claude's reading. `.app_key` is on both machines and
the phone reads its own encrypted data with it. `auth.json` is on the phone's
neither side, and adding it would change who can sign in to a device that gates
on login.

The phone now holds a Google service-account private key and this machine's
`settings.json`. That file names `default_endpoint_id: 182e58cc`, which is a
row in this machine's `app.db` and not in the phone's.

### What is open

Item 29.4 is built and untested. Every run record on disk has the layers off,
so no step carries a prompt and no drawer button renders. Measurement 14.4
reads zero for that reason and not because a prompt was hidden.

Two items in `phase-six-spec.md` state that Claude chose them: the shared
stylesheet at 24.1, and sections that open on their own content at 28.3.

Two items in `phase-five-spec.md` state the same: the flag cap at 12.4 and the
judged book placement at 15.1.

Item 22.6 of phase five is blocked and the specification is wrong about it. It
asks the reader layer to reuse the `vision` role. `_resolve_vl_model`
auto-detects across every configured endpoint when `vision_model` is empty, and
its first candidates are hosted models, so reusing it would break invariant
3.2. The reader carries a role of its own.

`tests/test_signature_route_hardening.py` errors on
`test_signature_png_normalization_rejects_invalid_inputs`. It errors with every
change of these two phases stashed, so it predates them.

The `daily-driver` worktree at `odysseus-fork` sits at `a7869cb`, 54 commits
behind its own remote.

### Tests

Eight new files hold 175 tests: `test_layer_access.py`, `test_run_record.py`,
`test_conversation_reader.py`, `test_candidates.py`, `test_request_brief.py`,
`test_offer_run.py`, `test_phase_five_attacks.py` and
`test_phase_five_attacks_two.py`.

The itinerary and offers suites pass at 441.

## 2026-09-09: phase seven, and what reached the phone

Phase seven separated the two request kinds, split the regions, and shipped to
the phone. `phase-seven-spec.md` carries the decisions D58 to D66 and the work
packages WP32 to WP38. This section records what happened.

### What the owner's four comments turned out to mean

Half of them described code that no longer ran. The desk stores the rules
sequence once, when the draft opens, and never recomputes it. Six of the nine
worklist drafts stored an empty sequence, and none of the nine is empty today.
So the comments of 2026-09-07 read against sequences the code stopped
producing.

The half that survived was routing order, and the checker could not see any of
it. A day trip and a departure day carry no overnight city, so they take no
position in the night chain. Both faults the owner named sat on such a day.

### The four regions

The catalogue held three region names and the intake form offers four.
"Iraqi Kurdistan" and "Western Iraq & Nineveh Plains" were one value, so a
request for Mosul matched an Erbil route and reported coverage 1.00.

`services/itinerary/regions.py` now holds the four names, the label map, the
city map, and the seven templates whose work and hotel sit in different
regions. The normalizer and the matcher re-export from it. Three modules used
to answer the same question three ways.

A template's region is the region of its overnight city. Seven exceptions are a
written list: `SAFA`, `BGFA` and `MO1EB` in the west, and `NA2BG`, `NAURUKNJ`,
`URNJ` and `UrukNJ` in the south. Each works in one region and sleeps in
another.

The binder reads the owner's judgement first and the city second, and it binds
a day when the customer asked for either. Reading only the day's region
rejected the Ahwar marshes for a Central request and said "Overnight in
'Baghdad' (Southern Iraq)". Reading only the city put `SAFA` back in Central,
where no exception could reach it.

### Two templates the corpus already sold

`BGFA` is `SAFA` without Samarra: Fallujah by way of Abu Ghraib, the kebab for
lunch, and Dur-Kurigalzu on the way back. Four sold offers carry that exact day
(`offer_routes.json` lines 1939, 2246, 2375, 2685).

`MO1EB` is `MO1` with the drive to Erbil, and it is the only way out of the
plains. Two sold offers carry it.

The catalogue holds 62 active templates: 25 Kurdistan, 15 Central, 15 south,
7 west.

### The Samarra rule retired

`judged--safa-with-samo` had two faults. "nineveh plain" sat in both of its
word lists, so the label "Western Iraq & Nineveh Plains" satisfied both halves
of an `and` by itself. Its eight-day threshold sits below the one sold
precedent, which runs eleven days.

The corpus answers better: 258 of 335 sold offers visit Samarra and one visits
it twice. `SAFA`/`BGFA`, `MO1`/`MO1EB` and `NA2BA`/`NA2BG` are alternative
pairs instead. The binder marks a bound code's alternative as used, so a
proposal cannot hold both halves.

The rule file stays on disk with its statement rewritten to say it retired and
why. `.gitignore` excludes `data/`, so that text never travels.

### Three faults arrived

`day_start` catches a day that starts where the night before did not end.
`role_order` catches a departure day with days after it. `alternative_pair`
catches both halves of one day sold two ways.

`day_start` found the two faults the owner named and the checker called
clean. `FAULTS_NOT_YET_FOUND` now holds two entries, not three.

### The Curated record

The reader asked for `dietaryNeeds`, `heatWalkingComfort` and
`hotelChangePreference`. The form sends `dietaryRestrictions`,
`walkingDifficulty` and `hotelChangeTolerance`. It never read `journeyTypes` at
all, which is the richest field the form carries.

So the kind that needs no follow-up reached the matcher with one note, and the
kind that does reached it with ten.

`accommodation` arrives as a list, and `str(["5_star"])` matched no tier, so
all five live Curated records priced at three star. That was the only defect in
the phase that cost money on every request.

### The tie-break

The rules proposer answered from `find_best_route`, which returns the first of
the several routes that tie at the top. Phase four measured that tie at five to
eleven routes. Three tied at 0.83 for one live request and bound 1, 3 and 3
days.

`_best_binding_route` binds every tied route and keeps the fullest. Without it,
five of the nine live requests bound fewer days than before the region split.

### Where it went

Commit `466c3f1`, 72 files, +1534 −565.

Branch `ws-03/phase-seven-request-kinds-and-regions` on `origin`. `main` here
has no upstream, so the work went to a branch rather than to `main`.

`origin/daily-driver` fast-forwarded `f13282f..466c3f1`. The `odysseus-fork`
worktree fast-forwarded five commits to the same point.

The phone pulled to `466c3f1` over Tailscale. It loads 62 templates with the
four regions under its own venv.

### The phone has no offer corpus

`counted_moves()` returns zero pairs there. This machine returns 79, with
Baghdad to Mosul at 171 and Mosul to Erbil at 53.

`ODYSSEUS_DATA_DIR` is `/data/data/com.termux/files/home/odysseus-data`, and
`offer_corpus` inside it holds nothing. The 335 offers under
`/root/odysseus/data/offer_corpus` are a stale copy the app never reads. The
test ran with the service's own `.env` loaded, so the empty result is not a
shell artifact.

Every `move_not_joined` check therefore fires on the phone, on legs the work
drives constantly. The trip `BGFA, SAMO, MO1EB` reports no fault here and two
there, and both of those are false.

This predates phase seven. Commit `466c3f1` touches no `move_map`,
`offer_store` or `rule_counter`. `.gitignore` excludes `data/`, so no pull
ever carries the corpus.

### Still open

The phone runs `uvicorn app:app` on port 7000 from `/root/run-odysseus.sh`. It
holds the pre-pull modules in memory, so the live app does not use the new code
until that process restarts.

The owner settled the 32 catalogue-derived start cities. He has not read the
region of every template. Only the seven exceptions carry a judgement.

`propose_by_model` still resolves `resolve_endpoint("default")`, which is the
chain `layer_access` exists to forbid. Phase seven left it alone.

### Tests

The itinerary suites pass at 312. Nine test files changed, because their
fixtures named regions the catalogue no longer holds and counts the catalogue
no longer has.

Two fixtures were measuring the corpus rather than the code. `test_offer_run`
injected one Baghdad template and loaded all 164 real routes, so it passed only
while a Baghdad route happened to tie first. `test_sequence_check` gave its
templates an overnight city and no chain, which reads as a city day that starts
where it sleeps.

`test_email_digest_urgency_file_parsing` fails. It fails with every change of
this phase stashed, so it predates them.
