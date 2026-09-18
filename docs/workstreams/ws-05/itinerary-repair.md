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
| 1.1 | Preserve drafts, comments, runs, and task states | Pending phone comparison with backup |
| 1.2 | Block customer text from network models | Local privacy and direct API regressions pass |
| 1.3 | Keep option A scope | No new planner or catalogue templates |
| 2.1 | Use real activities and overnights for regions | Word boundaries and boilerplate regression pass |
| 2.2 | Measure bound coverage | Missing-south regression passes |
| 2.3 | Search beyond ties and five candidates | Lower-score eighth-route regression passes |
| 2.4 | Keep ranking deterministic | Reversed-corpus regression passes |
| 2.5 | Apply default only when regions are absent | Normalization regressions pass |
| 2.6 | Label the operator default | API and desk display its source |
| 2.7 | Check default length and connections | Default-route regression rejects incomplete results |
| 3.1 | Enforce connected binding | Missing-connection regression passes |
| 3.2 | Require exact length | Day-count check prevents shortened success |
| 3.3 | Check regions, sites, alternatives, closures, and roles | Existing and repair regressions pass |
| 3.4 | Separate invalid and unresolved results | Unknown dates and template starts remain unresolved |
| 3.5 | Reject invalid fallback | Offer-run regression leaves chosen codes empty |
| 4.1 | Convert applicable comments to tested behavior | Three corrections implemented, phone migration pending |
| 4.2 | Retire obsolete Samarra exception | Idempotent migration regression passes |
| 4.3 | Label deterministic results as rules | API and desk regressions pass |
| 4.4 | Display staleness and append recalculation | History-preservation API regression passes |
| 4.5 | Recheck at shared document boundary | Direct API and generator regressions pass |
| 5.1 | Test six unchanged requests | Initial phone diagnosis complete, final evidence pending |
| 5.2 | Run regressions locally and on phone | Local checks pass, phone suite running |
| 5.3 | Back up, deploy exact commit, and check UI | Pending release |

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
The final focused run passes 259 Python tests.
The desk behavior tests pass 3 Node tests.
Phone release evidence will be recorded after deployment.
