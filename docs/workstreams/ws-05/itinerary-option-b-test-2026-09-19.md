# Option B adversarial test report - 19 September 2026

This report records failures at revision `2419d82`.
The subsequent [repair](itinerary-five-defect-repair.md) resolves all five defects.

That revision fails the new boundary tests.
Five defects reproduce locally and on the phone as six failing cases.
Production code and live request data remain unchanged during this test task.

Tested production revision: `2419d829042f5a47e92ebe200ace68b4792665c6` on `daily-driver`.
The existing local focused suite passed 587 tests.
The browser logic suite passed five tests.
The new boundary suite has 16 passing controls and six strict expected failures.
Running with `--runxfail` produces six actual failures locally and on the phone.
Expected failures document open defects. They are not passing behavior.

## Findings

| ID | Priority | Observed defect | Reproduction and impact | Required result |
| --- | --- | --- | --- | --- |
| B-T01 | P1 | The desk supplies a 0.2% office markup while the shared pipeline default is 10%. | `generator.py:130` supplies `0.20`. The calculator divides this by 100. The live ready draft differs by $136.47 from the configured default. | The desk must use an explicit, consistent markup policy and percentage unit. |
| B-T02 | P1 | The document promises accommodation excluded from the resolved plan and quote. | A Baghdad overnight with no hotel tag passes readiness and has zero accommodation cost. `assembler.py:320` still adds the hotel promise. | Document inclusions and hotel options must follow the checked accommodation facts, including mixed stays. |
| B-T03 | P2 | Null pricing tags become known excluded accommodation. | `resolved_plan.py:100` reads through `field_of`, which converts `None` to `[]`. The unknown branch cannot execute. | Unknown accommodation data must remain unknown and produce a plan issue. |
| B-T04 | P2 | A negated airport transfer becomes a departure. | `No transfer to Erbil airport is included. Return to Erbil.` resolves as departure, despite an explicit return. | Negated or uncertain departure text must not establish a departure. |
| B-T05 | P2 | Malformed source day numbers become usable evidence. | `route_corpus.py:46` converts both `1.5` and `true` to day 1. Both records enter the usable pool. | Non-integer and boolean day values must retain a visible rejected or needs-review disposition. |

All findings have executable regression cases in `tests/test_itinerary_option_b_boundaries.py`.
The tests use synthetic source prose and temporary records.
They do not copy customer messages into the repository.

## Live price reproduction

The read-only quote test used draft `dr-8a761ebcb5ca` and its current saved plan.
The preview reports ready for generation.
The test kept its itinerary, travellers, rooms, hotel tier, and pricing data unchanged.
It changed only the markup fields to the shared configured default for the comparison.

| Measurement | Value |
| --- | ---: |
| Desk office markup | 0.2% |
| Shared configured default | 10.0% |
| Desk three-star total | $1,395.37 |
| Total at the shared default | $1,531.84 |
| Difference | $136.47 |

The test demonstrates a discrepancy between application paths.
It does not establish which percentage the business owner intends to charge.
No quote was sent. No Google document was created.
The probe blocked socket connections and used local pricing data.

## Boundaries and controls

The new passing controls cover positive departures, explicit returns, and unknown source roles.
They also cover rejected zero, negative, null, and invalid-string day numbers.
Changed required cities, sites, arrival cities, departure cities, dates, and traveller counts expire saved plans.
Empty, repeated, and unknown selected codes also expire saved plans.

B-T02 uses the real preview, builder, calculator, and document assembler.
It checks that readiness passes before checking the false accommodation promise.
No live catalogue row currently combines an overnight with a missing hotel tag.
B-T02 therefore concerns a supported boundary state, not a demonstrated current customer document.
B-T03 through B-T05 likewise use synthetic inputs.
The tests do not claim these malformed values occur in the current corpus.

The authenticated live checks still report one ready draft and five blocked drafts.
The five existing blockers remain separate from the new defects.
The ready indicator does not detect B-T01.

All 407 source files retained their recorded hashes.
Prior sequences, comments, request contents, runs, document links, settings, and scheduled states remain intact.
The phone retained its existing untracked `phone_db_register.py` file.
Affected network-model steps remained blocked.

## Reproduction

```powershell
venv/Scripts/python.exe -m pytest tests/test_itinerary_option_b_boundaries.py --runxfail -q
venv/Scripts/python.exe -m pytest tests/test_itinerary_option_b_boundaries.py -q -rx
node --test tests/itinerary_desk.test.mjs
```

The private execution logs are outside Git under `../scratch/option-b-test-sept19-*`.
The test harness supports repeated `--target-id` arguments for stable historical comparisons.
Production changes were intentionally absent from that Test-mode task.


## Historical replay

The replay reconstructed all 335 offers and compared six selected targets against strictly older offers.
The targets cover 2024, 2025, and 2026, with one-day and 16-to-17-day trips.
The six IDs are `06fd4ca4fa74`, `b5df34cbfe2f`, `0813d635e6eb`, `6d2a3d0bad92`, `7ffef15c9aec`, and `913ec1f61139`.
All reconstruction and comparison results match the preceding Option B audit.
The run took 37.94 seconds and left all source offers unchanged.

These requests infer constraints from delivered offers.
They do not establish original customer intent or resolve the pricing and document defects above.
