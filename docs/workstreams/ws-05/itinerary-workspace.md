# Itinerary focused workspace

The user selected design A on September 20, 2026.
The workspace gives phone and desktop navigation equal priority.
The implementation changes presentation and browser state only.
The server still owns calculation, readiness validation, and document generation.

## Specification coverage

| Requirement | Implementation |
| --- | --- |
| 1.1-1.2 | Four workspace views. No backend calculation or permission changes. |
| 2.1 | Overview, Request, Rules and sources, Activity. |
| 2.2 | Two panes above 900 CSS pixels. One pane at or below 900 pixels. |
| 2.3 | Back to requests preserves search, filters, selection, and queue scroll. |
| 2.4 | Draft, view, pane, and filters use URL state with Back and Forward support. |
| 3.1 | Overview contains request summary, day plan, accommodation, blockers, and actions. |
| 3.2 | Request retains submitted fields, interpreted fields, discrepancies, warnings, and conversation access. |
| 3.3 | Rules and sources retains checks, plan evidence, reference records, and rule books. |
| 3.4 | Activity retains every earlier sequence, run, comment, machine note, and worklist control. |
| 3.5 | Overview links to comments. Empty supporting sections do not precede the itinerary. |
| 3.6 | Existing information functions remain in use. History includes all earlier sequences instead of only one per source. |
| 4.1 | Day titles use the existing catalogue endpoint. Unknown places stay unknown. |
| 4.2 | Readiness includes stale results and document validation. Zero faults alone cannot enable generation. |
| 4.3 | Blockers link to a day, request details, or current checks. Ownership labels follow explicit message evidence. |
| 4.4 | An existing document has a separate label that explains recalculation does not update it. |
| 4.5 | Only the current Overview result has a generation action. Earlier results are read-only. |
| 4.6 | No invented quote amount or duplicate price calculation. |
| 5.1 | Per-draft in-memory state retains comments, view, and expanded evidence. Navigation responses cannot overwrite another request. |
| 5.2 | Native navigation buttons, focus targets, hidden panels, labelled fields, and status/error announcements. |
| 5.3 | Responsive content and 44-pixel button targets. State labels accompany colour. |

## Validation

Ten JavaScript tests passed.
Seventy-seven focused Python tests passed.
The synthetic browser fixture contains ready, blocked, stale, empty, failed, document-existing, and 17-day requests.
All seven requests produced the expected readiness and document-action states.
Tests did not create customer documents or send messages.

Browser measurements at 320, 390, 900, and 1280 CSS pixels found no page-wide horizontal overflow.
The selected request title appeared at 174 pixels at width 320 and 135 pixels at width 390.
The previous page placed the selected request approximately 3057 pixels below the top at width 390.
The queue hides in the compact workspace and appears beside it above 900 pixels.
Overview had no visible button smaller than 44 pixels in either dimension at the four tested widths.

Browser checks covered unsaved comments during recalculation and request switching, successful comment save, and recoverable comment failure.
The recalculation failure retained the current itinerary and restored its action.
Back and Forward restored a filtered phone list and selected request.
The test inspected direct day-evidence navigation and queued-change conflict handling.
These checks cover representative paths, not every possible operator interaction.

The pre-release phone backup is `odysseus-itinerary-backup-20260920T142707Z`.
Its database integrity check returned `ok`.
It contains 69 files, 21 projects, 64 tasks, 36 sessions, and 14 schedules.
Release acceptance must compare these records after deployment.
