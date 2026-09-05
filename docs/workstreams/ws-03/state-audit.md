# ws-03 state audit — 2026-09-05

Read-only stage. Tests every factual claim in `handover.md` against the artifacts
on this machine. Writes this file and nothing else; the corpus, the review queue
and the gap summary were not modified.

Scope: `odysseus-agent-1` and its two sibling working directories. The standalone
`WebOperationsBilW` checkout is out of scope by owner decision; its state is
recorded below as unmeasured.

Evidence labels per `00-PROTOCOL.md`: MEASURED, SOURCED, INFERRED. Raw commands
and output are in the Measurements appendix.

---

## Verdict table

| # | Handover claim | Verdict | Actual | Evidence |
|---|---|---|---|---|
| 1 | Corpus: 332 offers, 126 MB | **Superseded** | 335 offers, 128 MB, 2424 days | MEASURED |
| 2 | Fourth recovery pass was in flight | **Confirmed — and it completed at 11:24 during this audit** | See the addendum; the corpus is final at 335 for the 24-month window | MEASURED |
| 3 | Failures recorded in full | **Confirmed** | 331 records in `data/offer_recovery_failures.json` | MEASURED |
| 4 | ~26 rejected attachments are real offers | **Unverifiable from artifacts** | Reason strings do not distinguish a day tour from a contract | MEASURED + INFERRED |
| 5 | Queue: 48 pending, built from 68 offers | **Confirmed** | 48 pending, created 2026-09-04 13:04; 68 offers existed by 10:00 that day | MEASURED |
| 6 | Gap summary: stale, measured on 68 offers | **False — worse than stale** | The file records **2 offers, 3 days, coverage 0.3333** | MEASURED |
| 7 | Tests: 138 passing in the four `test_offers_*` files | **Confirmed** | 138 passed in 10.72 s | MEASURED |
| 8 | Five commits unpushed | **False** | Zero. `origin/daily-driver` == `HEAD` == `b42e8d5` | MEASURED, local ref only |
| 9 | Remote `daily-driver` | **Imprecise** | `daily-driver` is a *branch* on remote `origin` | MEASURED |
| 10 | Three sibling checkouts | **Reframed** | Not clones — three **worktrees of one repository** | MEASURED |
| 11 | Credential must be placed by hand | **Confirmed, and present here** | `data/bilweekend_service_account.json`, 2339 bytes, valid | MEASURED |
| 12 | Reconciliation is stale | **No artifact exists** | `reconcile()` computes and prints; nothing is persisted | MEASURED |
| 13 | Full suite has 123 pre-existing failures | **Unmeasured** | Not run this pass — see Unknowns | — |

---

## Findings

### 1. The corpus is 335 offers and structurally intact

MEASURED. 335 directories under `data/offer_corpus`, 128 MB, loading to 335
`SentOffer` objects carrying 2424 days between them. No offer has zero days.
Every directory holds exactly three files: 335 × `offer.json`, 335 × `text.txt`,
333 × `source.pdf` and 2 × `source.docx`. There are no partial writes.

### 2. Recovery ran in four bursts, and the last one left no failure record

MEASURED, from `offer.json` mtimes:

| Local time | Offers written |
|---|---|
| 2026-09-04 21:00–21:59 | 68 |
| 2026-09-04 22:00–22:59 | 61 |
| 2026-09-04 23:00–23:59 | 126 |
| 2026-09-05 02:00–03:59 | 77 |
| 2026-09-05 10:03 | 3 |

The first 68 `offer.json` files were rewritten at 21:00 over `source.pdf` files
fetched at 10:00 the same morning — a reparse, not a fresh fetch. That group is
the 68-offer corpus the handover names.

255 + 77 = 332, the handover's figure. The three offers at 10:03 postdate it.

**This paragraph originally inferred that the 10:03 run did not complete. That
inference was wrong, and the addendum below records what actually happened.**
It was drawn from `data/offer_recovery_failures.json` having an mtime of
2026-09-05 05:42, earlier than the three offers it should have accounted for.
The reasoning did not account for the pass still being alive at audit time.

### 3. The failure record holds 331 rejections in two reason families

