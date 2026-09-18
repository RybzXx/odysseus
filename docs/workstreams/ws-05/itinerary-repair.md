# Itinerary repair

The owner selected repair option A on 2026-09-18.
Repair the existing matcher and binder.
Do not add a new route planner or invent templates, transfers, or days.

The owner approved this default when regions are absent:
Baghdad → south → Mosul → Erbil.
Explicit customer regions take precedence.
The default must be identified as an operator decision.
Customer enquiry text must never reach network models.

## Contracts

The normalizer preserves explicit requirements and identifies defaults.
The binder enforces known start cities, end cities, roles, and unique days.
A missing connection produces an explicit gap.
Unknown template details remain unresolved.
The checker checks the bound sequence against the normalized request.
The selector checks all historical routes before it applies the display limit.
The generator rechecks the exact selected sequence before any document call.
A failed requirement or unresolved check prevents document generation.

A missing request value is an input gap.
A missing template is a catalogue gap.
A falsely clean result is an implementation defect.

## Executable corrections

- SAFA remains a Baghdad excursion when the itinerary does not continue north.
- Central and Southern trips reach Nasiriyah and the marshes, then return to Baghdad.
- Missing regions use the approved route through the south and Mosul to Erbil.

Each reviewed comment has an immutable text hash and a regression case.
The migration writes its rule before it changes the comment state.
The migration preserves the original comments and previous sequences.
The old Samarra exception remains in the book with retired status.

## Acceptance checklist

| ID | Requirement | Disposition and evidence |
| --- | --- | --- |
| 1.1 | Preserve drafts, comments, runs, and task states | Done. Original IDs, request data, comments, sequences, and run files preserved |
| 1.2 | Block customer text from network models | Done. Local privacy and direct API regressions pass |
| 1.3 | Keep option A scope | Done. No new planner or catalogue templates |
| 2.1 | Use real activities and overnights for regions | Done. Word boundaries and boilerplate regression pass |
| 2.2 | Measure bound coverage | Done. Missing-south regression passes |
| 2.3 | Search beyond ties and five candidates | Done. Lower-score eighth-route regression passes |
| 2.4 | Keep ranking deterministic | Done. Reversed-corpus regression passes |
| 2.5 | Apply default only when regions are absent | Done. Normalization regressions pass |
| 2.6 | Label the operator default | Done. API and desk display its source |
| 2.7 | Check default length and connections | Done. Default-route regression rejects incomplete results |
| 3.1 | Enforce connected binding | Done. Missing-connection regression passes |
| 3.2 | Require exact length | Done. Day-count check prevents shortened success |
| 3.3 | Check regions, sites, alternatives, closures, and roles | Done. Existing and repair regressions pass |
| 3.4 | Separate invalid and unresolved results | Done. Unknown dates and template starts remain unresolved |
| 3.5 | Reject invalid fallback | Done. Offer-run regression leaves chosen codes empty |
| 4.1 | Convert applicable comments to tested behavior | Done. Three tested corrections installed and their comments marked drafted |
| 4.2 | Retire obsolete Samarra exception | Done. Idempotent migration regression passes |
| 4.3 | Label deterministic results as rules | Done. API and desk regressions pass |
| 4.4 | Display staleness and append recalculation | Done. History-preservation API regression passes |
| 4.5 | Recheck at shared document boundary | Done. Direct API and generator regressions pass |
| 5.1 | Test six unchanged requests | Done. All six unchanged requests have current rules results and explicit readiness states |
| 5.2 | Run regressions locally and on phone | Done. Focused checks pass on both hosts. The separate timing issue remains open |
| 5.3 | Back up, deploy exact commit, and check UI | Done. Exact commit deployed, live UI and preservation checks passed |

## Initial phone diagnosis

The matcher evaluated all 164 historical routes for each of the six requests.
The initial repair produced one clean result and five explicit incomplete results.
No customer request changed during this evaluation.
Warm recalculation took about 0.7 seconds per request.
The first calculation took 3.5 seconds, including corpus loading.

The catalogue has no standalone Baghdad or Erbil departure template.
NA1 has no established start city.
These gaps must remain visible.
This repair does not invent the missing catalogue facts.

## Validation

The initial focused run passed 240 Python tests.
The repair regression file passes 19 tests.
The core focused run passed 259 Python tests on both hosts.
The final desk behavior tests pass 4 Node tests.
The final desk and pricing update passed 77 Python tests on both hosts.

## Release evidence

Phone branch: `daily-driver`.
Deployed commit: `74d6d454ac9da5c8fa256e905b18acef7a7f178a`.
The tracked phone checkout is clean.

The backup is `/data/data/com.termux/files/home/odysseus-itinerary-backup-20260918T104453Z`.
Its SQLite integrity check passed.
The archive check compared all 64 saved files with their SHA-256 hashes.
The earlier complete phone backup remains available.

The release preserved 21 projects, 64 project tasks, 36 sessions, and 14 scheduled tasks.
Scheduled task states did not change.
Settings and existing run records did not change.
Each draft retains its old sequences and comments.
Each draft now has one additional rules result.
The correction migration produced no changes on its second execution.
All five model steps remain blocked.
No test sent customer messages or created Google Docs.

The authenticated desk displayed the approved default, current rules result, and specific failures.
The desk displayed three enforced rules and one retired exception.
At a 390-pixel viewport, the document width was 375 pixels.
The build controls stayed disabled for incomplete routes and the missing vehicle.

## Six unchanged requests

| Draft | Requested days | Current result | Remaining blocker |
| --- | --- | --- | --- |
| dr-1d40984884cc | 3 | KABBBG → SAMO → MOBKHEB passes itinerary checks | VAN is absent from transport pricing |
| dr-7d5c4865d7b1 | 12 | Best diagnostic result has 10 days | Day shortfall, Friday palace closure, and unknown NA1 start |
| dr-8a761ebcb5ca | 4 | Four-day diagnostic result | The binding omits requested Kurdistan |
| dr-d33c56936b7a | 10 | Ten-day diagnostic result follows the south and Mosul | Erbil departure missing, Saturday palace closure, and unknown NA1 start |
| dr-f6f387710a8a | 10 | Ten-day diagnostic result | Erbil departure missing, start date absent, and unknown NA1 start |
| dr-fabcba91c398 | 7 | Nasiriyah, marshes, and return to Baghdad now appear | Start date absent, unknown NA1 start, and missing catalogue departure |

All six remain blocked from document generation.
A passing route check does not imply that pricing is ready.
These are explicit gaps under option A, which permits an incomplete result when existing routes cannot bind correctly.

The five-traveller request needs an established vehicle code and capacity.
The current catalogue has no VAN entry.
LARGE_CAR records a minimum capacity of 5 and a maximum of 3.
The repair preserves these facts instead of inventing the intended values.
The owner received a clarification request for this catalogue conflict.

## Remaining test issue

The broad phone run used the initial repair snapshot.
It returned 6,889 passes, 11 skips, and two failures in 1,099.80 seconds.
One failure asserted the old Central Iraq default.
The approved-default assertion now passes.
The later follow-up returned 63 passes and one timing failure.

The remaining failure is `test_the_fingerprint_is_cheap_enough_to_take_on_every_request`.
It measured 0.309 seconds initially and 0.326 seconds on the follow-up.
The test requires less than 0.25 seconds.
The repair does not change that fingerprint implementation or relax the threshold.
This timing issue remains unresolved.
