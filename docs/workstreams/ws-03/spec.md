# ws-03 — AI Offer Generator over the Bil Weekend offer corpus

Governed by `docs/workstreams/00-PROTOCOL.md`. Tier markers `[LOCKED]` / `[DEFAULT]` / `[OPEN]`
are binding on latitude. Evidence labels `MEASURED` / `SOURCED` / `INFERRED` are binding on claims.

Opened 2026-09-03. Supersedes the unpersisted spec described in
`OperationsAutomationSrv/DESIGN_RECORD_2026-09-02.md`, whose nine sections were drafted and never
written to disk.

## Problem

Bil Weekend answers travel enquiries by hand-writing offers. Seven months of those offers exist only
as attachments in the `book@bilweekend.com` Sent folder. An itinerary program maker exists
(`New_Operrations/NewOPsWeb/WebOperationsBilW`) but its day catalogue expresses a minority of what
the offers actually contain, so any system trained on the offers proposes itineraries the builder
cannot render.

Two capabilities, one workstream because they share the same corpus:

- **G — Gap closure.** The day catalogue covers what real offers actually say.
- **A — Assisted drafting.** An enquiry produces a parameter set and prose that a human approves.

## Definition of done

Not "the pipeline runs." Three demonstrations, in order:

1. A randomly chosen sent offer is recovered from mail, its attachment opens, and its day split
   contains no boilerplate.
2. Catalogue coverage is re-measured after append, and the delta is attributable to named,
   human-approved templates.
3. A held-out offer — never in the retrieval index — is regenerated from its enquiry and scored
   against what was actually sent.

---

## 1. Invariants

**1.1 [LOCKED]** The sent attachment is the sole authority. Any disagreement between a sent offer and
`routes.json`, `quote_log.jsonl`, or a template resolves in favour of the attachment.
*Done:* every stored offer retains its original attachment bytes, and every derived record names the
attachment it came from. *Falsified by:* any corpus record with no recoverable source file.
`SOURCED` — `curated/settings.py:87` "the original offers folder no longer exists anywhere".
`SOURCED` — `docs/docaut-staging.md` records the quote log disagreeing with the delivered document on
days (9 vs 10), tier (3star vs 4-star), price ($4,494.72 vs $4,500) and title.

**1.2 [LOCKED]** *(revised 2026-09-03, decision 2.4=D)* The engine MAY be modified. Every engine
change is a named work package with its own tests, and MUST NOT alter render output for any
template-only itinerary.
*Done:* a regression run over both confirmed tours produces byte-identical documents before and after
every engine change. *Falsified by:* one differing byte with no approved reason.
**Blast radius:** the engine is deployed on Render serving the live web GUI the operations team uses,
so engine changes reach production operations, not only the factory. `SOURCED` — `docs/sheet-sync.md`.

**1.3 [LOCKED]** No row reaches the `templates` sheet active. Every appended row lands
`active=FALSE`, `needs_review=TRUE`.
*Done:* post-append read-back shows both columns set on every new row.
`MEASURED` — both columns exist in the live header.

**1.4 [LOCKED]** Every model delegation over the corpus is approved by the human before it runs, and
its output is approved before it lands.
*Done:* no batch executes without a recorded approval; no sheet row appends without a per-row verdict.

**1.5 [LOCKED]** The model never writes a customer document. It emits parameters and prose; the
engine renders. *Done:* no model output path calls `generate_document` directly.

**1.6 [LOCKED]** Send is never automated. No work package produces a dispatched email.

**1.7 [LOCKED]** Evaluation never scores against offers present in the retrieval index.
*Done:* the hold-out manifest is written before the index is built, and index construction reads it
and excludes it. *Falsified by:* one evaluation offer found in the index.

**1.8 [LOCKED]** Bound day-codes are byte-identical with the model enabled and disabled.
*Done:* a differential run over the same enquiries produces identical code sequences.
`SOURCED` — carried from `DESIGN_RECORD_2026-09-02` decision 8.

**1.9 [LOCKED]** Enquiry text never leaves the machine. Offer corpus text may.
*Done:* a test asserts enquiry text cannot reach a remote endpoint.
`MEASURED` — all 1087 day snippets scanned post-split-fix: zero email addresses, zero phone numbers;
the 17 phone-shaped hits are price/pax table fragments (`1650 / 14-15`). Bil Weekend's own contact
block sits entirely in the boilerplate trailer that the split fix removes.
`SOURCED` — `ws-01 [LOCKED] R5` names customer names, emails, phone numbers and request text as the
data class requiring an explicitly recorded trust decision.

---

## 2. Decisions

