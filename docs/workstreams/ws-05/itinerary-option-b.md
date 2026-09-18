# Option B: one resolved itinerary plan

The September 18 implementation retains the historical matcher and binder.
It adds shared day facts, explicit request constraints, and versioned generation checks.
The operator default remains Baghdad, then south, then Mosul, then Erbil.
Explicit requested regions take precedence.

## Contract and disposition

| Item | Requirement and done condition | Disposition |
| --- | --- | --- |
| B1 | MUST separate day role, endpoints, overnight status, and accommodation inclusion. Each saved day must identify its evidence. | Done in `resolved_plan.py` and `day_facts.py`. The desk displays day facts and source evidence. |
| B2 | MUST use one canonical place vocabulary. Punctuation and known aliases must not change a binding. | Done in `places.py`, binder, activity regions, move map, and pricing loader. H01 and H03 pass. |
| B3 | MUST account for every historical record. Duplicate routes must retain their references. Unresolved records must remain visible. | Done in `route_corpus.py`. The pool contains 235 usable records, 100 records needing review, and 209 distinct usable routes. |
| B4 | MUST distinguish required cities, sites, and endpoints from preferences. Missing or malformed requirements must block generation. | Done for explicit structured request fields. Free text and model suggestions do not acquire authority. |
| B5 | MUST check, price, and render the same resolved day data. Changes to request, catalogue, corpus, or prices must require recalculation. | Done. Generation passes the checked built days and quote to the renderer. Legacy results require recalculation. |
| B6 | MUST preserve draft history, comments, runs, and settings during migration. Incomplete results must identify their blockers. | Done. Local and live phone checks preserve prior sequences, comments, runs, and settings. |
| B7 | MUST replay historical offers, run focused tests on the phone, check a backup, and check the deployed service. | Done. Verification results below. |

The matcher remains responsible for route selection.
The catalogue remains responsible for actual start cities, overnight stays, included hotels, and vehicle facts.
A source record can reject a binding. It cannot silently rewrite catalogue facts.
Missing historical overnight text no longer means airport departure.
An explicit return can establish a day trip. Otherwise, the source needs review.
BANA cannot supply a Nasiriyah overnight while its catalogue omits that overnight.

The pool's usable status means its structural source checks passed.
It does not mean a human approved every source statement.
A candidate must still pass routing, date, request, and pricing checks.
Malformed source files remain visible as rejected records.
A missing local corpus exposes legacy references as needing review.

## Tests

The broad local focused run passed 577 tests before the final edge-case changes.
The final itinerary integration suite passed 285 tests locally and on the isolated phone checkout.
The later desk gate change passed all 77 desk tests locally and on the phone.
All seven historical defect regressions now pass.
The browser logic suite passed five tests, including evidence escaping and generation controls.
Tests did not send customer text to network models or create real documents.

The backup at `odysseus-itinerary-backup-20260918T150252Z` passed SQLite and archive integrity checks.
It contains 67 files plus the database snapshot.
The snapshot preserves 21 projects, 64 tasks, 36 sessions, and 14 scheduled tasks.

## Six phone drafts

The isolated acceptance run reused the six existing requests without changing their contents.
One request passes both itinerary and pricing checks.
The remaining requests retain concrete blockers.

| Draft | Requested days | Bound days | Readiness or blocker |
| --- | ---: | ---: | --- |
| `dr-1d40984884cc` | 3 | 3 | VAN has no transport pricing entry. |
| `dr-7d5c4865d7b1` | 12 | 11 | One day missing. The palace day falls on Friday. |
| `dr-8a761ebcb5ca` | 4 | 4 | Ready. `SAMO`, `MO1`, `MOQOLA`, `AMBASO` pass route and pricing checks. |
| `dr-d33c56936b7a` | 10 | 10 | Erbil departure missing. The palace day falls on Saturday. NA1 has no established start. |
| `dr-f6f387710a8a` | 10 | 10 | Erbil departure missing. Start date absent. NA1 has no established start. |
| `dr-fabcba91c398` | 7 | 7 | Start date absent. NA1 has no established start. |

