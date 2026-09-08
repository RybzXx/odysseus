/* static/js/briefCard.js
 *
 * What the customer asked for, rendered the same on both pages (ws-03 D55).
 *
 * The Operations modal shows the brief so an operator can judge a proposal
 * before pressing build. The desk shows it so a reviewer can read what layer 1
 * took from the conversation. Two renderers would drift, and a reviewer who
 * read a different brief from the operator would be reading a different
 * request (invariant 3.4).
 *
 * This file depends on nothing either page defines. The desk and the app share
 * no globals, so the escaping is here rather than borrowed.
 *
 * Its input is `brief_to_dict` from services/itinerary/request_brief.py, over
 * the wire, unchanged.
 */
(function (root) {
  "use strict";

  /* Post: `value` as text no browser reads as markup.
   * Blame: a caller that inserts a brief field without this opens the page to
   * whatever a screenshot held (ws-03 D48). */
  function escapeText(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/[&<>"]/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function line(label, value) {
    if (value === null || value === undefined || value === "" ||
        (Array.isArray(value) && !value.length)) return "";
    const text = Array.isArray(value) ? value.join(", ") : value;
    return `<div class="brief-line"><strong>${escapeText(label)}:</strong> ` +
           `${escapeText(text)}</div>`;
  }

  function diffBlock(kind, heading, statements) {
    if (!statements.length) return "";
    const rows = statements
      .map((s) => `<div class="brief-diff">• ${escapeText(s)}</div>`).join("");
    return `<div class="brief-diffs ${kind}">
        <div class="brief-diffs-head">${escapeText(heading)}</div>${rows}
      </div>`;
  }

  /**
   * One brief as both pages render it.
   *
   * Pre:  `brief` is the object `brief_to_dict` produced, or null when layer 1
   *       did not run.
   * Post: HTML. A null brief renders one line saying layer 1 did not run,
   *       rather than nothing, because an empty card reads as a brief with no
   *       content.
   */
  function briefCardHtml(brief) {
    if (!brief) {
      return `<div class="brief-card"><div class="brief-empty">` +
             `No brief. Layer 1 did not run.</div></div>`;
    }

    const differences = brief.differences || [];
    const filled = differences.filter((d) => d.applied).map((d) => d.statement);
    const kept = differences.filter((d) => !d.applied).map((d) => d.statement);

    // A brief written with no conversation can only repeat the request, so the
    // card says so rather than letting the reader assume a screenshot was read.
    const unread = brief.read_the_conversation ? "" :
      `<div class="brief-unread">No screenshot was read for this brief.</div>`;

    const where = brief.where
      ? `<div class="brief-where">${escapeText(brief.where)}` +
        `${brief.at ? " · " + escapeText(brief.at) : ""}</div>`
      : "";

    return `<div class="brief-card">
        <div class="brief-summary">${escapeText(brief.summary || "(no summary)")}</div>
        ${line("Days", brief.day_count)}
        ${line("Travellers", brief.party_size)}
        ${line("Regions", brief.regions)}
        ${line("Places named", brief.must_see_sites)}
        ${line("Interests", brief.interests)}
        ${line("Start date", brief.start_date)}
        ${diffBlock("filled", "Filled from the conversation", filled)}
        ${diffBlock("kept", "Disagrees with the request", kept)}
        ${diffBlock("refused", "Refused", brief.refused || [])}
        ${unread}${where}
      </div>`;
  }

  /* Post: one line for a caller with no room for the card. */
  function briefHeadline(brief) {
    if (!brief) return "no brief";
    return brief.statement ||
      `${(brief.applied_count || 0)} field(s) filled, ` +
      `${(brief.contradiction_count || 0)} disagreement(s) kept`;
  }

  root.BriefCard = { html: briefCardHtml, headline: briefHeadline,
                     escape: escapeText };
})(window);
