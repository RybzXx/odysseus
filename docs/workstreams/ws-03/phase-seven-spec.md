# ws-03 phase seven — the two request kinds, provenance, and the region model

Written 2026-09-08. Read `phase-six-spec.md` for the desk this phase changes,
and `handover.md` for the state it starts from.

## 0. Numbering

This phase continues the earlier numbers. Phase six defined WP24 to WP31.
WP32 to WP38 are new. Decisions continue from D57.

## 1. Why this phase exists

The desk mixes two request kinds and the reviewer cannot tell them apart.

A Curated request comes from a preset form. Every field the office needs is on
it, and an offer can follow at once. A Queue request comes from a chat, and a
data-entry team types what it can read out of a photograph. The two carry
different evidence and need different work.

`normalizer.py:410` is the only place in the pipeline that branches on the
kind. The normalizer sets `NormalizedRequest.source` there, and no layer,
route, check or run reads it again. Five call sites pass `origin` where the kind belongs, and
`origin` holds `"sheet"` or `"typed"`, never `"curated"` or `"queue"`.

Three separate mechanisms then hide evidence from the reviewer. The desk shows
a stored sequence beside a live check. A request with no stated region scores
1.00 coverage against a region the normalizer invented. The sequence checker
reports "clean" for a trip that drives Mosul to Sulaymaniyah, because the day
that makes that move carries no overnight city and never enters the chain.

The owner commented on four requests on 2026-09-07. Half of those comments
describe sequences the current code no longer produces, because the desk stores
a proposal once and never recomputes it.

## 2. Decisions

| # | Decision |
|---|---|
| D58 | A stored sequence is a record, not a cache. The desk recomputes only to compare, and says when the two differ |
| D59 | One helper reads the request kind from the `request_id` prefix. The draft does not store it |
| D60 | The catalogue holds the four region names the intake form offers, and no others |
| D61 | A template's region is the region of its overnight city. Exceptions are a written list, never an inferred rule |
| D62 | A template with no overnight city takes the region of its end city |
| D63 | Two templates that work the same sites are an alternative pair. Holding both is a fault, and the binder never picks both |
| D64 | The `SAFA` with `SAMO` judged rule retires. The corpus base rate replaces it |
| D65 | A proposal that used a defaulted field says so. A default and a stated value never read alike |
| D66 | A check that cannot run says which check and why. Silence never reads as a clean sequence |

## 3. Measurements this phase rests on

Measured on 2026-09-08 over the repository's own data.

| What | Number |
|---|---|
| Worklist drafts on disk | 9 — 5 curated, 4 queue |
| Drafts whose stored sequence is empty | 6 of 9. None is empty on recomputation |
| Drafts carrying a stale parse warning | 7 of 9 |
| Sold offers in the corpus | 335 |
| Sold offers that visit Samarra | 258 |
| Sold offers that visit Samarra on two days | 1, an 11-day trip through Fallujah, Hatra, Mosul and Erbil |
| Sold routes that reach Nineveh without Kurdistan | 0 of 164 |
| Active day templates | 60 |
| Templates whose start city the owner settled | 21 |
| Templates whose start city a title gives | 7 |
| Templates whose start city the code derived | 32. The owner read all 32 on 2026-09-08 |
| Curated records that price at the wrong hotel tier | 5 of 5 |
| Run records | 8, all Queue. No run ever executed on a Curated request |

## 4. WP32 — provenance on the desk

**WP32.1 A stale sequence says so.** MUST.
`_draft_to_dict` recomputes the rules proposal and compares it to the stored
one. Done: a card whose stored codes differ carries a note naming how many
differ. A matching card carries nothing.

**WP32.2 Stored sequences stay stored.** MUST.
Recomputation compares and never writes. Done: a draft file's `sequences`
array does not change when the desk renders a card.

**WP32.3 A re-propose action.** SHOULD.
Done: it appends a sequence with a new `proposed_at`, and the old sequence
keeps the comments made against it.

**WP32.4 The note names a defaulted field.** MUST.
`propose_by_rules` reads `defaulted_fields`. Done: a request with no stated
region produces a note that says the desk assumed the region, not a coverage
of 1.00.