| # | Decision | Choice | Runner-up and the condition that would flip it |
|---|---|---|---|
| D1 | Factory placement | **A3** — module inside one Odysseus instance | A2 (separate process) if instance consolidation proves unsafe |
| D2 | Offer store | **B2** — directory per offer, `routes.json` generated | B3 (SQLite) if the corpus exceeds a few thousand offers |
| D3 | Phase-1 mechanism | **C1** — cluster, model drafts, human approves each | C3 (human authors) if draft quality is unusable |
| D4 | Retrieval | **E3** — two-stage, route skeleton then per-day fill | E1 (whole-offer few-shot) if the day index underperforms |
| D5 | Normalization | **F2** — strip weekdays, dates, clock times, `night N`, bare years | F1 if the re-validated threshold cannot be placed in empty space |
| D6 | Model | **cloud, whichever large model is offered**; Gemma not required | local-only if the cloud tier's limits block WP1.3 |
| D7 | Host | **consolidate onto one branch, work there** | — |
| D8 | Egress | **corpus to cloud, enquiries local** | — |

**Rejected and why, kept visible:** B1 (extend `routes.json` in place) keeps no raw file and is how
the original corpus was lost. C2 (model proposes the template set unsupervised) has no measurement
supporting it. J1 (everything to cloud) sends customer PII with no offsetting benefit, since the
corpus scan shows the drafting workload carries none. J3 (redact then send) has no redaction layer in
either tree and fails silently.

---

## 3. Open questions

**3.1 RESOLVED 2026-09-03 — `main`, created from `local-agent-1` in `odysseus-agent-1`.**
`daily-driver` and `local-agent-2` are both ancestors of `local-agent-1`, so `main` is a
fast-forward containing all three with no conflicts. `MEASURED` — `git merge-base --is-ancestor`
returns true for both. Correcting an earlier claim: `local-agent-1` already carries
`routes/operations/` and `services/itinerary/`, so no code had to move at all — only the branch
needed creating. `data/app.db` and `data/.app_key` stay where they are, untouched.

**3.2 RESOLVED 2026-09-03 — `qwen3.8:27b` is the local enquiry model.**
It is installed and needs no download. The cloud model for corpus drafting remains behind the
WP5.1 config seam.

**3.5 RESOLVED 2026-09-04 — the repository reaches outside itself nowhere.**
`services/itinerary/pipeline` holds the vendored engine: 14 modules, 4245 lines, plus a
purpose-built `config.py` carrying only the 12 values the generation path reads. The web GUI's
session password and sync PIN are not vendored, because nothing in the package serves a UI, and no
credential is committed — `CREDENTIALS_FILE` names a location resolved from the environment.
`BILWEEKEND_REPO_ROOT` is gone. `MEASURED` — a smoke test builds, validates and prices a four-day
itinerary from the vendored modules alone, with real site-availability warnings.

The catalogue has one home. `services/offers` owns it (it is what syncs it from the sheet) and the
pipeline reads it from there, so a second drifting copy cannot exist.

Its Google dependencies — previously satisfied by the separate checkout's own requirements — are now
declared in this project's `requirements.txt`.

**3.3 [OPEN] Cloud catalogue.** Blocks WP5.1.
`ollama signin` exists in v0.33.0, so cloud models are supported by the installed client. `MEASURED`
Which models the tier offers is **unknown** — verification requires signing in under the owner's
account, which is not an agent action.

**3.4 [OPEN] Near-miss floor.** Blocks WP1.1.2; resolved by WP1.1.4.
The band below 0.85 that separates "known template, edited" from "genuinely new" is unmeasured.

---

## 4. Work breakdown

### WP0 — Recover the corpus

- **0.1 [MUST]** Consolidate branches, select the host checkout, and confirm it can decrypt
  `book@bilweekend.com`. *Done:* an IMAP connection from the host lists the Sent folder.
  *Blocked by 3.1.* Credential decryption is **unverified** — the check was refused by the
  permission classifier this session.
- **0.2 [MUST]** Fetch every Sent message with attachments, 2026-02-03 → 2026-09-03.
  *Done:* a manifest with message-id, date, subject, recipient, filename, MIME type, byte size.
  *Falsified by:* a message in range with attachments absent from the manifest.
- **0.3 [MUST]** Offer store at `offers/<message-id>/{source.<ext>, text.txt, offer.json}`.
  *Done:* every manifest row has a directory and `source.*` byte-length matches the manifest.
- **0.4 [MUST]** Text extraction for `.docx`; **[MUST]** for `.pdf` if present. Format distribution is
  **unknown** until 0.2 runs; no PDF reader exists in either tree. `SOURCED`
  *Done:* every attachment yields non-empty `text.txt`, or appears in a named exclusions file with a
  reason.
- **0.5 [MUST]** Day split with terminator. Split on `Day N`; terminate at the first of
  `end of tour | Includes: | Pricing: | Optional: | General Information: | Price: | Inclusions: | Notes:`.
  **[SHOULD]** live in the extractor, not in each consumer.
  *Done:* no day block exceeds 400 words, or each exception is listed with its text.
- **0.6 [MUST]** Generate `routes.json` in the existing schema.
  *Done:* `curated.runner --check` and the fork's itinerary tests pass unchanged against it.
- **0.7 [MUST]** Reconcile against the existing 164 offers.
  *Done:* a three-way count — mail-only, corpus-only, both — with the matching rule stated.
  Overlap is **unknown**: only 30 of 164 filenames carry a month word, none a reliable year. `MEASURED`
