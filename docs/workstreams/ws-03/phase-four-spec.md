# ws-03 phase four — routing checks and the template tie-break

Written 2026-09-07. Read `handover.md` first for the state it starts from, and
`phase-three-spec.md` for the decisions it continues.

## 0. Numbering

This phase continues the handover's WP numbers. Phase three defined WP8 to WP10.
WP11 to WP15 are new. Decisions continue from D27.

## 1. Decisions

| # | Decision |
|---|---|
| D28 | A template carries a start city and an end city. The end city equals `overnight_city` where the catalogue sets one |
| D29 | A move counts in either direction. A pair is refused only where neither direction appears |
| D30 | Two or more shared sites on one day pair is a fault. One shared site is a flag |
| D31 | The flag cap is per trip. Two flags break it |
| D32 | The same template on two days is a fault, whatever the site count |
| D33 | A machine note has its own list on the draft. It never enters the comment queue |
| D34 | A machine note is written when the check runs, not when a document is built |
| D35 | The binder filters by role, then scores by site name, then by word overlap |
| D36 | A judged rule may lower a fault to a flag for a named template pair. A counted zero still wins on a move |
| D37 | The `SAFA` rule reads `request_row['regions']`, the raw customer text |

D36 and D6 do not conflict. D6 governs moves between cities, where the counted
zero wins. D36 governs shared sites between templates. The two families never
meet.

## 2. Invariants

**2.1 [LOCKED]** Invariants 1.1 to 1.9 in `spec.md` and 2.1 to 2.4 in
`phase-three-spec.md` bind unchanged.

**2.2 [LOCKED]** `move_count` stays directional. A rule that reads "61 of 256"
keeps meaning one direction.
*Falsified by:* one caller that receives a summed count from `move_count`.

**2.3 [LOCKED]** A check that could not run records itself. It never reports a
clean sequence.
*Falsified by:* one `is_clean` that is true while `untested` is not empty.

**2.4 [LOCKED]** The check reports. It never repairs and never generates.
*Falsified by:* one `day_codes` list that `sequence_check` changes.

**2.5 [LOCKED]** A machine note never reaches `comments`.
*Falsified by:* one note that `GET /api/itinerary/comments` returns.

## 3. Measured facts this spec stands on

Each figure was measured on 2026-09-07.

| Fact | Value |
|---|---|
| Active day templates | 60, all complete |
| Codes the binder reached before this phase | 48 of 60 |
| Codes the binder reaches after it | 52 of 60 |
| The ceiling on that figure | 58. No sold route sleeps in Korek Mountain |
| Median word overlap, Sulaymaniyah | 0.238 |
| Median word overlap, Erbil | 0.250 |
| Median word overlap, Mosul | 0.818 |
| Templates the catalogue could not give a start | 21. The owner settled each one |
| Sites the route text names, by exact match | 24 of 55 |
| Sites the route text names, by word match | 44 of 55 |
| Day pairs sharing a site, over ten proposals | 24. 20 adjacent, 4 apart |
| Site repeats over ten proposals, before | 14 |
| Site repeats over ten proposals, after | 9 |
| Same-template repeats, before and after | 4, then 0 |
| Nights placed in the offer's city | 58 of 116, unchanged |
| The driving ceiling | 410 km, the corpus p90 of 408 |

## 4. WP11 — the template's start, end and role

**11.1 [MUST]** Each of the 60 templates carries a start city, an end city and a
role.
*Done:* `day_shape.all_shapes` answers for all 60. 21 from the owner, 7 from a
title, 32 from the catalogue.
*Falsified by:* one template that a check reads and that answers none.

**11.2 [MUST]** The end city equals `overnight_city` where the catalogue sets
one.
*Falsified by:* one template whose end disagrees with a set `overnight_city`.

**11.3 [MUST]** A day tour may carry no start city.
*Done:* `BB` carries a role and no start. Babylon sits 44 km from Karbala and
99 km from Baghdad, and a trip reaches it from either.
*Falsified by:* `BB` that binds after one of those and not the other.

**11.4 [MUST]** The values live in the repository, not in the sheet.
*Done:* `day_shape.OWNER_SETTLED_SHAPES` holds the owner's 21, with the date he
gave them.
*Falsified by:* a value written to the catalogue, which invariant 1.3 forbids
this phase.

**11.5 [SHOULD]** The run reports the templates that carry no start.
*Done:* `shapes_without_a_start` names `BB`, `ArrSU` and `NA1`.

**11.6 [WONT]** A repair to the catalogue rows. `BANA` and `MOBKHEB` carry a
blank `overnight_city` and the sheet is the owner's.

## 5. WP12 — the site rules

**12.1 [MUST]** Two or more sites shared by one day pair is a fault.
*Done:* `BBKA` with `KABBBG` at 4 sites raises one fault about two days.
*Falsified by:* a day pair sharing 2 sites that reports clean.

**12.2 [MUST]** One site shared by one day pair is a flag, not a fault.
*Done:* `EBNEWROZ` with `BAEB`, sharing `ERB_CITD`, raises a flag.
*Falsified by:* a one-site pair that reports a fault.

**12.3 [MUST]** The rule reads any two days of the trip, not adjacent days
alone.
*Done:* `SAMO` on day 2 and `SAFA` on day 9 raises a fault.
*Falsified by:* a repeat that passes because the days do not touch.

