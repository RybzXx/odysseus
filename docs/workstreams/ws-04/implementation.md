# Daily-driver reliability repair

## Authority and scope

The user selected option B: staged repair of the existing phone installation.
The specification is recorded in this conversation, revision 1, on 2026-09-18.
The user then selected Code and reaffirmed the customer-data prohibition. The user instructed us to disable affected model steps.
Customer enquiry text must not reach network models. This restriction is enforced in itinerary layer access.
No customer email is sent by this repair. Booking tasks remain paused.

## Baseline

- Phone and origin/daily-driver: 565a04fec1088479777d29e9902924f63507c25b.
- Local repair branch: codex/daily-driver-reliability.
- Active phone data: /data/data/com.termux/files/home/odysseus-data.
- Verified backup: /data/data/com.termux/files/home/odysseus-repair-backup-20260918T082611Z.
- Backup database integrity: ok. Restore counts: 21 projects, 64 project tasks, 36 sessions, 14 scheduled tasks.
- Files archive SHA256: b2567fc4ea017cde90440f038d6ac23a806d62fab21a65f955b3242804a60510.
- One earlier backup attempt is incomplete and has no verified.json. Do not use it for recovery.

## Specification checklist

| Item | Requirement | Status |
|---|---|---|
| 1.1 | Preserve phone data and paused tasks | In progress: compare after deployment |
| 1.2 | Establish exact baseline | Done |
| 1.3 | Exact-commit deployment with branch and dirty-file refusal | Implemented. disposable-repository tests pass |
| 1.4 | Verified backup and isolated restore | Done |
| 2.1 | Shared project access rule | Implemented. cross-owner route/tool tests pass |
| 2.2 | Child IDs and linked resource ownership | Implemented. mismatch and private-link tests pass |
| 2.3 | Project tool capability registration | Implemented. existing gate tests pass |
| 2.4 | Explicit itinerary proposer role | Implemented. no default endpoint fallback |
| 2.5 | Customer-data network prohibition | Implemented. user reaffirmed policy. regression tests pass |
| 3.1 | Compatible ChromaDB and supervision | Pending phone recovery |
| 3.2 | Data migration with hashes and conflict refusal | Implemented. copy/repeat/rollback tests pass |
| 3.3 | Missing corpus means untested | Implemented. regression tests pass |
| 4.1 | Accurate booking outcomes | Implemented. failure/empty/partial tests pass |
| 4.2 | Do not repeat uncertain Gmail appends | Implemented. persistent receipts. validation pending |
| 4.3 | Scheduler poll timestamp separate from task history | Implemented. publisher tests pass |
| 4.4 | Preserve heartbeat consumer fields | Implemented. end-to-end validation pending |
| 5.1 | Remove stale asset assertion and scheduler test contamination | Implemented. combined gate tests pass |
| 5.2 | Focused and complete Linux regression checks | In progress |
| 5.3 | Authenticated mobile and runtime workflow checks | Pending |
| 6.1 | Separate verified release stages | Pending |
| 6.2 | Rollback preserves later data | Migration rehearsal passes. deployment rehearsal pending |
| 6.3 | Record deployed commit and limits | In progress |

## Contradictions and surprises

The prior heartbeat used a nonexistent created_at column. Using started_at alone would still produce false scheduler-dead alarms during idle periods. The implementation therefore preserves scheduler_tick_at but sources it from completed scheduler polls. last_task_started_at is independent.

The phone has cloud model settings despite the older customer-data prohibition. The user explicitly retained that prohibition. All itinerary model layers refuse before resolving endpoints when enabled. Deterministic checks continue.

The initial project tests also exposed repeated completion inflating task counters. The tool now updates counters only when completion changes, and writes task changes to the manifest.

## Validation so far

- Existing focused ownership/capability/itinerary/scheduler suites: 203 passed.
- New and adjacent repair suites: 78 passed.
- Broader focused run: 391 passed, one Windows fsync failure in the new migration utility. Repaired by opening the temporary file for writing before fsync.
- Migration and deployment refusal/rollback tests after that repair: 3 passed.

## Recovery procedure

Preserve the live database during code rollback. Create a revert commit for the failed stage, check it, and deploy that exact commit with scripts/deploy_revision.py. Do not reset the phone branch or restore the whole database over newer activity.

Each data reconciliation writes a manifest outside the active data directory. scripts/reconcile_phone_data.py --manifest PATH --rollback --apply removes only created files whose hashes still match. It keeps modified files and unrelated new data.

Restore service scripts from the verified backup only if that stage failed. Keep migration originals and all backup artifacts.