- **0.8 [WONT]** Read any mailbox folder other than Sent, or any date outside the range.

### WP1 — Close the catalogue gap

- **1.1 [MUST]** Matcher: `0.5 × Jaccard + 0.5 × SequenceMatcher`, `Overnight:` line excluded from the
  day body, threshold **0.85**, F2 normalization. **[MUST]** re-validate the threshold under F2 before
  use. *Done:* every template scores 1.000 against itself and the threshold sits in empty space
  between template-derived and known-bespoke days, or the threshold changes and the new gap is stated.
  `SOURCED` — `docs/docaut-staging.md`: changing the scoring formula invalidates the threshold.
  - **1.1.1 [MUST]** Partition unmatched days into *near-miss* and *genuinely new* before drafting.
    *Done:* every unmatched snippet carries a band label and its best-matching template code.
  - **1.1.2 [MUST]** Near-misses become edit proposals against the existing template, never new rows.
    *Done:* no appended row scores above the near-miss floor against an existing template.
  - **1.1.3 [MUST]** Replace strict argmax with all-matches-above-threshold; ties and multi-matches
    surface for human resolution. *Done:* a day matching two templates ≥0.85 produces both codes and a
    flag, not a silent first-wins pick.
  - **1.1.4 [MUST]** Set the near-miss floor from measurement. *Done:* a table of band vs. hand-labelled
    verdicts on a sample.
  - **1.1.5 [SHOULD]** Fix this in the engine's matcher, not a factory copy — a second divergent matcher
    is how the fork's five regressions happened.
- **1.2 [MUST]** Cluster unmatched days greedily at 0.85.
  *Done:* a cluster manifest — pattern id, occurrence count, member snippet ids, dominant overnight city.
- **1.3 [MUST]** Model drafts one template row per recurring pattern, citing its member snippet ids.
  *Done:* a draft per recurring pattern, each with citations.
  *Falsified by:* a draft whose `full_text` contains a date, a price, or a named client.
- **1.4 [MUST]** Approval queue: one human verdict per draft — approve, edit, reject.
  **[SHOULD]** show the draft beside its member snippets and the nearest existing template with score.
  *Done:* every draft carries a terminal verdict and timestamp; none reaches 1.5 without one.
- **1.5 [MUST]** Append to `Pricing_information` → `templates`, 11 columns in live header order.
  **[MUST]** preflight for merged ranges; **[MUST]** read headers live at write time.
  *Done:* post-write read-back matches what was staged, cell for cell.
  Service-account **write** access to this tab is **unverified**; read is confirmed. `MEASURED`
- **1.6 [MUST]** One stated rule assigning `region` and `overnight_city`, applied at creation.
  *Done:* every city appearing as `overnight_city` maps to exactly one region across all templates,
  or the exceptions are enumerated with reasons. *Falsified by:* one city with two regions afterwards.
  `SOURCED` — open bug B18; the measured gap concentrates on Baghdad and Mosul, the cities B18 names.
- **1.7 [MUST]** Re-measure coverage after append, on the same corpus, delta attributed to named templates.
- **1.8 [MAY]** Draft the singleton patterns. Default is to leave them bespoke.
- **1.9 [WONT]** Write to `To-Do`, `Upcoming Tours`, `Arrivals`, or `Hotels`.
- **1.10 [WONT]** Translate template codes into operations' shorter vocabulary — it exists nowhere. `SOURCED`

### WP2 — Retrieval index

- **2.1 [MUST]** Hold-out split, written before any index exists. **[SHOULD]** ≥20 offers, stratified by
  tour type and day count. *Done:* a manifest of held-out message-ids.
- **2.2 [MUST]** Route index on region set, day count, tour type, reusing `scorer.score()` unchanged.
  *Done:* for each held-out offer its own route is absent and top-k returns k scored routes.
- **2.3 [MUST]** Day index under F2, keyed by overnight city and region, carrying the matched code.
  *Done:* a query for a known day ranks its own cluster's members above unrelated days.
- **2.4 [MAY]** Embedding retrieval instead of lexical. Default is lexical.

### WP3 — Generation

- **3.1 [MUST]** Enquiry normalization reusing `REGION_NAME_MAP`. *Done:* the four customer-facing
  regions map to the three the templates model; an unmapped region fails loudly. `SOURCED` — B16 fix.
- **3.2 [MUST]** Stage-1 route retrieval → top-k skeletons. *Done:* k scored skeletons per enquiry.
- **3.3 [MUST]** Stage-2 day retrieval → per-slot candidates plus template code where matched.
  *Done:* every slot has ≥1 candidate or is marked a gap.
- **3.4 [MUST]** Model call, local model only (1.9). Output: ordered day codes, dates, hotel tier, pax,
  transport; plus prose for codeless days. **[MUST]** fail closed — an unreachable model holds the row.
  *Done:* a malformed or absent response produces a held row and no document. *Blocked by 3.2.*