MEASURED. 277 "no itinerary in this document"; 54 "no text recovered from
<filename>". By account: 296 `book@bilweekend.com`, 35 `mahdi@bilweekend.iq`.

The record carries `message_id`, `attachment`, `reason`, `account` — and nothing
that separates a day-tour offer from a signed hotel agreement. 131 attachment
*names* match travel keywords, but that set contains `Bil Weekend Tours Catalog
2024.pdf` (24 copies), guide biographies and rate sheets alongside genuine
candidates such as `Babylon Day Tour (1).pdf`, `Samarra Day Tour (5).pdf`,
`Najaf & Karbala Day Tour (1).pdf`, `Baghdad Day Tour (9).pdf`. 131 is an upper
bound on a filename heuristic, not a count.

The handover's "roughly 26" is neither confirmed nor contradicted here. Nothing
in the artifacts supports or refutes it; establishing the real number means
reading the rejected documents.

### 4. `catalogue_gap.json` does not describe the 68-offer corpus

MEASURED. The file is 301 bytes and reads:

```
offers = 2      total_days = 3      matched = 1
near_miss = 0   unmatched = 2       coverage = 0.3333
measured_at = 2026-09-04T10:52:16+00:00
never_matched_codes = []            never_referenced_codes = []
```

`measured_at` is 13:52 local on 2026-09-04. At that moment 68 offers were on
disk and the 48-proposal queue was 48 minutes old. Both writers of this file —
`recover.py:87` and `POST /api/offers/proposals/rebuild` — persist
`len(offers)` from the live corpus, so neither should have produced `offers = 2`
at that time.

The route's own docstring states the reason the summary is persisted rather than
recomputed: *"a fresh measurement beside a stale queue would show two different
gaps with no way to tell which the proposals came from."* That invariant is
currently violated. The number `/offers` shows a reviewer is derived from two
offers; the queue beside it is derived from 68.

The handover's coverage figures — 35.0% before the autojunk fix, 47.7% after —
are not in this file and are not recoverable from it. They are SOURCED from the
handover only.

### 5. Nothing in the queue records which corpus produced it

MEASURED. 48 proposals, all `pending`, 42 `new` and 6 `revision`, `created_at`
clustered at 2026-09-04T10:04Z. Proposal keys are `proposal_id`, `kind`,
`fields`, `evidence_day_keys`, `occurrences`, `target_code`, `nearest_code`,
`nearest_score`, `status`, `reviewer_note`, `created_at`, `decided_at`,
`applied_at`.

There is no corpus-size, corpus-hash or `measured_at` field on a proposal. A
fresh queue and a queue derived from a corpus five times smaller are
indistinguishable by inspection. The staleness the handover reports in prose is
not represented in the data.

### 6. The gap-path defect the handover reports as fixed is in fact fixed

MEASURED. `data/catalogue_gap.json` had mtime `2026-09-04 13:52:16.534098200`
before the test run and the identical mtime after 138 tests passed. Tests no
longer write the real summary. `save_summary` and `load_summary` both resolve
`path or GAP_SUMMARY_FILE` at call time, with the reason recorded in a comment
at `services/offers/gap_report.py:259`.

### 7. Everything is pushed, and the three checkouts are one repository

MEASURED:

```
HEAD                  b42e8d5   (odysseus-agent-1, branch main)
origin/daily-driver   b42e8d5
daily-driver          a7869cb   (odysseus-fork worktree)
local-agent-2         a7869cb   (odysseus-agent-2 worktree)
origin/local-agent-2  a7869cb
origin/local-agent-1  555825f
```

`git rev-list --count origin/daily-driver..HEAD` is 0, and the reverse is 0.
The five commits the handover lists as unpushed — `d12dbfb`, `de66b5a`,
`2dd1180`, `0b2d970`, `5a1ea4c` — plus two later commits `a88f9a3` (the handover
itself) and `b42e8d5` (its correction) are all at or below the remote-tracking
ref. The working tree is clean: zero entries from `git status --porcelain`.

Two corrections to the handover's framing:

- There is no remote named `daily-driver`. Remotes are `origin`
  (`github.com/RybzXx/odysseus.git`) and `upstream` (`github.com/odysseus-dev/odysseus.git`).
  `daily-driver` is a branch. There is no `origin/main`.
- `odysseus-agent-1`, `odysseus-agent-2` and `odysseus-fork` are worktrees of a
  single repository, per `git worktree list`. The ws-02 changelog and
  `tool_capabilities.py` appearing in all three is a consequence of that, not
  evidence of divergent copies.

The local branch `daily-driver` (`a7869cb`) is a different line of work from
`origin/daily-driver` (`b42e8d5`) and is not part of ws-03.

### 8. The Google credential is present on this machine

MEASURED. `data/bilweekend_service_account.json`, 2339 bytes, written
2026-09-04 11:57, parses as JSON carrying `client_email`, `client_id` and
`private_key`. It is ignored through the blanket `data/` rule at `.gitignore:28`
— as are `data/offer_corpus`, `data/catalogue_gap.json` and
`data/template_proposals`. This is the machine the work was built on.

### 9. The reconciliation has no persisted form

MEASURED. `services/offers/reconcile.py` exposes `reconcile()` and
`format_reconciliation()`; neither writes a file, and no reconciliation artifact
exists under `data/`. The handover's "the reconciliation is stale" therefore
refers to a number reported in conversation, not to a file that can be inspected.

Its inputs are present: `services/itinerary/data/routes.json`, 1.88 MB, 164
legacy routes, dated 2026-06-22; and 28 templates via `load_template_texts()`.
The "128 legacy offers with no surviving source" figure is SOURCED from the
handover and cannot be checked without re-running the comparison.

---

## Contradictions and surprises

**The gap summary is not stale — it is wrong.** Every stated concern about it
assumed a 68-offer measurement awaiting a 335-offer rebuild. The file holds a
two-offer measurement written 48 minutes after the queue it is meant to
accompany. Neither known writer explains it.

**The push already happened.** The handover's most operationally specific claim —
five named unpushed commits — no longer holds, and two commits made after it
are on the remote too.

**Three checkouts are one repository.** Flagged during framing as a possible
divergence risk; it is not one.

**The corpus is clean.** 335 of 335 directories complete, zero malformed offers.
A recovery process killed three times left no partial state.

---

## Unknowns

| Unknown | Why it is unknown | Cost to close |
|---|---|---|
| Whether `origin` actually holds `b42e8d5` | No `FETCH_HEAD` exists; the remote-tracking ref reflects a local push, not a verified fetch | One `git fetch --dry-run` |
| Whether the 2026-09-05 10:03 run completed | Inferred from a missing failure-record write | Read the run's log, if one survives |
| What wrote `offers = 2` into the gap summary | Both known writers persist the live corpus size | Trace shell history / server logs for 2026-09-04 13:52 |
| How many of the 331 rejections are real offers | The record stores no document classification; filename matching gives 131 as an upper bound | Read the rejected documents |
| Full-suite baseline of 123 failures | Not run — the suite once hung at ~90% on an `rglob` walk, and the four offers files were the stage's scope | One full `pytest` run, timeboxed |
| Coverage at 335 offers | `analyse_catalogue_gap` over the full corpus takes minutes and its persistence is a write; out of scope for a read-only stage | One measured run, ~3 min per 4000 days |
| `WebOperationsBilW` state, incl. `c4170ae` | Out of scope by owner decision | — |

---

## Addendum — 2026-09-05, later the same day

The corpus-finality check was run as a follow-on read-only stage. It resolved
finding 2 by observation rather than inference, and it changed three other rows.

### The fourth pass was still running during the audit, and completed at 11:24

MEASURED. `data/offer_recovery_failures.json` was rewritten at 11:24:37 while
this audit was in progress: 331 records became 328, 80196 bytes became 79450.
By reason, 277 "no itinerary" became 274; "no text recovered" stayed at 54. By
account, `book@bilweekend.com` went 296 → 293; `mahdi@bilweekend.iq` stayed at 35.

The three records that disappeared are the three offers stored at 10:01–10:03:

| Attachment | Mail date | Rank by mail date |
|---|---|---|
| `Baghdad and The South in 8 days (1).pdf` | 2024-11-12 | 32 of 335 |
| `Baghdad and The South in 7 days.pdf` | 2024-12-02 | 50 of 335 |
| `Baghdad and The South in 7 days (1).pdf` | 2024-12-02 | 54 of 335 |

All three appeared in the 331-record file under "no itinerary in this document"
and are absent from the 328-record one. They now carry empty
`extraction_warnings`.

`recover.py` writes the failure record once, in `w` mode, after every account
has been walked. A record dated 11:24:37 is therefore a completed pass, not a
snapshot. The corpus is final at **335 offers** for the 24-month window.

INFERRED, high confidence: the pass ran with `--months 24` or wider. The default
is 7, and all three recovered offers are from November–December 2024, outside a
7-month window anchored anywhere in 2026.

### Why the fix landed exactly when it did

MEASURED, from `git log --date=iso`:

```
10:00:10  5a1ea4c  fix(offers): read a day number that runs into a weekday
10:01     (offer stored)
10:01:59  a88f9a3  docs(ws-03): handover for an agent with no memory of this work
10:03     (two offers stored)
10:09:01  b42e8d5  docs(ws-03): correct the handover on what lives outside this repo
11:24:37  (failure record rewritten — pass complete)
```

The three rescues follow the weekday-adjacency parser fix by roughly a minute.
INFERRED, high confidence: they are that commit's yield, recovered by a pass
that was already walking the mail when the fix landed.

### Two hazards in the failure record found while checking

**A run with zero failures leaves the previous record in place.**
`services/offers/recover.py:143` guards the write with `if all_failures:`. An
empty result writes nothing, so a stale record is indistinguishable from a
current one that happened to find nothing. MEASURED by inspection.

**Any run overwrites the whole record with its own scope.** The write is `w`
mode over `all_failures` for that run. A narrower invocation — `--account`, or a
shorter `--months` — silently replaces a full-corpus rejection record with a
partial one, and nothing in the file states its scope. MEASURED by inspection.

Both belong to the same class as the handover's own corrections and as finding
5: a process that does not record the conditions it ran under.

### The running server writes into this data directory

MEASURED. Two `app.py --port 7001` processes have been up since 2026-08-31,
launched with `odysseus-fork\venv\Scripts\python.exe` but running against
`odysseus-agent-1\data` — `data/app.db`, `data/settings.json` and
`data/scheduled_emails.db` were all written at 11:01–11:03 today, and
`data/logs/app.log` is live. `odysseus-fork/data` exists separately and holds no
offer artifacts. Neither directory is a link.

No scheduled task invokes recovery: the 11 rows in `scheduled_tasks` are email,
calendar and tidy jobs. The 11:24 write came from a standalone detached
`recover` process, which is no longer running.

### Rows this addendum closes

| Unknown from the table above | Now |
|---|---|
| Whether the 10:03 run completed | **Closed.** It completed at 11:24:37, MEASURED |
| Coverage of the 24-month window | **Closed enough.** Oldest recovered mail is 2024-08-25, beyond 24 months back from today |
| How many rejections are real offers | **Still open**, now 328 records rather than 331 |

### What this does to finding 5

It sharpens it. The audit's own inference about pass completion was wrong for
exactly the reason finding 5 names: the artifacts record results, not the
conditions that produced them. A failure record carrying its run's scope, window
and end time would have answered in one read what took a session to establish.

---

## Measurements appendix

All commands run from `D:\ai_projects_2026\odysseuswork\odysseus-agent-1` on
2026-09-05.

