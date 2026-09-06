# ws-03 phase three — the desk, the rule books, and the mail intake

Written 2026-09-06. This is the specification for the work that follows the
merge and the rule counter. Read `handover.md` first for the state it starts
from.

## 0. Numbering

This phase keeps the handover's WP numbers. The handover defines WP3 to WP7. WP8
and WP9 are new, and WP10 is new.

A numbering collision exists and is not resolved here. `spec.md` uses WP1 to WP5
for a different set: Catalogue, Retrieval index, Generation, Human loop, and
Cross-cutting. A reader who opens `spec.md` to find WP6 does not find it.

Two of the owner's requests were already scoped. The pill list is the handover's
WP6. The rules book is WP4. This phase changes their content, not their number.

## 1. Decisions

| # | Decision |
|---|---|
| D14 | The desk reads the Operations worklist. It keeps no request store |
| D15 | A pull never generates. The desk shows a request. A human starts a generation |
| D16 | Two rule books this phase, one counted and one judged. The merge is a later decision |
| D17 | No call reaches `gemma4:31b-cloud` this phase. Claude does the wording and the rule drafting, in session |
| D18 | A comment drafts a rule |
| D19 | The mail window is eight months |
| D20 | The assembly reads the headers first. Quotes fill the gaps |
| D21 | Two reads answer independently. A grader compares them position by position |
| D22 | The thread comes from inside the sent message. There is no INBOX walk |
| D23 | The desk shows a pill row in batches of ten, above one detail pane that stays in place. One request is open at a time |
| D24 | A judged rule carries the comment, the sequence it corrected, and a corpus verdict. The verdict reports and never refuses |
| D25 | A setting gates the desk's model route. It is off by default |
| D26 | Each comment carries a `rule_state`. An export route reads it |
| D27 | A grader scores both reads against the sent offer. The model states what it got wrong. The human states why |

## 2. Invariants

**2.1 [LOCKED]** Invariants 1.1 to 1.9 in `spec.md` bind unchanged.

**2.2 [LOCKED]** Nothing enforces invariant 1.9 today. D17 and D25 hold
it. No chokepoint and no test exist. The endpoint record for `182e58cc` says
`local` while the daemon relays.
*Falsified by:* one model call that carries enquiry text or mail text while D17
stands.

**2.3 [LOCKED]** No mail text and no enquiry text reaches a network endpoint
this phase.
*Done:* every model reading in this phase is a session activity. No new
`source: "model"` sequence names a remote endpoint.
*Falsified by:* one new sequence with a filled `endpoint` field.

**2.4 [LOCKED]** The desk reads Supabase. It never writes to Supabase.
*Done:* every worklist call from the desk is a GET.
*Falsified by:* one `POST /api/operations/stage` from a desk code path.

## 3. Measured facts this spec stands on

This session measured each figure on 2026-09-06.

| Fact | Value |
|---|---|
| Offers in the corpus | 335, sent between 2024-08-25 and 2026-09-03 |
| Offers in the eight-month window | 80 |
| Of those, subjects that start `Re:` | 45, which is 56 percent |
| Sent Mail rows indexed | 139, of which 90 carry thread headers |
| INBOX rows indexed | 278, of which 22 carry thread headers |
| INBOX index window | 2026-07-31 forward only |
| Rules the counter finds | 39, over 289 offers |

The sent side carries the thread headers. The inbound side does not. D20 works
from the sent side and would fail from the inbound side.

## 4. WP6 — the desk page

**6.1 [MUST]** The desk pulls Curated and Queue requests from
`GET /api/operations`. It applies no status constraint.
*Done:* a request with status `Replied` and one with status `Confirmed` both
appear.
*Falsified by:* a request that `/operations` holds and the desk does not show.

**6.2 [MUST]** Pills render in batches of ten.
*Done:* eleven requests render ten pills and a control for the rest.
*Falsified by:* every request rendered at one time.

**6.3 [MUST]** One detail pane sits below the pill row and stays in place. One request is
open at a time.
*Done:* a second pill replaces the pane's content. The pill row does not move.
*Falsified by:* the pane's position that changes between two pills.

**6.4 [MUST]** The pane shows the normalised request beside the raw record.
*Falsified by:* a normalisation that replaces a typed value in silence.

**6.5 [MUST]** A generation runs only when a human clicks.
*Falsified by:* one `doc_url` that the desk sets with no click.

**6.6 [MUST]** The comment box writes to the draft's `comments`, with
`rule_state` set to `new`.
*Done:* a comment survives a reload with its time and its state.

**6.7 [MUST]** A setting gates the model route. The setting is off by default.
*Done:* with the setting off, the route refuses and names D17. No request
reaches an endpoint.
*Falsified by:* a model sequence that appears while the setting is off.

**6.8 [MAY]** The rules book renders beside the desk. It expands by family.

**6.9 [WONT]** A request store on the desk side.

## 5. WP4a — the counted rule book

**5.1 [MUST]** The counter's output persists to `data/ai_rules/counted/`. One
file holds one rule, with WP4's eleven fields.
*Done:* a second run over an unchanged corpus writes the same eleven values.
*Falsified by:* two runs over one corpus that produce different rule ids.

**5.2 [MUST]** Each record carries `synced_at` and the hash at the last sync.
*Done:* a record that was never synced reads `synced_at: null`.
*Falsified by:* an unsynced record that carries a sync time.

**5.3 [MUST]** A rule states its count and its denominator.
*Done:* every record answers "n of t".
*Falsified by:* a counted rule with no denominator.

