# ws-03 phase five — the three layers, the screenshots, and the run record

Written 2026-09-07. Read `phase-four-spec.md` first for the checks this phase
uses, and `handover.md` for the state it starts from.

## 0. Numbering

This phase continues the earlier WP numbers. Phase four defined WP11 to WP15.
WP16 to WP23 are new. Decisions continue from D37.

## 1. What this phase builds

The desk reads a customer's conversation screenshots, reasons about what the
customer asked for, chooses one itinerary from the candidates the rules
produce, and states whether the result answers the request.

Every step writes what it did into a record a human can read.

Two buttons in Operations start the work. The first button makes a proposal.
The second button makes the document.

## 2. Decisions

| # | Decision |
|---|---|
| D38 | Each itinerary layer resolves its own endpoint. An unset role reaches no other model |
| D39 | A brief may fill a request field the queue left blank. It never overwrites a value the queue holds |
| D40 | The candidates are the routes that tie at the top match score. No model invents a day code |
| D41 | Layer 3 writes a note. It never stops a build |
| D42 | The run record holds every prompt, every answer and every endpoint. It lives apart from the draft |
| D43 | A layer that is off, or that could not run, records itself as untested. The run continues |
| D44 | Both buttons live in Operations. Operations shows the verdict and the brief. The desk holds the trace |
| D45 | The Operations generator opens a draft. No document is built without one |
| D46 | The extraction step and layer 1 are separate. A human may edit the extracted text |
| D47 | D25 stays as the master switch. Each layer carries its own switch below it |
| D48 | A screenshot is untrusted text. Its content is data for a reader, never an instruction for a layer |

D40 and phase four §9 do not conflict. §9 refused a repair to `find_best_route`.
This phase repairs nothing there. It reads the tie the function already has, and
it uses every tied route.

D39 and D25 do not conflict. D25 governs whether request text reaches an
endpoint. D39 governs what the answer may change after it arrives.

## 3. Invariants

**3.1 [LOCKED]** Invariants 1.1 to 1.9 in `spec.md`, 2.1 to 2.4 in
`phase-three-spec.md`, and 2.1 to 2.5 in `phase-four-spec.md` bind unchanged.

**3.2 [LOCKED]** An itinerary layer reaches only an endpoint the owner named for
that layer.
*Falsified by:* one run record that names `default_model` for a layer whose own
role is unset.

**3.3 [LOCKED]** No model text reaches a customer document.
*Falsified by:* one sentence of a brief, a ranking reason or a layer 3 note in a
rendered Google Doc.

**3.4 [LOCKED]** A brief never overwrites a value the queue row holds.
*Falsified by:* one run where a normalized field differs from a filled column.

**3.5 [LOCKED]** A run that could not read the screenshots is never reported
complete.
*Falsified by:* one run record with an empty `untested` list and no extracted
text.

**3.6 [LOCKED]** Every day code in a candidate names an active template.
*Falsified by:* one code in a candidate that `active_day_templates()` does not
hold.

**3.7 [LOCKED]** The run record is written. It is never rewritten.
*Falsified by:* one record whose step output changes after the run ends.

## 4. Measured facts this spec stands on

Each figure was measured on 2026-09-07. Confidence is stated for each.

| Fact | Value | Confidence |
|---|---|---|
| Columns on a `queue_requests` row | 36 | measured, live read |
| Rows that carry `conversation_link` | 6 of 6 | measured, live read |
| Rows that carry `itinerary_link` | 1 of 6 | measured, live read |
| Rows that carry `email_chain_link` | 0 of 6 | measured, live read |
| Files in this repository that read `conversation_link` | 0 | measured, grep |
| Drafts on disk that already hold the link | 4 of 55 | measured, file read |
| Service account read of a conversation link | HTTP 404 | measured, two links, two scopes |
| Service account read of the output folder | success, folder named `API` | measured |
| Models the configured endpoint serves | 1, `qwen3.8:27b`, 17.7 GB | measured, `/api/tags` |
| Capabilities of that model | completion, vision, tools, thinking | measured, `/api/show` |
| Context length of that model | 262144 | measured, `/api/show` |
| `vision_model` setting | empty | measured |
| `default_model` setting | `gemma4:31b-cloud` | measured |
| Routes that tie at the top match score | 5 to 11 | measured, phase four |
| Codes the binder reaches, of 60 | 52 | measured, phase four |