**WP32.5 Warnings render live.** MUST.
Done: no draft shows a warning about a region name the current map resolves.

**WP32.6 One helper reads the request kind. Nothing guesses it.** MUST.
One helper answers the kind from the `request_id` prefix. Done:
`normalize_from_dict` never receives `"sheet"` or `"typed"`. A draft with no
`request_id` answers `"unknown"` and takes the shape-detection path on purpose.

**WP32.7 The kind is not stored on the draft.** WONT.
Two fields that can disagree is a new way to be wrong.

## 5. WP33 — checks

**WP33.1 Role order.** MUST.
A departure day before the last day, or an arrival day after the first, is a
fault. Done: `cr-mthikj54` reports a fault at day 9, where `SUEBDEP` sits in a
12-day trip. A sequence that ends with `SUEBDEP` reports none.

**WP33.2 The day's start.** MUST.
A day that starts in a city the last night did not end in is a fault.
Done: the check finds the fault `FAULTS_NOT_YET_FOUND` names as `day_start`,
and the entry leaves that list.

**WP33.3 Skipped sites and a day trip on a moving day.** WONT this phase.

## 6. WP34 — template and site data

**WP34.1 Corrected shapes.** MUST.
The owner read the 32 derived shapes on 2026-09-08 and corrected six.

| Code | Role | Start | End | What changed |
|---|---|---|---|---|
| `NJ` | day_trip | Najaf | Najaf | role |
| `KA` | day_trip | Karbala | Karbala | role |
| `EBSORA` | day_trip | Erbil | Erbil | the derived start was backwards |
| `BGNJURUKNA` | transit | none | Nasiriyah | role, start, and the record's overnight city |
| `NA2BA` | transit | Nasiriyah | Basra | role and start |
| `DaMOZKDU` | transit | none | Duhok | the work sells this day two ways. It is a Duhok day trip, and it is a transit out of Mosul |
| `SHSOKO` | transit | Akre | Korek Mountain | the day starts at Shush village, which the map does not hold. Akre is the nearest place it does hold |

**WP34.2 Record defects.** MUST.
`BGNJURUKNA.overnight_city` reads Najaf and the day sleeps in Nasiriyah.
`NA2BA.city` and `BGNJURUKNA.city` name fewer cities than the day passes
through. Done: the recorded overnight matches the night the day sells.

**WP34.3 Site codes that do not resolve.** MUST.
Three active templates name a site the index does not hold: `EBSORA` names
`EB_SORA`, `BAMaMNV` names `NVHMARK`, `EBKOSU` names `EBL_KOYA`.
`EBSORA` names no other site, so it is invisible to the repeat check.
Done: every `included_sites` code resolves, and `EBSORA` reports its Soran
overlap with `SHSOKO`.

**WP34.4 Places without a coordinate.** MUST.
Done: every start and end city across the templates resolves in `move_map`.

## 7. WP35 — the region model

**WP35.1 Four regions, the form's own words.** MUST.
`Iraqi Kurdistan`, `Western Iraq & Nineveh Plains`,
`Central Iraq & Middle Euphrates`, `Southern Iraq`.
Done: every region label the live records carry maps to one of the four, and
`unmapped_regions` answers empty for all of them.

**WP35.2 The region is the overnight city's region.** MUST.
Done: every active template's region equals the region of its overnight city,
or its code sits in the exception list below.

**WP35.3 The exception list.** MUST. Seven codes, each with its reason.

| Code | Region | Sleeps in | Reason |
|---|---|---|---|
| `SAFA` | Western Iraq & Nineveh Plains | Baghdad | Fallujah and Aqar Quf |
| `BGFA` | Western Iraq & Nineveh Plains | Baghdad | the same day without Samarra |
| `MO1EB` | Western Iraq & Nineveh Plains | Erbil | the region's only exit |
| `NA2BG` | Southern Iraq | Baghdad | the Ahwar marshes |
| `NAURUKNJ` | Southern Iraq | Najaf | Ur and Uruk |
| `URNJ` | Southern Iraq | Najaf | Ur |
| `UrukNJ` | Southern Iraq | Najaf | Uruk |

**WP35.4 A day with no overnight.** MUST.
It takes the region of its end city. `BANA` answers Southern, `MOBKHEB` and
`SUEBDEP` answer Kurdistan. `BB` has no end city, so the owner set it to Central.