**12.4 [MUST]** Two flags on one trip break the cap and raise a fault.
*Done:* `FLAG_CAP = 2`, and a trip with two one-site pairs reports a fault
naming both.
*Falsified by:* a third flag that raises nothing.
*Open:* the owner said "cap on 2, flag on 1". Two as the fault is Claude's
reading of that, and it is one constant.

**12.5 [MUST]** A flag lowers the candidate's score.
*Blocked:* no candidate scorer exists. It arrives with the three candidates.

**12.6 [MUST]** The same template on two days is a fault, whatever the site
count.
*Done:* `BG3` on day 6 and day 8 raises a fault.
*Falsified by:* a repeated template that raises only a flag.

**12.7 [MUST]** Site codes are compared after `canonical_site_code`.
*Done:* `NVHMARK` and `NVH_MARK` read as one site.

## 6. WP13 — the tie-break in the binder

**13.1 [MUST]** The binder keeps the templates whose role matches the day's
role.
*Done:* a Sulaymaniyah transit day keeps `ArrSU` and `EBKOSU`, and drops the
city day and the day trip.
*Falsified by:* an arrival template bound to a day that is not an arrival.

**13.2 [MUST]** The binder scores the survivors on the sites the day text names,
counting only sites the trip has not used.
*Done:* site repeats fell from 14 to 9 and same-template repeats from 4 to 0.
*Falsified by:* a score that counts a site an earlier day already took.

**13.3 [MUST]** Site names match on the distinctive word.
*Done:* "Abbas shrine" in the route text matches `KA_ABB`, named "Abbass
Shrine". 44 of 55 sites match, against 24 by exact string.

**13.4 [MUST]** The word overlap decides any tie that survives 13.1 to 13.3.
*Falsified by:* a tie resolved by file order.

**13.5 [MUST]** The run reports how many codes the binder reaches.
*Done:* 52 of 60, against 48 before. The ceiling is 58.

**13.6 [SHOULD]** The run reports the sites whose names cannot be matched.
*Done:* `unmatchable_sites` names 6.

**13.7 [WONT]** A repair to a site name. It is catalogue data.

## 7. WP14 — the machine note list

**14.1 [MUST]** A machine note lives in its own list on the draft.
*Done:* `ItineraryDraft.notes`, written by `POST /api/itinerary/drafts/{id}/note`.
*Falsified by:* one note that `GET /api/itinerary/comments` returns.

**14.2 [MUST]** The note is written when the check runs.
*Done:* flags compute on every read of a draft. `notes` holds what a session
adds and does not recompute.

**14.3 [MUST]** A flag names the site and both days.
*Done:* "day 1 (EBNEWROZ) and day 2 (BAEB) share one site: Erbil Citadel".

**14.4 [MUST]** The desk shows the list under the sequence it belongs to.
*Done:* flags render under each sequence, marked apart from faults. Notes render
in their own card.

**14.5 [MAY]** Claude adds a note in session, under D17.
*Done:* `source` is `model` or `check`, and a repeated note is not added again.

**14.6 [WONT]** A note in the generated document. It would reach a customer.

## 8. WP15 — the `SAFA` judged rule

**15.1 [MUST]** The rule lives in the judged rule book.
*Done:* `judged--safa-with-samo` is in `data/ai_rules/judged/`, and
`named_pair_rules` reads it back. The checker holds no template code.
*Open:* the placement is Claude's recommendation. The owner did not agree it.

**15.2 [MUST]** The rule lowers the fault to a flag. It never refuses.
*Done:* every combination of region and day count gives a flag and no fault.
*Falsified by:* a refusal.

**15.3 [MUST]** The penalty lifts when the raw region text names the west and
the north over 7 days.
*Done:* a 12-day request whose raw regions hold "Western Iraq & Nineveh Plains"
and "Iraqi Kurdistan" gives a flag that costs the candidate nothing.
*Falsified by:* a condition read from `requested_regions`, where the west and
the north are one value.

**15.4 [MUST]** The rule names one pair and generalises to no other.
*Done:* `BBKA` with `KABBBG` still raises a fault under 12.1.

**15.5 [MUST]** The comment on `dr-1d40984884cc` reads `declined`.
*Done:* three comments wait for a rule, not four. The comment text is unchanged.

## 9. This phase does not build

**WONT** A repair to `find_best_route`. Five to eleven routes tie at the top
score, and that holds the larger part of the 50 percent.

**WONT** A model call. D17 and D25 stand.

**WONT** A judged-rule UI. Three routes have no control on the page:
`GET /comments`, `POST /comments/{draft}/{comment}` and `POST /rules/judged`.

**WONT** A repair to the two blank `overnight_city` cells.

## 10. Measurements this phase produced

| # | Measurement | Value |
|---|---|---|
| 10.1 | Codes the binder reaches, of 60 | 52, against 48 before. The ceiling is 58 |
| 10.2 | Faults over the ten proposals | site repeat 9, day repeat 0, flag cap 2 |
| 10.3 | Flags over the ten proposals | 8 |
| 10.4 | Nights placed in the offer's city | 58 of 116, unchanged |
| 10.5 | Sites the route text names | 44 of 55 |

## 11. Risks that stand

The `SAFA` condition rests on raw customer text. A customer who writes "north
Iraq" and means the west gets the penalty. Nothing measures how often that
happens.

The role of 21 templates rests on the owner's answers, not on a measurement. A
wrong role hides a template that fits, and 13.1 gives no report when it does.

The flag cap has no evidence behind its value. The worst of the ten proposals
carries two flags and no trip carries three.

`find_best_route` still returns the first of several tied routes. It decides the
nights, and the tie-break decides only the code for a night already chosen.
