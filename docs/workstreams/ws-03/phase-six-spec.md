# ws-03 phase six — the desk as a queue and one detail pane

Written 2026-09-08. Read `phase-five-spec.md` for the layers this phase shows,
and `handover.md` for the state it starts from.

## 0. Numbering

This phase continues the earlier WP numbers. Phase five defined WP16 to WP23.
WP24 to WP31 are new. Decisions continue from D48.

## 1. What this phase builds

The desk becomes a queue on the left and one detail pane on the right.

The queue holds every tour request, and a filter bar narrows 43 rows to the 9
that need work. The detail pane holds one request: what went in, what each
layer did, and what came out.

Nothing about the four layers changes. This phase is their view.

## 2. Decisions

| # | Decision |
|---|---|
| D49 | The desk is one queue and one detail pane. The queue lists requests and the pane holds one |
| D50 | The queue is one list keyed by request. A draft with no request appears under one filter value |
| D51 | The filter bar is the Operations bar, with a fifth control for the desk's own state |
| D52 | The pane carries a fixed strip of input, run and output, above collapsible sections |
| D53 | A section opens when its own content asks to be read |
| D54 | The desk speaks the tokens the Operations modal speaks |
| D55 | One brief card renders on both pages, from one file |
| D56 | A prompt never renders on the surface. A reader opens it |
| D57 | The list route sends a list. The detail route sends the detail |

D54 and the standalone pair do not conflict. `itinerary_desk.html` and
`offers_review.html` share ten tokens and nothing else: no link, no navigation
and no shared job. The one walked path ends at the Operations modal.

D55 and phase five's V3 do not conflict. V3 put the brief in Operations, and
the owner has now put it on both pages. One file is what stops the two copies
from drifting.

## 3. Invariants

**3.1 [LOCKED]** Every invariant in `spec.md`, `phase-three-spec.md`,
`phase-four-spec.md` and `phase-five-spec.md` binds unchanged.

**3.2 [LOCKED]** A prompt reaches no surface until a reader asks for it.
*Falsified by:* one prompt rendered without a click.

**3.3 [LOCKED]** Every draft on disk is reachable from the queue.
*Falsified by:* one draft that no filter value shows.

**3.4 [LOCKED]** The brief card has one definition.
*Falsified by:* a second place that renders a brief field.

**3.5 [LOCKED]** An unreachable worklist reads as a failure and never as "no
work" (ws-03 D14).
*Falsified by:* an empty queue with no error beside it.

**3.6 [LOCKED]** The desk builds no document that a reviewer did not choose a
sequence for.
*Falsified by:* one document built from an empty sequence.

## 4. Measured facts this spec stands on

Each figure was measured on 2026-09-08 and is stated as measured, not as
estimated.

| Fact | Value |
|---|---|
| Tour requests on the live worklist | 43. 37 curated, 6 queue |
| Requests with status New | 9. 8 of them carry the risk `confirmed-spam` |
| Requests marked spam or suspected | 9 |
| Requests that are New and not spam | 1 |
| Requests that are not spam, any status | 34 |
| Open drafts | 10. 9 match a request, 1 does not |
| Requests carrying no operator | 17 of 43 |
| Requests carrying a next action date | 1 of 43 |
| `GET /api/itinerary/drafts` | 51,646 bytes for 11 drafts |
| The largest draft in that answer | 16,935 bytes, of which 10,178 is sequences |
| One full run record, four layers on | 38,799 bytes |
| Prompts in that record | 16,205 characters over three steps |
| Everything else a reader reads | under 10,000 bytes |
| `static/style.css` | 41,421 lines, 1.3 MB |
| The desk today | 167 HTML lines, 637 JavaScript lines |
| Links from the app to either standalone page | 0 |

**One fact reached its limit.** Nobody logs which controls an operator uses, so
this specification cannot say which existing control earns its place. Every
figure above counts data, not behaviour.

## 5. WP24 — the tokens the two pages share

**24.1 [MUST]** One stylesheet holds the tokens the desk needs and the rules the
brief card needs.
*Done:* `static/css/deskShared.css` loads in the desk and in the app, and the
brief card renders the same in both.
*Falsified by:* one rule for the card in a second file.
*Reason:* `style.css` is 41,421 lines. A desk that linked it would inherit
41,000 rules it never asked for, and the cascade onto a page nobody tested is
not knowable in advance.
*Open:* the owner has not chosen between this and a token block copied into the
desk. This is Claude's reading of what D55 needs.

**24.2 [MUST]** The desk drops its own palette and uses the shared tokens.
*Done:* `--ink`, `--line`, `--panel` no longer appear in
`itinerary_desk.html`, and the page renders in the Operations colours.
*Falsified by:* one desk rule that names a token the app does not define.

**24.3 [MUST]** The desk keeps its light and dark answer.
*Done:* `:root.light` from `style.css` reaches the shared file, so the desk is
readable in both.
*Falsified by:* a desk that renders dark text on a dark ground.

