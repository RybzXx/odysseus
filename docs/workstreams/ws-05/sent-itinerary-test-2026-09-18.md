# Sent itinerary test, 18 September 2026

The itinerary system still fails important historical cases.
This test found four reproducible defects and saved seven regression cases.
No production code, catalogue facts, live drafts, or rules changed during this test.

The test used the phone release `74d6d454ac9da5c8fa256e905b18acef7a7f178a`.
It read 335 stored sent offers, dated 25 August 2024 through 3 September 2026.
The offers contain trips from 1 to 17 days, with 301 distinct itinerary texts.
The current catalogue contains 62 active templates. The production matcher contains 164 routes.
The local catalogue matched all 72 phone JSON data files after JSON decoding.
Byte differences came from file formatting, not JSON values.

The audit reconstructed every offer from its own parsed days.
It then tested 174 requests against strictly older offers: all 81 offers from 2026 and 93 older representatives.
Each older representative covers a year, trip length, and inferred region combination.
The reference pool excluded the target message and identical itinerary text.
References can contain similar routes or related revisions. This is not a customer-disjoint evaluation.

Requests in this audit are inferred from delivered day counts, tour types, and activity regions.
They are not recovered customer enquiries. Five records have no recognized activity region.
The current catalogue and connection evidence remain available in both comparisons.
This is a retrospective comparison of route sources, not a historical training evaluation.

Sent dates order the references. They do not become travel dates.
The audit tests each result with seven synthetic departure weekdays, starting 5 October 2026.
A result that passes on one synthetic weekday is not ready for a real customer booking.
No actual start date, quote, document, or message was approved by this audit.

| Reconstruction result | Count |
| --- | ---: |
| All source days bound | 75 / 335 |
| All days and all overnight stops preserved | 74 / 335 |
| Binding stopped before the final day | 260 / 335 |
| No day could bind | 10 / 335 |
| At least one synthetic start weekday passed every sequence check | 16 / 335 |
| All overnight stops matched, but at least one day was missing | 108 / 335 |

Matching nights alone gives a misleading result in 108 cases.
A missing departure can preserve every hotel night while shortening the trip.
The audit therefore measures trip length and overnight agreement separately.
It does not use the misleadingly named `SequenceGrade.day_count_agrees` property as a trip-length test.

| Sent year | Offers | All days bound | At least one synthetic weekday passed |
| --- | ---: | ---: | ---: |
| 2024 | 93 | 23 | 1 |
| 2025 | 161 | 30 | 9 |
| 2026 | 81 | 22 | 6 |

Older references improve some structural results, but do not reliably reproduce the delivered itinerary.
The following table covers the same 174 inferred requests in both columns.
One target has no eligible older reference. Its empty result remains in the denominator.

| Top candidate result | Production route pool | Older sent-offer pool |
| --- | ---: | ---: |
| Exact requested day count | 141 / 174 | 147 / 174 |
| Exact overnight sequence and night count | 14 / 174 | 4 / 174 |
| At least one synthetic weekday passed every sequence check | 48 / 174 | 60 / 174 |

For the 81 offers from 2026, exact trip lengths increased from 63 to 68.
Results that passed on a synthetic weekday increased from 17 to 34.
Exact overnight agreement decreased from 10 to 3.
These are agreement measures, not customer-request accuracy scores.
The inferred requests omit particular cities, activities, and airport requirements.

Two comparisons demonstrate the difference between a complete length and a faithful itinerary.
IDs below are stable hashes of the local message ID and attachment name.
They contain no customer names or addresses.

| Target sent date and ID | Older reference | Result |
| --- | --- | --- |
| 28 July 2026, `51a6503d2412`, 11 days | 22 June 2026, `cdb4f8cc111a` | Production returns 10 days. The older reference returns 11, but matches only 4 of 11 overnight positions. |
| 29 August 2026, `f4b55f87a673`, 11 days | 22 June 2026, `cdb4f8cc111a` | Production returns 10 days. The older reference returns 11, but matches only 3 of 10 overnight positions and adds a night. |

Four defects need repair before these historical cases can be trusted.