**5.4 [SHOULD]** The book expands by family: first night, last night, move, and
trip length.

## 6. WP4b — the judged rule book

**6b.1 [MUST]** The store is `data/ai_rules/judged/`, separate from `counted/`.
*Falsified by:* one file that both readers read.

**6b.2 [MUST]** Each judged rule carries the comment, the corrected sequence,
and a corpus verdict of `agrees`, `disagrees` or `silent`.
*Done:* the book stores a rule the counter contradicts, and marks it. The book never refuses one.
*Falsified by:* a rule whose corpus verdict is absent rather than `silent`.

**6b.3 [MUST]** `GET /api/itinerary/comments?rule_state=new` returns the
comments that wait for a rule.
*Done:* a comment that drafted a rule no longer appears.
*Falsified by:* one comment that drafts two rules.

**6b.4 [MUST]** Claude drafts. A human accepts.
*Falsified by:* a judged rule with no recorded acceptance.

**6b.5 [WONT]** A merge of the two books this phase.

## 7. WP8 — the eight-month set

**8.1 [MUST]** The set comes from `data/offer_corpus`, filtered on `sent_at`.
*Done:* a cutoff of 2026-01-06 gives 80 offers.
*Falsified by:* a count that moves while the corpus does not.

**8.2 [WONT]** Organiser-based request detection. The live sample was mostly
marketing, and sent-only removes inbound marketing.

**8.3 [WONT]** A wider `email_message_index`. The corpus already spans 24
months.

**8.4 [WONT]** Hand-labelling of matches as requests. Every corpus record is an
offer by construction.

## 8. WP9 — the thread inside the sent message

**9.1 [MUST]** The Sent-folder walk captures the message body beside the
attachment.
*Done:* every record in the window holds `body.txt` and `body.html`. An empty
file records a message with no body.
*Falsified by:* a record with an attachment and no body file.

**9.2 [MUST]** Invariant 1.1 holds. The walk never writes `source.<ext>`.
*Done:* every `source.<ext>` keeps its size and its modification time.
*Falsified by:* one changed source byte.

**9.3 [MUST]** The record gains `in_reply_to` and `references`.
*Done:* all 80 records in the window carry both fields, empty or filled.
*Falsified by:* a field that is absent rather than empty.

**9.4 [MUST]** `parse_thread` runs over the captured body.
*Done:* an offer whose subject starts `Re:` gives one earlier turn or more.
*Falsified by:* a `Re:` offer that gives no turn, with no reason recorded.
The expected floor is 45 of the 80.

**9.5 [MUST]** Each turn carries `quote` or `header`. A turn that both methods
find appears one time.
*Falsified by:* one exchange rendered two times.

**9.6 [MUST]** The run names an offer whose thread does not recover.
*Done:* the run reports recovered against not recovered. The 35 offers that do
not start `Re:`.
*Falsified by:* a run that reports successes with no denominator.

**9.7 [WONT]** An INBOX walk.

## 9. WP10 — grade, then critique

**10.1 [MUST]** Read one takes the first inbound turn alone.

**10.2 [MUST]** Read two takes every turn before the sent offer.

**10.3 [MUST]** Neither read sees the sent offer or its attachment.
*Done:* the material for both reads holds no string from `text.txt`.
*Falsified by:* a day-code sequence that matches the offer by construction.

**10.4 [MUST]** A grader scores both reads against the offer's own day sequence,
position by position.
*Done:* each read gives a verdict for each position, and a total.
*Falsified by:* a grade that is one number with no positions.

**10.5 [MUST]** The model states what it got wrong, position by position.
*Falsified by:* a wrong position with no statement.

**10.6 [MUST]** The human states why it was wrong. That statement is a comment.
*Done:* the correction lands on the draft's `comments` with `rule_state` set to
`new`.
*Falsified by:* a correction that lands where WP4b cannot read it.

**10.7 [MUST]** This phase runs WP10 as a session activity, not as code.
*Falsified by:* a new `source: "model"` sequence with a filled `endpoint`.

**10.8 [SHOULD]** The grader scores the two reads apart, so the thread's value is
measurable.

## 10. Packages this phase does not build

**WP3 [WONT]** Model wording of rules. D17 moves it to Claude, in session.

**WP5 [WONT]** Two-way `AIRules` sync. It needs one settled book, and D16 leaves
two.

**WP7 [SHOULD, deferred]** The first run of ten offers and ten itineraries. It
follows WP6.

## 11. Measurements this phase must produce

| # | Measurement | State |
|---|---|---|
| 11.1 | Offers in the eight-month window | 80, measured |
| 11.2 | Subjects that start `Re:` | 45, measured |
| 11.3 | Sent rows with thread headers | 90 of 139, measured |
| 11.4 | Bodies captured, and threads recovered from them | unknown, WP9 gives it |
| 11.5 | Read one's grade against read two's | unknown, WP10 gives it |
| 11.6 | Judged rules gained, and how many the corpus contradicts | unknown, WP4b gives it |
| 11.7 | Desk requests by source and status | unknown, never counted |

## 12. Risks that stand

Invariant 1.9 stays unenforced. D17 and D25 hold it, and a setting is not a
chokepoint.

WP9 needs a new walk over the Sent folder. The first walk kept attachments and
discarded bodies, so about 80 messages must be read again.

The 35 offers that do not start `Re:` have no explanation. Item 9.6 requires
them accounted for. Nothing predicts what they are.