**24.4 [SHOULD]** The shared file states which page owns each rule.
*Done:* a comment per block naming the desk, the app, or both.

**24.5 [WONT]** A change to `offers_review.html`. It shares no link and no job
with the desk, and it can move later or never.

**24.6 [WONT]** A CSS framework. The page carries no build step.

## 6. WP25 — the list route sends a list

**25.1 [MUST]** `GET /api/itinerary/drafts` sends one row per draft, and no
sequence, no `SequenceCheck` and no run.
*Done:* the answer holds the draft id, the request id, the day count, a fault
and flag count, and whether a document exists.
*Falsified by:* a `sequences` key in the list answer.
*Reason:* the route sends 51,646 bytes to render one draft today.

**25.2 [MUST]** `GET /api/itinerary/drafts/{id}` stays the detail.
*Done:* the pane loads from it, and the list never carries what the pane shows.

**25.3 [MUST]** The list answer is smaller than 8 KB for the drafts on disk.
*Falsified by:* a measured answer above it.

**25.4 [MUST]** No caller of the fat answer is left reading a key that is gone.
*Done:* every reader of `sequences` from the list route reads the detail route
instead.
*Falsified by:* a page that renders an empty sequence where one exists.

**25.5 [SHOULD]** The list states how many drafts it holds, and the pane states
which one it read.

## 7. WP26 — the queue

**26.1 [MUST]** The queue is one list of every tour request.
*Done:* 43 rows, from `GET /api/itinerary/requests`.
*Falsified by:* a second list of the same things on the same page.

**26.2 [MUST]** A request that has a draft carries a mark.
*Done:* 9 rows of 43 carry it today.
*Falsified by:* a request with a draft that reads like one without.

**26.3 [MUST]** A draft that no request row matches appears under one filter
value.
*Done:* the Desk control's "draft with no request" shows the one on disk.
*Falsified by:* invariant 3.3.

**26.4 [MUST]** A row states the name, the reference, the status and the source.
*Done:* the longest name is 24 characters, so a 320 pixel column holds it.
*Falsified by:* a row whose name is cut.

**26.5 [MUST]** Choosing a row loads the detail and changes nothing else.
*Falsified by:* a choice that writes to a draft.

**26.6 [MUST]** The queue states how many rows the filters left, against the
total.
*Done:* "9 of 43".

**26.7 [WONT]** The `<select>` of drafts. One list replaces two.

**26.8 [WONT]** "Show ten more". A filter replaces a page size.

## 8. WP27 — the filter bar

**27.1 [MUST]** The bar carries the Operations controls: an Open preset, and
dropdowns for status, flags, source and operator.
*Done:* each dropdown counts its options against the pool that excludes its own
dimension, as `_matchingExcept` does.
*Falsified by:* a count that changes when its own dimension changes.

**27.2 [MUST]** A fifth control filters the desk's own state.
*Done:* "Desk" offers no draft, has a draft, has a run, has a document, and
draft with no request.
*Falsified by:* a desk state a reader cannot filter on.
*Reason:* the Operations bar cannot ask which requests have no draft, and that
is this page's own question.

**27.3 [MUST]** A search field reads the name, the email, the phone and the
operator.
*Done:* the same fields the Operations search reads.

**27.4 [MUST]** A spam control hides the 9 rows marked spam or suspected.
*Done:* 43 rows become 34.

**27.5 [MUST]** One press reaches the rows that need work.
*Done:* the Open preset leaves 1 of 44, and the spam control alone leaves 35.
*Falsified by:* a reader who must set two controls to see the New rows.
*Amended 2026-09-08:* this item said 9. Measured on the live worklist, 8 of
the 9 New rows carry the risk `confirmed-spam` and 1 does not, so "9 New" counted spam as
work. The queue hides spam by default, which is why one press answers 1.

**27.6 [MUST]** A clear control appears only when a filter is set.

**27.7 [SHOULD]** The filters survive a reload.
*Done:* the query string carries them, so a link carries a view.

**27.8 [MAY]** Saved views. Nothing measures a need for them yet.

**27.9 [WONT]** A filter on the next action date. It is set on 1 row of 43.

## 9. WP28 — the detail pane

**28.1 [MUST]** A strip of input, run and output sits above everything and does
not collapse.
*Done:* the input names the days, the travellers, the regions and the
screenshots. The run names the steps done, the time and the endpoints. The
output names the days delivered, the faults, the flags and the build control.
*Falsified by:* a strip that scrolls away.

**28.2 [MUST]** Every other block is a section a reader opens and closes.
*Done:* the layers, the brief, the candidates, the check, the feedback, the
machine notes and the rule books.
*Falsified by:* a block that cannot close.

**28.3 [MUST]** A section opens when its own content asks to be read.
*Done:* the check opens where a fault exists, which `checkBlock` already does.
The layers open where a step failed. The brief opens where it disagrees with
the request.
*Falsified by:* a fault that a reader must open a section to find.
*Open:* the owner has not chosen between this and a fixed list of open
sections. This is Claude's reading of what D53 and three readers need together.