**Unknown, and the reason.** Nobody can say what one conversation link holds.
The read answers 404, so findability ends at the folder boundary. The link may
name one file or one folder. Both shapes must work.

## 5. WP16 — the run record

**16.1 [MUST]** One run record holds every step, with its input, its output, its
endpoint and its time.
*Done:* `data/itinerary_runs/<run_id>.json` reads back with seven steps.
*Falsified by:* one step that reached a model and records no endpoint.

**16.2 [MUST]** The draft names the runs it produced.
*Done:* a `run_ids` list on `ItineraryDraft`, newest last.
*Falsified by:* a run that no draft points to.

**16.3 [MUST]** A run record never enters `comments`.
*Done:* `GET /api/itinerary/comments` returns what a human wrote and nothing
else (D33 continues).
*Falsified by:* one run step that the comments route returns.

**16.4 [MUST]** A second run writes a second record.
*Done:* two records for one draft, each readable, neither changed.
*Falsified by:* a run that overwrites the record before it.

**16.5 [MUST]** The record states which steps did not run, and why.
*Done:* an `untested` list, in the shape `SequenceCheck.untested` already uses.
*Falsified by:* a disabled layer that leaves no trace.

**16.6 [SHOULD]** The record states how long each step took.
*Done:* a millisecond figure per step.

**16.7 [WONT]** A prompt in the generated document. Invariant 3.3 forbids it.

## 6. WP17 — the screenshot reader

**17.1 [MUST]** The reader takes `conversation_link` from `request_row`.
*Done:* the four queue drafts on disk resolve to a Drive id.
*Falsified by:* a reader that asks Supabase again for a value the draft holds.

**17.2 [MUST]** The reader handles a file id and a folder id.
*Done:* a folder id lists its images. A file id gives one image.
*Falsified by:* a folder id that reads as one file, or the reverse.
*Reason:* the shape is unknown, and a 404 blocks the test today.

**17.3 [MUST]** The Drive scope becomes `drive.readonly`.
*Done:* `google_clients.SCOPES` holds it, and the output folder still opens.
*Falsified by:* a renderer that stops creating documents.
*Owner act:* share each conversation folder with
`mahdibil2@docs-automation-378406.iam.gserviceaccount.com`. Nothing in this
repository can do that.

**17.4 [MUST]** Extracted text is cached against the Drive file id.
*Done:* a second run of the same request reads the cache and calls no model.
*Falsified by:* two model calls for one unchanged image.

**17.5 [MUST]** A human may edit the extracted text, and the edit wins.
*Done:* the edited text reaches layer 1, and the model text does not.
*Falsified by:* a run that uses the model text after an edit exists.
*Source:* the upload path already does this. `PUT /api/uploads/{id}/vision`
stores a human text, and `chat_handler` marks it authoritative.

**17.6 [MUST]** A 404, an empty folder and a disabled role each record untested.
The run continues.
*Done:* a run with no readable screenshot reaches layer 3 and produces a
proposal.
*Falsified by:* a run that stops because a folder is shut.
*Reason:* every folder is shut today. A reader that refuses would refuse every
request.

**17.7 [SHOULD]** The record states how many files one link held.
*Done:* a count per run.

**17.8 [WONT]** Any write to Drive. `drive.readonly` cannot write, and the
renderer keeps its own `drive.file` grant for the document it creates.

## 7. WP18 — layer 1, the brief

**18.1 [MUST]** Layer 1 produces a brief with named fields.
*Done:* the brief reads back as an object, not as prose.
*Falsified by:* a brief that only a human can parse.

**18.2 [MUST]** Layer 1 produces a difference list against the queue columns.
*Done:* a 10-day brief against a 6-day column produces one entry naming both.
*Falsified by:* a disagreement that the record does not hold.

**18.3 [MUST]** A brief value fills a field the queue left blank or placeholder.
*Done:* a blank `number_of_people` column takes the brief's party size.
*Falsified by:* a filled column that changes.
*Reason:* `_parse_int_safe` gives pax a default of 2 when the column is blank.
A brief that says four people is better evidence than a constant.

**18.4 [MUST]** A disagreement on a filled field is reported and never applied.
*Done:* a 10-day brief against a filled 6-day column leaves `day_count` at 6 and
raises one entry.
*Falsified by:* invariant 3.4.

**18.5 [MUST]** The fields a brief may fill are a named list, and contact
details are not on it.
*Done:* the list names day count, party size, regions, sites, dates and
interests. It excludes name, email and phone.
*Falsified by:* a run where a brief changed a customer's email address.