**WP35.5 The binder's region strings.** MUST.
`is_multi_region_non_contiguous` and `force_erbil_departure` both test the
literal `"Northern Iraq"`, which stops existing under WP35.1. Done: a
west-only request still ends at Erbil, and a Central-only request does not.

## 8. WP36 — two new templates

**WP36.1 `BGFA`.** MUST.
Baghdad day trip: Fallujah by way of Abu Ghraib, the Fallujah kebab for lunch,
and Dur-Kurigalzu on the way back. It is `SAFA` without Samarra.
Overnight Baghdad. Sites `['BG_AGIRQUF']`. Region Western Iraq & Nineveh Plains.
Four sold offers carry this exact day.
Done: a west request binds `BGFA` and no Samarra site.

**WP36.2 `MO1EB`.** MUST.
Old Mosul reconstruction, Al-Nuri, Al Hadbaa and Al Tahira, the Kubba of Mosul
for lunch, then the drive to Erbil and the citadel.
Overnight Erbil. Sites `['MO_OLD_CITY','MO_NORI','ERB_CITD']`. Region Western
Iraq & Nineveh Plains by WP35.3.
Two sold offers carry this day.
Done: `BGFA, SAMO, MO1EB` binds for a three-day west request and carries
Samarra one time.

**WP36.3 Alternative pairs.** MUST.
`SAFA` with `BGFA`, `MO1` with `MO1EB`, and `NA2BA` with `NA2BG`.
`NA2BA` and `NA2BG` are one Chibayish day with two endings, and they share
both their site and their opening sentence.
Done: a sequence holding a pair reports one alternative-pair fault, and the
binder cannot produce such a sequence.

**WP36.4 `BGFA` with `MUCTAGKDHBG`.** SHOULD.
Both carry `BG_AGIRQUF`, and they are not alternatives. The one-site flag
stands, and this phase writes no rule for it.

## 9. WP37 — the Samarra rule

**WP37.1 Retire `judged--safa-with-samo`.** MUST.
Its condition asked for the west and the north, and `"nineveh plain"` sits in
both word lists, so one label satisfied both halves. Its threshold allowed the
repeat at eight days, and the one sold precedent is eleven.
The corpus base rate replaces it: 1 of 258.
Done: `safa_verdict` softens nothing, and a Samarra repeat always lowers the
candidate's score.

## 10. WP38 — the Curated record

**WP38.1 The hotel tier.** MUST.
`accommodation` arrives as a list and spells the tier `3_star`.
Done: `cr-mtjf9aek` prices at five star and `cr-mthikj54` at four.

**WP38.2 Three field names.** MUST.
The reader asks for `dietaryNeeds`, `heatWalkingComfort` and
`hotelChangePreference`. The form sends `dietaryRestrictions`,
`walkingDifficulty` and `hotelChangeTolerance`.
Done: those three values reach `special_notes`.

**WP38.3 The customer's interests.** MUST.
`journeyTypes` is never read, and it is the richest field the Curated form
carries. Done: it reaches `special_notes` the way the Queue's `trip_focus`
does.

**WP38.4 A rules-built brief for Curated.** MAY. Deferred, because layers two
and three do not run and nothing would read it.

## 11. Assumptions

| # | Assumption | What would disprove it |
|---|---|---|
| A1 | A day with no overnight takes the region of its end city | `MOBKHEB` belongs to the west because it works Bakhdida |
| A2 | `force_erbil_departure` fires for both northern regions | A west trip that should end in Baghdad |
| A3 | `BGNJURUKNA` has no settled start | It always starts in Baghdad |
| A4 | `MO1EB` leaves Kurdistan-only requests | A Kurdistan trip that opens with an Old Mosul day |

## 12. Out of scope

The model layers stay off. `data/settings.json` holds no `itinerary_` key, and
the owner decides that.

`propose_by_model` resolves `resolve_endpoint("default")`, which is the chain
`layer_access` exists to forbid. Real, independent, and not this phase.

The 55 drafts on disk are not re-scored. `sites_skipped` and
`day_trip_on_a_moving_day` are not built. Curated gets no rules-built brief.