| ID | Defect and evidence | Required behavior |
| --- | --- | --- |
| H01 | City matching treats `Nasiriyah,` as an unknown place. Five stored offers contain this value. Four stop on day 1. `f7dc1417a6da`, sent 12 December 2024, is a two-day example. | Normalize harmless trailing punctuation consistently. Preserve unknown place names as unresolved. |
| H02 | An empty overnight field always becomes a departure role. All four one-day offers bind to `MOBKHEB` or `SUEBDEP`, including Baghdad and Samarra day tours. The region check rejects these direct reconstructions, but the binding itself is wrong. | Distinguish a day excursion from an airport departure. Stop with an explicit unresolved result when the source cannot establish the role. Never substitute an unrelated departure. |
| H03 | Activity-region matching ignores recognized place aliases such as `Chibayesh` and `Sulimaniyah`. The marshland day in `7ffef15c9aec`, sent 21 February 2026, loses Southern Iraq from its inferred regions. | Apply the place alias vocabulary to activity text while retaining word boundaries and boilerplate removal. |
| H04 | The owner-defined shape of `BANA` ends in Nasiriyah, but its catalogue row has no overnight city or hotel pricing tag. The binder accepts a Nasiriyah night that the document builder omits. Seven-day offer `adacd11fde40`, sent 4 February 2025, loses one of six nights. The checker then compares Basra directly with Baghdad and reports a long leg. | A complete binding must preserve the source overnight contract. Resolve the shape and catalogue disagreement, or reject the binding with a specific reason. Do not silently omit accommodation. |

H02 and H04 affect the meaning of a day, not only its ranking.
H01 and H03 affect place normalization in different paths.
The regression tests use synthetic prose. They do not copy customer correspondence.

The binding stops also expose catalogue and constraint limits.
These are the most frequent first stops across the 335 reconstructions.
Counts identify where binding stopped, not proof that a new template is always required.
An existing template can be rejected because it repeats sites or conflicts with a day role.

| First unavailable binding | Offers |
| --- | ---: |
| Erbil departure | 50 |
| Karbala to Baghdad | 29 |
| Baghdad departure | 22 |
| Karbala to Najaf | 18 |
| Basra departure | 15 |
| Basra to Baghdad | 14 |
| Nasiriyah to Karbala | 12 |
| Nasiriyah departure | 12 |

Historical records also need care as test evidence.
Nineteen offers have non-contiguous day numbers.
Thirty-eight have an empty overnight field before the final day.
These can reflect parsing problems, partial offers, or the source document itself.
They require inspection before they become planning rules.
Historical repetition alone does not establish route validity.

The test outputs are reproducible with `scripts/audit_sent_itineraries.py`.
Use a local snapshot, not the live application data directory.
The script blocks network connections and verifies that stored offer records remain unchanged.
The full result file is outside the repository at `../scratch/itinerary-sent-audit-results.json`.
The private snapshot is at `../scratch/itinerary-sent-audit-data`.

```powershell
venv/Scripts/python.exe scripts/audit_sent_itineraries.py --data-dir ../scratch/itinerary-sent-audit-data --output ../scratch/itinerary-sent-audit-results.json
venv/Scripts/python.exe -m pytest tests/test_itinerary_historical_regressions.py --runxfail -q
venv/Scripts/python.exe -m pytest tests/test_itinerary_historical_regressions.py tests/test_itinerary_repair.py tests/test_sequence_grade.py -q
```

The full corpus audit completed in 150.04 seconds on the local machine.
The focused local suite reports 39 passed and 7 expected failures.
The seven strict expected failures document H01 through H04. They are not passing behavior.
All seven expected failures reproduced on the phone in an isolated checkout.
The phone also passed the same 39 existing focused tests during the preceding run.
With expected-failure handling disabled, all seven new cases fail on the stated assertions locally.
After testing, all 335 phone offer records and all 72 catalogue JSON files retained their original SHA-256 hashes.
The phone remained at `74d6d45`. Its tracked checkout stayed clean.
The existing untracked `phone_db_register.py` remained present.

The next code task should repair H02 and H04 first, then H01 and H03.
After those repairs, repeat this audit before changing rules or adding catalogue rows.
Use actual request constraints to assess customer intent. Keep historical fidelity as a separate measurement.
