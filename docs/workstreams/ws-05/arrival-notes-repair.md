# Arrival instructions in queue entry notes

The queue normalizer omitted an explicit Basra arrival because it only read
structured endpoint fields. The candidate ranker then preferred a Baghdad start
when the Basra candidates had more unrelated faults.

Queue entry notes now supply an arrival requirement through a small deterministic
grammar: an affirmative arrive/arrival/landing clause, a known city or alias,
and an optional airport, date, or time suffix. The normalizer preserves the
original notes and records the requirement source. Other city mentions and
model summaries do not supply endpoints.

Uncertain, negated, conflicting, or unsupported arrival wording requires review.
A conflict with a structured arrival field preserves that field and blocks a
fully checked result. This parser does not interpret all requested sites or
departure instructions in prose.

Candidate ranking keeps routes with matching endpoints ahead of routes with
endpoint faults, including when all candidates remain incomplete. Existing
generation checks still apply. The normalized request fingerprint invalidates
saved plans that omitted the arrival requirement.

Validation: 267 focused local Python tests passed. Staged phone validation passed
91 tests and resolved the affected saved request to Basra. Its five-day candidate
starts in Basra but remains blocked by the repeated-site cap and the existing
Central/Southern marshes-and-Baghdad-return rule. No catalogue facts were changed.

The verified phone backup is `odysseus-itinerary-backup-20260920T151136Z`.
It contains 69 files and a SQLite snapshot with integrity `ok`.
