# Daily-driver reliability repair

## Authority and scope

The user selected option B: staged repair of the existing phone installation.
This conversation contains the specification, revision 1, dated 2026-09-18.
The user then selected Code and reaffirmed the customer-data prohibition. The user instructed us to disable affected model steps.
Customer enquiry text must not reach network models. Itinerary layer access enforces this restriction.
This repair sends no customer email. Booking tasks remain paused.

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
| 1.1 | Preserve phone data and paused tasks | Done. Baseline IDs and scheduled task states preserved |
| 1.2 | Establish exact baseline | Done |
| 1.3 | Exact-commit deployment with branch and dirty-file refusal | Done. Refusal tests and staged phone deployments pass |
| 1.4 | Verified backup and isolated restore | Done |
| 2.1 | Shared project access rule | Implemented. cross-owner route/tool tests pass |
| 2.2 | Child IDs and linked resource ownership | Implemented. mismatch and private-link tests pass |
| 2.3 | Project tool capability registration | Implemented. existing gate tests pass |
| 2.4 | Explicit itinerary proposer role | Implemented. no default endpoint fallback |
| 2.5 | Customer-data network prohibition | Implemented. user reaffirmed policy. regression tests pass |
| 3.1 | Compatible ChromaDB and supervision | Done. Existing storage recovered. Controlled restart passed |
| 3.2 | Data migration with hashes and conflict refusal | Done. 1,937 files verified. Repeat inventory has no missing files or conflicts |
| 3.3 | Missing corpus means untested | Implemented. regression tests pass |
| 4.1 | Accurate booking outcomes | Implemented. failure/empty/partial tests pass |
| 4.2 | Do not repeat uncertain Gmail appends | Done. Durable receipt and interruption tests pass |
| 4.3 | Scheduler poll timestamp separate from task history | Implemented. publisher tests pass |
| 4.4 | Preserve heartbeat consumer fields | Done. Installed publisher produced independent signals at 09:15 UTC |
| 5.1 | Remove stale asset assertion and scheduler test contamination | Implemented. combined gate tests pass |
| 5.2 | Focused and complete Linux regression checks | Done. 6,884 passed and 4 skipped in the complete Linux run |
| 5.3 | Authenticated mobile and runtime workflow checks | Done within the limits below. API, hub, workspace, and task views pass |
| 6.1 | Separate verified release stages | Done. Ownership, privacy, recovery, and layout deployed in stages |
| 6.2 | Rollback preserves later data | Done. Migration and deployment rollback rehearsals pass |
| 6.3 | Record deployed commit and limits | See release evidence and limits below |

## Contradictions and surprises

The prior heartbeat used a nonexistent created_at column. Using started_at alone would still produce false scheduler-dead alarms during idle periods. The implementation therefore preserves scheduler_tick_at but sources it from completed scheduler polls. last_task_started_at is independent.

The phone has cloud model settings despite the older customer-data prohibition. The user explicitly retained that prohibition. All itinerary model layers refuse before resolving endpoints when enabled. Deterministic checks continue.

The initial project tests also exposed repeated completion inflating task counters. The tool now updates counters only when completion changes, and writes task changes to the manifest.

## Validation

- Existing focused ownership/capability/itinerary/scheduler suites: 203 passed.
- New and adjacent repair suites: 78 passed.
- Broader focused run: 391 passed, one Windows fsync failure in the new migration utility. Repaired by opening the temporary file for writing before fsync.
- Migration and deployment refusal/rollback tests after that repair: 3 passed.
- Phone focused repair suites: 233 passed.
- Expanded suites covering failures from the first complete run: 141 passed on Windows and on the phone.
- Complete Linux suite on e0ffc882471ae0265eb1488d69eac4d6da16fa8c: 6,884 passed, 4 skipped, 162 warnings in 1,060.20 seconds. The run used an isolated checkout and data directory. Its log is /tmp/odysseus-final-full.log on the phone. A local copy is ../scratch/odysseus-final-full.log.
- Later changes affect project layout only. JavaScript syntax and git diff checks pass. Live mobile verification covers the Projects Hub and workspace panels.
- The first complete run found 12 failures. Repairs covered optional organiser summary tables, summary ownership, project tool discovery, plan-mode restrictions, and test isolation. The repair retains the offer-corpus performance threshold. It passed in the final run.

## Release evidence

The phone baseline was 565a04f. The staged revisions were eccaf40, 9243108, e0ffc88, 0702cb1, and f7ba4e4. Each applied revision passed exact-commit validation and a supervised application restart. The final deployed revision is f7ba4e41177c0d1e93e27897e58dda10e6104376. Application health returns 200.

Live browser checks show that the project hub, workspace overview, and task controls fit both 390-pixel and 320-pixel phone viewports. Body scroll width equals client width. The workspace tabs remain visible, and the browser reports no frontend errors. The browser now uses its original viewport size.

The restored ChromaDB uses the existing data directory and version 1.5.9. A copied store passed an isolated startup check before the live store opened. The supervisor then recovered from a controlled ChromaDB stop in 27.3 seconds. The live store contains 113 indexed tools, 15 memories, and an empty RAG collection.

Data reconciliation restored 1,167 offer-corpus files, 40 rule files, and 730 template-proposal files. This includes 335 offer JSON files and 79 city pairs. All 1,937 destination hashes match their sources. Approval content and source files remain intact. Native Termux performs an atomic rename that refuses an existing destination. This avoids PRoot hardlink emulation. The final manifests are final-migration-offer_corpus.json, final-migration-ai_rules.json, and final-migration-template_proposals.json in the verified backup directory.

Authenticated checks show application readiness, project detail and structure reads, task reads, and itinerary policy refusals. Unauthenticated requests to protected routes return 401. Database integrity is ok. All baseline project, task, session, and scheduled-task IDs remain present. Scheduled-task states remain unchanged. The untracked phone_db_register.py file retains SHA256 e98d5b228c774d51ec60ede0dff4e6408b2d046fa8ab137ff594c7d7eb2ac883.

The installed heartbeat publisher produced device_online_at 09:15:00, scheduler_tick_at 09:14:25, last_task_started_at 09:04:26, and backup_success_at 09:00:38 UTC. The scheduler timestamp later advanced to 09:16:26. This shows that idle task history does not prevent scheduler liveness updates.

## Remaining limits

- The configured SearXNG service at localhost:8080 refuses connections. No SearXNG startup entry exists in the phone supervisor script. Search recovery needs a working instance or an explicit provider choice.
- Two laptop model endpoints return no available models or time out. Ollama Cloud returns 20 model names. Cloud availability does not authorize customer enquiry processing.
- Mailbox connectivity varies. All four accounts passed an earlier probe. The final probe reached three accounts, while the work mailbox timed out.
- Validation used no real customer email, Gmail append, or model generation. Booking tasks remain paused. Automated tests exercise append receipts and failure handling with simulated services.
- Local commits and the phone contain the repairs. The work did not publish a GitHub branch update or pull request.

## Recovery procedure

Preserve the live database during code rollback. Create a revert commit for the failed stage, check it, and deploy that exact commit with scripts/deploy_revision.py. Do not reset the phone branch or restore the whole database over newer activity.

Each data reconciliation writes a manifest outside the active data directory. scripts/reconcile_phone_data.py --manifest PATH --rollback --apply removes only created files whose hashes still match. It keeps modified files and unrelated new data.

Restore service scripts from the verified backup only if that stage failed. Keep migration originals and all backup artifacts.