**18.6 [MUST]** The brief is marked as machine text.
*Done:* the brief carries its model, its endpoint and its time, in the shape
`TemplateProposal.suggested` already uses.

**18.7 [SHOULD]** A human may edit the brief, and the edit wins.
*Done:* an edited brief reaches layer 2 unchanged.

**18.8 [WONT]** A brief in the generated document.

## 8. WP19 — the candidate set

**19.1 [MUST]** The candidates come from the routes that tie at the top match
score.
*Done:* a request that ties at 7 routes produces 7 candidates.
*Falsified by:* a candidate whose route did not tie.

**19.2 [MUST]** The candidate count has a ceiling.
*Done:* a tie of 11 produces the ceiling, not 11.
*Falsified by:* a prompt that grows without limit.
*Open:* the ceiling has no measurement behind it yet. Five is a starting value.

**19.3 [MUST]** Each route binds through `bind_route_to_templates`.
*Done:* every candidate uses the phase four tie-break, with its role filter and
its unused-site score.
*Falsified by:* a candidate built by a second binder.

**19.4 [MUST]** `check_sequence` examines every candidate.
*Done:* each candidate carries its own faults, flags and untested list.
*Falsified by:* a candidate that reaches layer 2 unchecked.

**19.5 [MUST]** No day code comes from a model.
*Done:* invariant 3.6.
*Falsified by:* one code that `active_day_templates()` does not hold.

**19.6 [SHOULD]** The record states the spread between candidates.
*Done:* the fault count and the flag count of each.

**19.7 [WONT]** A change to `score_route` or to `find_best_route`. This phase
reads the tie. It does not resolve it.

## 9. WP20 — layer 2, the ranking

**20.1 [MUST]** The model receives the brief, every candidate, and each
candidate's check.
*Done:* the prompt in the run record holds all three.
*Falsified by:* a ranking made without the check.

**20.2 [MUST]** The model answers with one candidate and a reason.
*Done:* the answer parses to an index inside the candidate range.
*Falsified by:* an answer that names a day code.

**20.3 [MUST]** An answer outside the range is a failure, and the record names
it.
*Done:* the run reports the failure and keeps the first candidate.
*Falsified by:* a silent substitution.

**20.4 [MUST]** The chosen sequence lands on the draft with `source=model`.
*Done:* the desk renders it beside the rules sequence, as it does today.

**20.5 [MUST]** A layer that is off keeps the first candidate and records
untested.
*Done:* the run completes with `itinerary_rank_enabled` false.

**20.6 [SHOULD]** The ranking is measured against the graded drafts.
*Done:* a figure for how often the model's choice beat the first candidate, over
the 44 graded drafts.
*Falsified by:* a figure below the first candidate's own score.

## 10. WP21 — layer 3, the reading

**21.1 [MUST]** Layer 3 reads the brief and the chosen sequence.
*Done:* the prompt in the record holds both, and holds no candidate the model
did not choose.

**21.2 [MUST]** Layer 3 writes a note with `source=model`.
*Done:* the note renders in the desk's Machine notes card (WP14).
*Falsified by:* a layer 3 answer that reaches `comments`.

**21.3 [MUST]** Layer 3 never stops a build.
*Done:* button 2 works with a layer 3 note that states a problem.
*Falsified by:* one disabled button whose only cause is layer 3.
*Reason:* D41. The human is the gate, which is D15.

**21.4 [SHOULD]** Layer 3 names the request detail it could not find in the
itinerary.
*Done:* a brief naming the marshes, against an itinerary with no marsh day,
produces a note that names the marshes.

**21.5 [WONT]** A repair. Invariant 2.4 of phase four binds here.

## 11. WP22 — the roles, and the gate

**22.1 [MUST]** Three settings prefixes exist, one per layer.
*Done:* `resolve_endpoint` answers for each, and Settings lists each.
*Falsified by:* two layers that share one prefix.

**22.2 [MUST]** Each layer carries its own switch.
*Done:* layer 1 runs with layer 2 off, and the record states which ran.

**22.3 [MUST]** D25 stays as the master switch above the three.
*Done:* `itinerary_model_proposals_enabled` false stops all three, whatever the
three hold.
*Falsified by:* one model call with the master off.