- **3.5 [MUST]** Engine render, including the inline-day path opened by decision 2.4=D.
  *Done:* a Doc renders with both templated and bespoke days, and 1.2's regression run stays byte-identical.
- **3.6 [MUST]** Evaluation over held-out offers and curated requests with a finalised link.
  Metrics **[MUST]** include day-code sequence agreement, day-count agreement, region-set agreement,
  gap count. *Done:* a scored table. How many curated requests carry a populated link is **unknown** —
  it needs live Supabase credentials.
- **3.7 [WONT]** Pricing generation. The engine prices; the model does not touch it.

### WP4 — Human loop

- **4.1 [MUST]** Review surface: submit an enquiry, see parameters, gaps and prose, approve or edit.
  *Done:* a full submit → review → edit → re-render cycle completes without leaving the host.
- **4.2 [MUST]** Every human edit stores the before/after pair and the enquiry that produced it.
  *Done:* each correction is retrievable by enquiry id.
- **4.3 [SHOULD]** A correction produces a model-drafted rule; a human promotes, merges, or discards it;
  only promoted rules reach a prompt. *Done:* a rule store where each entry carries its anchoring
  example and a promotion verdict.
- **4.4 [MAY]** Auto-suggest merges between similar rules.
- **4.5 [WONT]** Auto-accepted rules. `SOURCED` — rejected in `DESIGN_RECORD_2026-09-02`.

### WP5 — Cross-cutting

- **5.1 [MUST]** One config field selects endpoint and model id; changing it touches no caller.
  *Done:* local and remote run the same call path. *Blocked by 3.3.*
- **5.2 [MUST]** Egress control at a single chokepoint, not per call site.
  *Done:* the test named in 1.9 passes.
- **5.3 [SHOULD]** One JSON trace per generated row; traces are diagnostics, never state.
  *Done:* deleting every trace changes no row's status.
- **5.4 [MUST]** No test touches the live sheet, Google APIs, Supabase, or a model endpoint.
  **[MUST]** pin the eight ops-layer behaviours carried from `curated` and the five fork divergences,
  each with a test that fails if the behaviour is removed. `SOURCED` — line-cited in
  `DESIGN_RECORD_2026-09-02`. *Done:* the suite runs green with no network and no credentials.
- **5.5 [WONT]** Port `curated`'s sheet-polling runner. Enquiries arrive through WP4.

---

## 5. Measurements appendix

All figures below were produced this session against
`OperationsAutomationSrv/curated/data/routes.json` (164 offers) and
`WebOperationsBilW/data/templates/*.json` (28 templates), using the shipped formula
`0.5 × Jaccard + 0.5 × SequenceMatcher` at threshold 0.85.

**Day-splitter defect.** 158 day blocks exceed 400 words. All 158 are the last day of their route,
one per route, across 158 of 164 routes. Median words: last-day 1186, all other days 105. The
terminator regex resolves 158 of 158, no misses. Truncated last-day median 78 words, max 305.
First marker hit: `end of tour` 83, `Includes:` 54, `Pricing:` 10, `Optional:` 8,
`General Information:` 3.

**Coverage.**

| | raw | split fixed | split fixed + F2 |
|---|---|---|---|
| Matched ≥0.85 | 200 (18.4%) | 219 (20.1%) | 377 (34.7%) |
| Unmatched | 887 | 868 | 710 |
| Distinct patterns @0.85 | 439 | 498 | 405 |
| Recurring patterns (>1×) | 127 | 112 | 100 |
| Max block length | 1370 w | 305 w | 305 w |

The pattern count rises after the split fix because the 158 boilerplate-laden blocks were
near-identical to each other and collapsed into false clusters; truncated, they resolve into distinct
departure days.

**Gap by overnight city** (split fixed): Baghdad 219, day-trips 152, Mosul 126, Nasiriyah 87,
Erbil 69, Karbala 57, Najaf 50, Basra 49, Duhok 22.

**Matcher defect — template-plus-edit is invisible.** `MO1` scores **0.848** against three real offer
days (`yassine_center_north`, `vasco_barbosa_5_days`, `salam_aljazden_7_days_in_iraq`). The template
is 84 words; the offer day is 95. The difference is one added clause — *"and al tahira church that
are being rebuilt by unesco"*. A genuine match falls below threshold on eleven words.

**Matcher defect — argmax hides templates.** Nine templates never win the argmax, but four clear or
nearly clear the threshold against real days: BB 0.944 (24 days ≥0.60), AMBASO 0.917 (11),
NA1 0.905 (42), MO1 0.848 (75). Genuinely unmatched: URUK 0.491 (0), MOBKHEB 0.237 (0). All nine are
`active=True`, `needs_review=False`, with empty `internal_notes` — the sheet records nothing about
them being retired.

**Corpus profile.** 164 offers, 1087 day snippets, 142 individual / 22 group, 1–17 days,
`themes` empty on all 164.