```
$ git rev-parse --abbrev-ref HEAD
main

$ git remote -v
origin    https://github.com/RybzXx/odysseus.git (fetch)
origin    https://github.com/RybzXx/odysseus.git (push)
upstream  https://github.com/odysseus-dev/odysseus.git (fetch)
upstream  https://github.com/odysseus-dev/odysseus.git (push)

$ git status --porcelain | wc -l
0

$ git worktree list
D:/AI_Projects_2026/OdysseusWork/odysseus-fork      a7869cb [daily-driver]
D:/AI_Projects_2026/OdysseusWork/odysseus-agent-1   b42e8d5 [main]
D:/AI_Projects_2026/OdysseusWork/odysseus-agent-2   a7869cb [local-agent-2]

$ git rev-list --count origin/daily-driver..HEAD
0
$ git rev-list --count HEAD..origin/daily-driver
0

$ git log --oneline -8
b42e8d5 docs(ws-03): correct the handover on what lives outside this repo
a88f9a3 docs(ws-03): handover for an agent with no memory of this work
5a1ea4c fix(offers): read a day number that runs into a weekday
0b2d970 fix(offers): actually write the recovery failure record
2dd1180 fix(offers): recover offers whose PDF lost every space
de66b5a feat(offers): rebuild the review queue from the command line
d12dbfb test(offers): pin what the reviewer is actually shown
c446240 docs(ws-03): move the workstream record into the repository it describes

$ find data/offer_corpus -maxdepth 1 -mindepth 1 -type d | wc -l
335
$ du -sh data/offer_corpus
128M    data/offer_corpus

$ find data/offer_corpus -maxdepth 2 -type f -printf '%f\n' | sort | uniq -c | sort -rn
    335 text.txt
    335 offer.json
    333 source.pdf
      2 source.docx

$ find data/offer_corpus -name offer.json -printf '%TY-%Tm-%Td %TH\n' | sort | uniq -c
     68 2026-09-04 21
     61 2026-09-04 22
    126 2026-09-04 23
     63 2026-09-05 02
     14 2026-09-05 03
      3 2026-09-05 10

$ find data/offer_corpus -name source.pdf -printf '%TY-%Tm-%Td %TH\n' | sort | uniq -c
     67 2026-09-04 10
     61 2026-09-04 22
    125 2026-09-04 23
     63 2026-09-05 02
     14 2026-09-05 03
      3 2026-09-05 10

$ python -c "from services.offers import iter_offers; ..."
offers loaded: 335
total days: 2424
zero-day offers: 0

$ python -c "json.load(open('data/catalogue_gap.json'))"
offers = 2
total_days = 3
matched = 1
near_miss = 0
unmatched = 2
coverage = 0.3333
measured_at = 2026-09-04T10:52:16+00:00
never_matched_codes []
never_referenced_codes []

$ stat -c '%y %s' data/catalogue_gap.json
2026-09-04 13:52:16.534098200 +0300 301

$ ls data/template_proposals | wc -l
48
$ python -c "... collections.Counter over proposals ..."
status: Counter({'pending': 48})
kind:   Counter({'new': 42, 'revision': 6})
created_at: [('2026-09-04T10:04:22+00:0', 10), ('2026-09-04T10:04:18+00:0', 6), ...]
corpus/offers/source/measured_at fields: None on all 48

$ python -c "json.load(open('data/offer_recovery_failures.json'))"
total 331
277 | no itinerary in this document
 54 | no text recovered from <filename>   (50 distinct filenames)
296 | book@bilweekend.com
 35 | mahdi@bilweekend.iq

$ stat -c '%y %s' data/offer_recovery_failures.json
2026-09-05 05:42:49.513312000 +0300 80196

$ PYTHONIOENCODING=utf-8 python -m pytest tests/test_offers_apply.py \
    tests/test_offers_module.py tests/test_offers_reconcile.py \
    tests/test_offers_routes.py -q
138 passed, 1 warning in 10.72s

$ stat -c '%y' data/catalogue_gap.json      # after the test run
2026-09-04 13:52:16.534098200 +0300         # unchanged

$ stat -c '%s bytes  %y' data/bilweekend_service_account.json
2339 bytes  2026-09-04 11:57:45.456521700 +0300

$ git check-ignore -v data/bilweekend_service_account.json data/offer_corpus \
    data/catalogue_gap.json data/template_proposals
.gitignore:28:data/   (all four)

$ python -c "json.load(open('services/itinerary/data/routes.json'))"
routes: 164            # 1882922 bytes, 2026-06-22

$ python -c "from services.offers import load_template_texts; ..."
templates: 28
```
