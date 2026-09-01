# Workstream Protocol

Governs how every `docs/workstreams/ws-NN/` folder is run. Applies to all workstreams, not just ws-01.

## Tier markers

Every requirement in a `spec.md` carries exactly one tier marker. The marker is binding on how much latitude an agent has, not on the requirement's importance.

- **[LOCKED]** — Immutable for the life of the workstream. No stage may propose changing it, working around it, or silently narrowing it. If anything discovered during research or implementation contradicts a `[LOCKED]` item, that is a stop-and-flag event, reported immediately, not absorbed into a workaround.
- **[DEFAULT]** — The current best answer, adopted provisionally. A later stage may replace it with something better, but only with evidence, and the replacement plus the reason must be logged in that stage's output file. Silently keeping or silently changing a default without saying so is a protocol violation either way.
- **[OPEN]** — A question a named stage is obliged to resolve. "Resolve" means: state a decision, back it with evidence, name the runner-up option and the condition that would flip the choice, and give a confidence level. An open question is not resolved by restating the question or by picking an answer with no evidence attached.

## Evidence rules

Every factual claim used to resolve an `[OPEN]` question, or to justify changing a `[DEFAULT]`, is labeled with exactly one of:

- **MEASURED** — Observed directly, this pass, by actually running the thing (a real command against a real or faithfully-copied system, timed and recorded). The raw command and its real output go in the stage's Measurements appendix. A plausible number is never substituted for a measured one — if the measurement could not be taken, say why in one line and mark the dependent decision's confidence as Low.
- **SOURCED** — Taken from external written evidence (official docs, changelogs, issue trackers, release notes). Cite what was read.
- **INFERRED** — Derived by reasoning from other MEASURED or SOURCED facts, not observed directly. State the chain of reasoning.

## Stage naming

Stages are numbered per workstream (S1, S2, ...) and each has a single-file deliverable and a fixed set of things it is and is not allowed to touch, stated in the prompt that launches it. Referenced in ws-01: **S1** is the research stage (resolves the `[OPEN]` list, writes `research.md`); **S4** is the drill/validation stage (proves the workstream's definition of done against real artifacts, not simulated ones).

## Non-negotiables across every stage

- A read-only stage runs read-only commands and writes exactly one named file. It does not install anything permanently, and it never operates on a live/production data store directly — copy first, work on the copy.
- Contradiction with a `[LOCKED]` item is flagged before continuing, not worked around.
- A stage's "Contradictions and surprises" (or equivalent) section is never left empty for politeness. If nothing surprising happened, that itself is a two-line statement of what was checked and confirmed as expected.