Warm isolated recalculations took 4.02 to 6.16 seconds on the phone.
The first recalculation, which loaded the corpus, took 16.91 seconds.
These are measurements from this run, not response-time guarantees.

The BANA accommodation conflict and vehicle capacities still need catalogue authority.
No overnight stay, hotel inclusion, transport rate, or missing departure template was invented.
The earlier whole-suite fingerprint timing failure remains outside this change.
The full application suite is not claimed to pass.


## Historical replay

The final replay covered all 335 sent offers and the same 174 comparison targets as the baseline.
It completed in 346.95 seconds with socket connections blocked.
All source offer hashes remained unchanged.
The comparison requests infer day count, tour type, and regions from delivered offers.
They do not recover original customer requirements.
Known place aliases now contribute to region inference.
This changes the inferred regions for one of the 174 comparison targets.

| Top production candidate | Previous implementation | Option B |
| --- | ---: | ---: |
| Exact inferred day count | 141 / 174 | 151 / 174 |
| Exact sent overnight sequence | 14 / 174 | 11 / 174 |
| Passes code checks on a synthetic weekday | 48 / 174 | 95 / 174 |
| Also passes source-plan checks | Not measured | 95 / 174 |

Direct source reconstruction completes 55 of 335 offers, compared with 75 before the repair.
All 55 complete reconstructions retain the source nights.
The reduction exposes bindings that previously treated blank stays as departures or omitted an overnight.
It is not evidence of wider catalogue coverage.
Exact historical agreement remains low for broadly inferred requests.
The higher check-pass count does not establish customer-intent accuracy.

The older-only stress pool returns exact day counts for 147 of 174 targets.
It returns exact nights for three targets and a clean synthetic weekday for 59.
This pool deliberately includes raw records to test failure handling.
Production retrieval uses only the 209 structurally usable distinct routes.
Both paths use the current catalogue and full-corpus connection evidence.
They are retrospective comparisons, not a pure historical training evaluation.

The reproducible harness is `scripts/audit_sent_itineraries.py`.
The private results remain outside Git at `../scratch/option-b-sent-audit-results.json`.


## Phone deployment and live acceptance

The phone fast-forwarded `daily-driver` from `74d6d45` to implementation commit `f8cd4e9`.
The service restarted through its existing supervisor and returned HTTP 200 from `/api/health`.
The tracked checkout remained clean. The existing `phone_db_register.py` file remained present.

All six drafts received an appended rules result with plan version 1.
The selected draft recalculated through the browser.
The other five recalculated through the authenticated application API.
All six current results passed their version checks and reported no stale plan.
The ready draft enabled the Build the Google Doc control in the live page.
The incomplete draft kept its build control disabled and displayed its specific blockers.
No document was created during acceptance.

The preservation check passed for prior sequences, request contents, comments, runs, and document links.
Settings and scheduled-task states remained unchanged.
The database retained all 21 projects, 64 tasks, 36 sessions, and 14 schedules.
The live SQLite quick check returned `ok`.
All 335 sent offers and 72 catalogue JSON files retained their original SHA-256 hashes.
The existing three enforced corrections and retired exception remained present.
All affected network-model steps remained blocked.

The live evidence table displayed day roles, endpoints, overnights, accommodation inclusion, and source-day evidence.
At a 390-pixel viewport, the document width was 375 pixels.
The table uses its own horizontal scroll area.
The final display adjustment removes duplicate blocker text from the result summary.
The five browser logic tests still pass after that adjustment.

The release receipt is outside Git at `../scratch/option-b-release-check.json`.
The remaining five blocked drafts require the catalogue or request facts listed above.
Option B is implemented and deployed. It does not resolve those unknown facts by inference.