**28.4 [MUST]** The pane states which request it holds.
*Falsified by:* a pane that reads as the previous request after a slow load.

**28.5 [MUST]** An empty pane says a request is not open, and says nothing else.

**28.6 [SHOULD]** The rule books move into a section of the pane.
*Falsified by:* a full width block below the two panes.

## 10. WP29 — the layers, and the prompts

**29.1 [MUST]** The layers section lists seven steps in the order they ran.
*Done:* read link, extract, brief, candidates, check, rank, review.
*Falsified by:* a step the section leaves out.

**29.2 [MUST]** Each step states its outcome, its milliseconds and its endpoint.
*Done:* a deterministic step states no endpoint, and a model step names the
host and the model.
*Falsified by:* a step that reached a model and names none.

**29.3 [MUST]** A step that did not run states why, on the surface.
*Done:* "the master switch is off" reads without a click.
*Falsified by:* an untested step that reads as a step that found nothing.

**29.4 [MUST]** A prompt and a raw answer open in a drawer.
*Done:* three steps carry 16,205 characters of prompt, and none of it renders
until a reader asks.
*Falsified by:* invariant 3.2.

**29.5 [MUST]** A second run is reachable, and the newest is shown first.
*Done:* a draft with six runs lists six.

**29.6 [SHOULD]** The section states the whole run time.
*Done:* 5.4 seconds for the measured run.

**29.7 [WONT]** A tree or a flame chart. Seven steps in one line each is the
whole structure.

## 11. WP30 — the brief card, once

**30.1 [MUST]** One file defines the brief card.
*Done:* `static/js/briefCard.js` renders from `brief_to_dict`, and both pages
load it.
*Falsified by:* invariant 3.4.

**30.2 [MUST]** The card depends on no page's own helpers.
*Done:* it carries its own escaping, because the desk and the app share no
globals.
*Falsified by:* a reference to a name the desk does not define.

**30.3 [MUST]** The card states what the brief filled and what it disagreed
with.
*Done:* "the request left party_size blank, and the conversation says 20", and
the disagreements the request won.

**30.4 [MUST]** The card names its source honestly.
*Done:* a brief written with no conversation says "the brief says", which
`_difference` already decides.

**30.5 [MUST]** The card states what the brief named and the request refused.
*Done:* the `refused` list renders.

**30.6 [SHOULD]** The card states the endpoint that wrote it.

## 12. WP31 — the Operations side

**31.1 [MUST]** The Operations modal renders the brief through the shared card.
*Done:* `_renderOfferBox` calls it, and the modal holds no brief markup of its
own.
*Falsified by:* a brief field in `operations.js`.

**31.2 [MUST]** The link to the desk carries the draft.
*Done:* `/itinerary?draft=<id>`, which the desk already reads.

**31.3 [MUST]** The two buttons stay in Operations.
*Done:* ws-03 G2 stands, and this phase moves no control.

**31.4 [WONT]** A change to what the buttons do.

## 13. This phase does not build

**WONT** Any change to the four layers, the checks, the candidates or the
binder. This is a view.

**WONT** A change to `offers_review.html`.

**WONT** A judged rule interface. Three routes still have no control.

**WONT** A model call from the desk. The buttons live in Operations.

**WONT** A framework, a build step or a package.

## 14. Measurements this phase must produce

| # | Measurement | Known today |
|---|---|---|
| 14.1 | Rows the Open preset leaves | 1 of 44. 8 of the 9 New rows are spam rows |
| 14.2 | The list route's answer size | 51,646 bytes now, under 8,192 after |
| 14.3 | Drafts reachable from the queue | 10 of 10, including the orphan |
| 14.4 | Prompt characters rendered without a click | 0 |
| 14.5 | Places that render a brief field | 1 |
| 14.6 | Desk rules naming a token the app does not define | 0 |

## 15. Risks that stand

**Five dropdowns serve a 43 row list**, and the operator dimension is blank on
17 of them. The owner kept the Operations bar whole and added a fifth control.
Nothing measures whether a reader opens any of them.

**One card in two pages couples two pages.** They deploy together, so the
coupling costs nothing today. A desk that ships apart from the app would carry
a file the app also needs.

**Nothing measures a reader.** Every figure in section 4 counts rows and bytes.
The three readers in D49 are the owner's statement, not a measurement, so a
layout that serves one badly will not show up in any number this phase produces.

**A section that opens itself can hide as much as it shows.** Item 28.3 opens a
section on its own content, and a reader who expects a fixed layout may read a
closed section as an empty one.

## 16. Open

**16.1** Item 24.1: a shared stylesheet against a token block copied into the
desk.

**16.2** Item 28.3: sections that open on their content against a fixed list.

**16.3** Whether the rule books stay on this page at all (item 28.6).

**16.4** Whether `offers_review.html` follows the desk into the app's tokens
later.
