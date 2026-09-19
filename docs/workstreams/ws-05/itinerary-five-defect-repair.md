# Itinerary repair for five boundary defects

This repair resolves B-T01 through B-T05 from the September 19 test report.
The default route and catalogue ownership remain unchanged.

| Defect | Disposition | Implementation contract |
| --- | --- | --- |
| B-T01: markup mismatch | Done | The desk reads `DEFAULT_MARKUP_PCT`, currently 10.0. Pricing fingerprints include that setting. |
| B-T02: unpriced hotel promises | Done | Pricing and document assembly share the included-night predicate. Hotel options and custom overrides exclude unpriced stays. Mixed stays name only included night numbers. |
| B-T03: null accommodation | Done | Null or malformed pricing tags create an unknown accommodation fact and block the plan. |
| B-T04: negated departures | Done | Negated, optional, or uncertain clauses cannot establish a departure or return. A dated reference to May remains valid evidence. |
| B-T05: invalid day numbers | Done | Source days accept positive integers and integer strings. Booleans, fractions, nulls, and invalid values receive a rejected disposition. |

Saved plans now use version 2.
Version 1 plans require recalculation before generation.
Recalculation appends results and preserves earlier sequences.
A later markup-setting change also expires a saved plan.

The document assembler applies the same accommodation rule to tours and day-trip documents.
An explicit hotel-inclusion selection cannot promise a stay excluded from its price.
No-hotels mode removes the hotel promise.
Overnight locations remain visible because a stay location does not establish hotel inclusion.

## Verification

The broad local focused run passed 622 tests.
The isolated phone integration run passed 320 tests.
The final source-parser follow-up passed 44 historical and boundary tests locally.
The same phone follow-up covers the dated-May correction.
The five browser logic tests passed.
The six original failing cases now pass without expected-failure markers.

The historical replay reconstructed 335 offers and compared six selected targets across 2024, 2025, and 2026.
It completed in 40.56 seconds and preserved every source offer hash.
Fifty-five offers still reconstruct completely.
The source pool now contains 234 usable records, 101 needing review, and 208 distinct usable routes.
One previously usable source offered an airport transfer or an optional overnight.
That source now needs review instead of establishing a definite departure.

All six existing requests passed the isolated acceptance run with plan version 2.
One draft remains ready. Five retain their existing request or catalogue blockers.
The ready draft, `dr-8a761ebcb5ca`, now quotes $1,531.84 at the shared 10% markup.
Its itinerary remains `SAMO`, `MO1`, `MOQOLA`, `AMBASO`.
No customer document or message was created during testing.
Network access was blocked during quote and historical replay tests.

The verified backup is `odysseus-itinerary-backup-20260919T125613Z`.
It contains 67 files and a SQLite snapshot with integrity result `ok`.
The snapshot contains 21 projects, 64 tasks, 36 sessions, and 14 schedules.
The deployment check must preserve source files, prior draft history, settings, and schedule states.

The remaining VAN, NA1, departure-template, date, and closure blockers are unchanged.
This repair does not invent their missing catalogue or request facts.