**Append target.** Spreadsheet `1EiNUPoI…` titled `Pricing_information`; tabs `Copied_Ongoing_Sites`,
`templates`, `settings`, `entry_tickets`, `New_Hotels`, `transport`, `guides`, `extras`,
`general_info`. `templates` header: `code · title · city · region · overnight_city · full_text ·
included_sites_json · pricing_tags_json · active · needs_review · internal_notes`. 28 data rows.
Read verified live; write **unverified**.

**Environment.** Ollama v0.33.0, `signin` subcommand present. One local model: `qwen3.8:27b`, 17 GB.
No Gemma installed; "Gemma 31B" is not a shipped size. Outbound reachability confirmed to
`imap.gmail.com:993` and `sheets.googleapis.com:443`. Nothing listening on port 7000; all three
instances default to `APP_PORT=7000`.

**Mail.** Four accounts configured in `odysseus-agent-1/data/app.db`: `book@bilweekend.com`
(imap.gmail.com), `mahdi@bilweekend.iq` (taylor.mxrouting.net), and two personal Gmail accounts.
`odysseus-fork` and `odysseus-agent-2` have zero. `data/.app_key` present in agent-1, 44 bytes.

**PII scan.** All 1087 day snippets, post-split-fix: zero email addresses, zero phone numbers.
Seventeen phone-shaped matches are price/pax table fragments. Counterparty names appear in offer
filenames — `Baalbeck Sky`, `TravelShop`, `Shkran DMC`.

---

## 6. Contradictions and surprises

**The README's "~97% coverage" and the measured 20.1% are both correct and measure different things.**
The README figure counts route-days bindable to *some* day-code by overnight city. The measured figure
counts days verbatim-equivalent to a template at the production threshold. Neither refutes the other.

**The design record claims a nine-section spec that does not exist on disk.** `find` across the whole
tree returns only `docs/workstreams/ws-01/spec.md`, the unrelated phone-backup workstream. This file
replaces it.