**22.4 [MUST]** An unset itinerary role reaches no other model.
*Done:* invariant 3.2. The layer records untested.
*Falsified by:* a run record naming `gemma4:31b-cloud` for an unset role.
*Reason:* `resolve_endpoint` reaches `utility`, then `default`, when a prefix is
unset. `default_model` is the cloud model. A shared resolver would send customer
screenshots off the machine in silence.

**22.5 [MUST]** The run record names the endpoint and the model of every step.
*Done:* a reader can say where each customer sentence went.

**22.6 [SHOULD]** The extraction step uses the existing `vision` role.
*Done:* `analyze_image_with_vl` needs no change.
*Falsified by:* a fourth prefix that duplicates it.

**22.7 [MAY]** A per-layer fallback list, in the shape
`vision_model_fallbacks` already uses.

## 12. WP23 — the two buttons

**23.1 [MUST]** Button 1 in Operations starts a run and builds no document.
*Done:* a press produces a draft, a run record and a proposal. Drive holds no
new file.
*Falsified by:* one Google Doc created by button 1.

**23.2 [MUST]** Button 2 builds the document from the chosen sequence.
*Done:* `execute_generation(req, day_codes=chosen)`, which the desk already
calls.
*Falsified by:* a document whose codes differ from the chosen sequence.

**23.3 [MUST]** Operations shows the verdict and the brief.
*Done:* the modal states the fault count, the flag count, the layer 3 note and
the brief.
*Falsified by:* an operator who must open the desk to know whether to press
button 2.

**23.4 [MUST]** The desk holds the full trace.
*Done:* every prompt, every answer and every candidate render on the draft.
*Falsified by:* a run step that no page shows.

**23.5 [MUST]** `POST /api/operations/itinerary/generate` opens a draft.
*Done:* the route creates or finds a draft, and builds from a chosen sequence.
*Falsified by:* a document built with no draft behind it.
*Reason:* the route renders a document today with no draft, no check and no
record. A second door makes every count wrong.

**23.6 [WONT]** A second path that builds a document without a draft.

## 13. This phase does not build

**WONT** A change to `score_route` or `find_best_route` (19.7).

**WONT** A numeric candidate scorer. Layer 2 is the scorer, which is what
phase four item 12.5 waited for. A numeric scorer would compete with it.

**WONT** The three checks phase four named and did not find: the day start, the
skipped sites, and the day trip on a moving day. They stay buildable and unbuilt.

**WONT** A judged-rule interface. Three routes still have no control on the page.

**WONT** Any write to a customer. No email and no message is sent by any layer.

**WONT** A repair to the two blank `overnight_city` cells.

## 14. Measurements this phase must produce

| # | Measurement | Known today |
|---|---|---|
| 14.1 | Files one conversation link holds | unknown, the folder is shut |
| 14.2 | Screenshots the vision model reads without error, of those tried | unknown |
| 14.3 | Brief fields that disagree with a filled column | unknown |
| 14.4 | Brief fields that filled a blank column | unknown |
| 14.5 | Candidates per request, mean and ceiling | tie is 5 to 11 |
| 14.6 | Runs where the model chose other than the first candidate | unknown |
| 14.7 | Runs where the model's choice held fewer faults | unknown |
| 14.8 | Layer 3 notes a human overruled | unknown |

Measurement 14.7 is the one that says whether layer 2 earns its place. A model
that never beats the first candidate is a model this pipeline does not need.

## 15. Risks that stand

**A screenshot is untrusted text, and it reaches a prompt.** D48 states the
rule. Nothing enforces it. A customer image that holds words shaped like an
instruction reaches layer 1, and layer 1 writes the brief that layer 2 obeys.
The named field list in 18.5 limits the damage. It does not remove it.

**Every folder is shut, so 17.6 carries the whole pipeline today.** Until you
share a folder, every run records untested extraction and reasons from the
columns alone. The pipeline works and reads nothing.

**The candidate ceiling has no evidence.** Item 19.2 marks it open.

**Layer 2 may add nothing.** Measurement 14.7 is the test, and it runs after the
build, not before it.

**`find_best_route` still decides the nights.** The tie gives the candidates.
Every candidate still comes from the same scorer that placed 58 nights of 116 in
the offer's city.

## 16. Open

**16.1** Whether one conversation link names a file or a folder. Item 17.2
handles both, and one shared folder settles it.

**16.2** The candidate ceiling in 19.2.

**16.3** Whether `qwen3.8:27b` satisfies D17. The model runs on the tailnet box
and relays nothing. D17 names the cloud model. The reading is the owner's.

**16.4** The three settings prefixes have no agreed names.