**The `Overnight:` exclusion documented in `docaut-staging.md` is real and correctly implemented.**
It happens upstream at body assembly (`src/itinerary_reader.py:235`, "kept out of the matched body on
purpose"), not inside `_normalize`. No template's `full_text` contains an `Overnight:` line, so the
comparison is symmetric. Checked because the code and the doc appeared to disagree; they do not.

**The 0.85 threshold was validated against a document that had not been hand-edited.** Its 9-of-9
result came from a generated document whose days scored 1.000. `docaut-staging.md` separately records
that the confirmed tour in the quote log *was* hand-edited after generation. The validation set never
contained the case that dominates real mail, which is why WP1.1.1 exists.

**The measured 710-unmatched figure is an upper bound, not the catalogue gap.** It merges two
populations — genuinely new days, and known templates with an edit — and the split is unmeasured until
WP1.1.4 sets the near-miss floor.

---

## 7. Revision 2026-09-03 — the scoring defect, and what it moved

**`difflib.SequenceMatcher` was silently discarding most of the sequence half of the score.**
Its `autojunk` heuristic drops any element appearing in more than 1% of a sequence longer than 200
elements. The comparison runs over *characters*, so it was dropping the space and most common
letters, and every day template is longer than 200 characters. It also junks only the second
argument, so `similarity(a, b) != similarity(b, a)`.

`MEASURED` on one edited day against the template it came from: Jaccard 0.827, sequence ratio
**0.205 with autojunk and 0.924 without** — a combined score of 0.516 against 0.875.

**Fixed with `autojunk=False`** in `services/offers/day_match.py` and in the engine's
`src/itinerary_reader.py`. Every figure in section 5 that involves a below-1.0 score was measured
with the defect present and is superseded by the table below.

### Coverage, re-measured over the same 1087 days

| | before the fix | after |
|---|---|---|
| Matched ≥0.85 | 380 (35.0%) | **518 (47.7%)** |
| Near miss [0.70, 0.85) | 122 | **162** |
| Unmatched | 585 | **407** |
| Distinct patterns | 341 | **261** |
| Recurring patterns | 78 | **59** |
| Templates no offer references at all | 9 | **2** — `MOBKHEB`, `URUK` |

Top templates by edited use: `MO1` ×25, `BG1` ×22, `BBNJ` ×19, `BAEB` ×12, `NA2BG` ×12, `BBKA` ×11.
Templates used only in edited form, never verbatim: `BA1`, `BANMEB`, `SUHA`.

**3.4's premise is answered by this.** The near-miss band is not a marginal population — 162 days,
attributed to 25 named templates. The claim that the catalogue was barely used was an artifact of
the scoring defect, not a property of the catalogue.

### Deployed behaviour changed, deliberately

The engine's live regression on doc2 moved from **0 of 13** template days accepted to **1 of 13**:
day 6 now matches `SAMO` at 0.875. That is a correction rather than drift — `docaut-staging.md`
records that operations logged 13 day codes for this tour, of which 4 exist as templates, so some
acceptance was always expected. doc1 is unchanged: all 9 codes recovered, zero warnings.
The canary test was re-pinned on the measured behaviour (`accepted == {6: "SAMO"}`), not deleted.

### Also revised

**`unused_codes` split into two fields.** `never_matched_codes` and `never_referenced_codes`. A
template no day matched outright may still be in daily use in edited form, and the two demand
opposite work — revise, or retire.

**`AMBIGUITY_MARGIN = 0.05` added.** Two templates both clearing the threshold is not ambiguity.
`BANMEB` and `BAEB` score 0.850 against each other, so a verbatim day of either has a second
template above threshold; warning on that would have made every itinerary containing one noisy and
would have failed doc1's `warnings == []` pin.

---

## 8. WP1.1 threshold re-validation (2026-09-04)

**The empty space the threshold was placed in no longer exists.** Its original justification was
that template days scored 1.000 and the best bespoke day scored 0.703, leaving a wide gap. With
autojunk removed, the best-score distribution over 1087 days is continuous from 0.60 to 1.00 with no
gap anywhere — `MEASURED`, histogram in 0.01 buckets. The threshold now has to rest on something
else.

**Independent corroboration used instead: overnight-city agreement.** Whether a day's own
`Overnight:` city equals its best-matching template's `overnight_city` is evidence the scorer never
sees, so it can referee the scorer.

| best-score band | days | city agrees |
|---|---|---|
| 0.95–1.00 | 287 | **96%** |
| 0.90–0.95 | 72 | 86% |
| 0.85–0.90 | 117 | 83% |
| **0.80–0.85** | **72** | **82%** |
| 0.75–0.80 | 24 | 58% |
| 0.70–0.75 | 34 | 65% |
| 0.60–0.70 | 104 | 36–44% |
| below 0.30 | 31 | 8–32% (chance) |

**Two conclusions.**

`MATCH_THRESHOLD = 0.85` stays defensible — everything above it agrees at 82% or better, far above
the ~20% chance level the low bands show. But **0.80 performs identically to 0.85** (82% against
83%), so the current threshold rejects 72 days that behave exactly like accepted ones. Lowering it
is a real improvement, and it is **[OPEN]** rather than taken: 0.85 was set by explicit instruction,
and a number the owner chose is not one to move on an agent's initiative.

`NEAR_MISS_FLOOR = 0.70` is corroborated and promoted from `[DEFAULT]` to settled. The 0.70–0.80
band sits at 58–65% agreement — clearly above chance, clearly below the match bands. That is exactly
the signature of a template that was edited, including edits that moved the overnight city.

---

## 9. WP0 complete — the corpus is recovered (2026-09-04)

**95 offers recovered from mail**, 349 messages scanned across `book@bilweekend.com` (324) and
`mahdi@bilweekend.iq` (25). Four attachments yielded no text — PDFs with no text layer, recorded as
failures rather than silently dropped. `MEASURED`

**The corpus has changed generation.** The legacy 164 offers were `.docx`; of the recovered offers
carrying an itinerary, **67 are PDF and 1 is `.docx`**. Every parser assumption inherited from the
`.docx` era had to be re-earned against PDF text, which flattens layout.

### Defects found and fixed against real mail

**The store lost offers to a key collision.** Keying a stored offer on its message id alone meant a
message carrying two offers — commonly a group and an individual version of one trip — silently
overwrote itself: 95 stored, 89 on disk. The key now includes the attachment. `MEASURED`

**PDF day headings are not at line start.** Extraction flattens an itinerary onto one line with
doubled spaces, so a line-anchored `^Day N` found nothing. A loose form is now tried when the strict
one finds no itinerary, and the strict form is still preferred when both work.

**One stray day number rejected a whole offer.** A 10-day offer yielded `[1,2,3,4,6,5,6,7,8,9,10]` —
a "Day 6" inside a hotel table. The guard now extracts the longest sensible run instead of vetoing
the document.

**The longer itinerary wins.** Preferring the strict form unconditionally settled for a single stray
`Day 1` line in PDFs whose remaining days were mid-line, cutting the corpus from 577 days to 452.

**The trailer terminator did not fire on PDFs** for the same flattening reason. A loose pass now
matches only the unambiguous headings — `End of tour`, `Includes:`, `Inclusions:`,
`General Information` — because `Optional:` and `Notes:` legitimately appear inside a day.

Net effect on the same recovered text, no re-download: **385 days → 577**, longest day 1358 → 615
words, days over 400 words 35 → 2, median 102. `MEASURED`

**27 attachments hold no itinerary at all** — catalogues, rooming lists, contracts, company
profiles, an electronic-document receipt. These are no longer stored as offers; they are recorded
with a reason. Three that *look* like offers are a known limitation, not a bug: two use named days
("Babylon Day", "Karbala Day") and one is an unnumbered single-day tour, so no day numbering exists
to split on.

### The gap, measured against what was actually sent

| | recovered corpus (68 offers, 577 days) |
|---|---|
| Matched ≥0.85 | **302 (52.3%)** |
| Near miss — edits to existing templates | **55** |
| Unmatched — candidates for new templates | **220** |
| Distinct patterns / recurring | **159 / 43** |
| Templates used only in edited form | `URNJ` |
| Templates no offer references at all | `MOBKHEB` |

Most-edited templates: `NA2BG` ×11, `MO1` ×9, `BG1` ×7, `BBKA` ×6, `NA1` ×4.

**49 proposals now sit in the review queue: 6 revisions and 43 new templates.** Every proposed
wording is a verbatim day a human actually sent, carrying the day keys it came from. No model was
involved, so this ran before any model delegation was approved (invariant 1.4).

**Known review-quality issue.** Proposed text still carries PDF artefacts — `◆` bullets, `/`
prefixes, and embedded dates such as "Saturday Aug 8". Cleaning these is exactly WP1.3's model
drafting step, which is gated on the owner approving a model delegation. Until then the reviewer
edits them in the page.

---

## 10. What exists, and where (2026-09-04)

All of it inside the odysseus repository, on branch `main` in `odysseus-agent-1`.

| Module | Responsibility |
|---|---|
| `services/offers/models.py` | `SentOffer`, `OfferDay`, `TemplateMatch`, `DayPattern`, `GapReport`, the three match bands |
| `services/offers/catalogue.py` | the 28 day templates, vendored under `services/offers/data/` |
| `services/offers/day_match.py` | F2 normalization, similarity, ranking, bands, ambiguity margin |
| `services/offers/offer_text.py` | docx and PDF extraction, day splitting, trailer trimming |
| `services/offers/offer_store.py` | one directory per offer, keyed by message **and** attachment; `routes.json` as a build artifact; reparse from stored text |
| `services/offers/sent_offers.py` | Sent-folder recovery, reusing odysseus's own IMAP layer |
| `services/offers/legacy_corpus.py` | the pre-mail 164 offers, for WP0.7 reconciliation |
| `services/offers/gap_report.py` | banding, clustering, coverage |
| `services/offers/propose.py` | gap → reviewable proposals, no model involved |
| `services/offers/proposals.py` | the proposal store and its verdicts |
| `services/offers/apply_to_sheet.py` | the only code that writes the catalogue; dry-run by default |
| `services/offers/recover.py` | `python -m services.offers.recover` — fetch, dry-run, reparse, prune |
| `routes/offers/offers_routes.py` | gap, queue, verdicts, evidence, catalogue listing |
| `static/offers_review.html` | the review page served at `/offers` |
| `services/itinerary/pipeline/` | the vendored engine |

**Persisted paths**, all declared in `src/constants.py` as the repository requires:
`OFFER_CORPUS_DIR`, `TEMPLATE_PROPOSAL_DIR`.

**Tests**: 93 across `test_offers_module.py`, `test_offers_apply.py`, `test_offers_routes.py`. None
touches the network, a mailbox, Google, or the real corpus. Route handlers are driven directly
rather than through `TestClient`, per `tests/TESTING_STANDARD.md`.

### Still open

- **WP1.3 model drafting** — blocked on the owner approving a model delegation (invariant 1.4).
  Until then proposals carry verbatim sent text, PDF artefacts included.
- **B2 matcher divergence** — `services/offers/day_match.py` uses F2 normalization; the engine's
  `itinerary_reader.py` does not. Both now share the autojunk fix. One formula should win.
- **MATCH_THRESHOLD 0.85 vs 0.80** — measured as equivalent; the owner set 0.85, so it stands.
- **27 non-itinerary attachments** still stored from before the fetcher learned to refuse them;
  `--reparse --prune` discards them.
- **Named-day offers** — two documents use "Babylon Day"/"Karbala Day" and one is an unnumbered
  single-day tour. No day numbering exists to split on; they are not in the corpus.
- **Workbench docking** — `/offers` is a standalone page, not a rail panel.

---

## 11. WP0.7 reconciliation, and a suite defect (2026-09-04)

**The 7-month window does not contain the legacy corpus.** `services/offers/reconcile.py` compares
the two corpora on itinerary content rather than filename, because filenames drift between the
`.docx` and PDF eras while the itinerary does not.

| | |
|---|---|
| In both | **36** |
| Legacy only — survives nowhere else | **128** |
| Recovered only — newer than the legacy extract | **32** |

**The count is threshold-sensitive and the distribution has no gap**, so it is reported as a range:
128 legacy-only at the 0.7 day-coverage rule, 104 at 0.6, 75 at 0.5, 50 at 0.4. `MEASURED`

Two conclusions hold at every threshold. `routes.json` is **not** redundant — it is the only
surviving record of at least 50 offers — which retroactively justifies tracking it in git (D1). And
the 7-month window is too narrow: the legacy `.docx` offers predate it, so widening the window would
recover originals for offers that currently exist only as a derived extract. **[OPEN]** for the owner.

Comparing whole offers proved intractable — the sequence half of the score is quadratic in text
length, and 164 × 68 whole offers did not finish in nine minutes. The comparison moved to day level,
which is both the unit the corpus is built from and two orders of magnitude shorter: 126 seconds.

**An exact prefilter replaced a wrong one.** Clustering skipped pairs whose token overlap fell below
`MATCH_THRESHOLD / 2`, justified by a comment claiming Jaccard is half the score. The real bound is
`2·threshold − 1`: since the sequence ratio cannot exceed 1, reaching 0.85 requires a Jaccard of at
least 0.70, not 0.425. The old filter was safe but needlessly permissive; `jaccard_lower_bound()`
now states the correct bound once and both clustering and reconciliation use it.

### A pre-existing test defect that hung the suite

`tests/test_tls_overrides_scope.py` walked the whole repository with `rglob("*.py")` and filtered
afterwards. `rglob` descends before any filter runs, so it entered `data/` — the gitignored runtime
directory, which on a working machine holds whole unrelated checkouts: **40,310 `.py` files**,
`node_modules` included. The test never finished, and took the suite with it at ~90%.

Not caused by this workstream: the offer corpus contributes 95 directories and zero `.py` files, and
the hang reproduced with every ws-03 test deselected. It did not appear on the control checkout
because that machine copy has no `data/projects/`.

Fixed by pruning during the walk instead of filtering after it: **never finished → 0.45 seconds,
4 passed.**

### The matcher now has one implementation

`services/itinerary/pipeline/itinerary_reader.py` imports its scoring from
`services.offers.day_match` rather than defining a second copy. Reading a document back and
measuring the catalogue gap ask the same question — "which template is this day?" — and two copies
of that answer is precisely how the earlier port acquired five regressions.

Verified through odysseus alone, with no external checkout: doc1 recovers all nine codes plus `TRF`
with zero warnings; doc2's `SAMO` day improves from 0.875 to 0.927 and its `NA2BG` near miss from
0.703 to 0.767 under F2 normalization.

---

## 12. Owner decisions, 2026-09-04

| # | Decision | Choice |
|---|---|---|
| D1 | Push the commits | Push `main` to `daily-driver`. Done: `a7869cb..be1c816` |
| D2 | Model delegation | **Not granted.** The owner reviews the proposals first |
| D3 | Mail window | 24 months, with older wording weighted down |
| D4 | 27 non-itinerary documents | Discard. Corpus is 68 offers, 21 MB |
| D5 | `MATCH_THRESHOLD` | 0.80, and show the small deviations |
| D6 | Review page in the sidebar | Keep it separate. Dock it later if wanted |

### D5 exposed an interaction the owner had already predicted

The owner chose 0.80 and, in the same answer, said that itineraries are sometimes
flipped because the route is literally flipped. Those are the same problem.

A route driven the other way uses almost the same words in almost the opposite order.
Token overlap is blind to order and carries half the score.

`MEASURED` on a reversed three-sentence day: jaccard 1.000, sequence 0.671, score
**0.836** — below the old 0.85, above the new 0.80. **The threshold change alone would
have made the catalogue accept a journey as its own mirror.**

`MEASURED` in the live corpus: 7 of 577 day/template pairs show the signature, and every
one is the Najaf/Uruk mirror — `NAURUKNJ` against `URUKNA`, codes that encode direction.
They score 0.62 to 0.68, so they were already becoming new-template proposals with no
hint that the catalogue held the same journey backwards.

**A reordered pair is now neither a match nor an edit.** Not a match, because opposite
journeys are different days. Not an edit either: that was tried first and was worse — it
proposed replacing the mirror template with the reversed wording. It is a day the
catalogue does not express, and the proposal names the mirror so a human decides whether
the reversed route deserves its own row.

`TemplateMatch` now carries both halves of its score. The mean hides the thing that
matters here: jaccard 1.000 with sequence 0.671 is a fact about order that 0.836 cannot
express.

Engine regression unchanged at 0.80 with the rule in place: doc1 recovers all nine codes
plus `TRF` with zero warnings; doc2 accepts exactly `{6: SAMO}`.

### D3 splits along the line the owner drew

The owner said the older offers matter less because things changed, but that the routing
is still viable. That is two different uses of one offer.

**Wording ages.** Sites close, hotels move, prose is rewritten. A day from two years ago
is weaker evidence for what a template should say.

**Routing does not age.** The city sequence, the day count and the tour type of a
two-year-old offer are as valid as today's.

The discount therefore applies to day-text evidence only, and never to route retrieval.
Half-life 365 days: 12 months counts 0.500, 24 months counts 0.250. A day with no date
weighs 1.0, because absence of a date is not evidence of age — only the legacy extract
lacks one, and that is used for routing.

Patterns and proposals are ranked by weight and reported by count. Two recent days
outrank three old ones, and the reviewer sees both numbers rather than one figure that
hides which it is.

### Still open

- **WP1.3 model drafting** — the owner reviews the queue first. Proposal wording is now
  clean prose; what a model would still remove is embedded dates, prices and client names.
- **C3 `BANMEB` / `BAEB`** — the owner chose to differentiate them. The pair scores 0.850
  against each other and will surface in the review queue.
- **Route retrieval must not apply the recency weight.** WP2 is not built; the rule is
  recorded where the weight is defined so it is not applied by reflex.
