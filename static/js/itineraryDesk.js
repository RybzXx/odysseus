/*
 * static/js/itineraryDesk.js
 *
 * The itinerary desk. Every Curated and Queue request is a pill across the top.
 * Clicking one opens it in the pane below: the request on the left, and two
 * proposed day-code sequences on the right, one from the model and one from the
 * rules, with a comment box.
 *
 * Ten pills at a time. The offers review page wrote 257 cards in one go and
 * locked a phone browser, and this list grows the same way.
 *
 * One request is open at a time, and the pane never moves. A comparison read
 * position by position needs somewhere steady to sit.
 *
 * In a file rather than a <script> block, because the app sends
 * `script-src 'self' 'nonce-…'` and a page served as a file carries no nonce.
 */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// The keys services/itinerary/normalizer.py reads for a curated request. These
// are the live web form's own key names, not sheet headers: a typed card here
// must reach the normalizer as the same payload a real request does, or it
// silently normalizes to the defaults and builds a trip nobody asked for.
//
// Regions separate on a comma. The vocabularies below are the ones the mapper
// knows. A word outside them is kept and matches no route, which the desk shows
// rather than hides.
const REQUEST_FIELDS = [
  ["name", "Client name", ""],
  ["email", "Email", ""],
  ["numberOfPeople", "Party size", "2"],
  ["tripDays", "Days", "8"],
  ["accommodation", "Hotel (3 star | 4 star | 5 star)", "4 star"],
  ["regions", "Regions (comma separated)", "central iraq, kurdistan"],
  ["travelDateMode", "Date mode (range | exact)", "range"],
  ["exactDate", "Exact date (YYYY-MM-DD)", ""],
  ["travelMonth", "Month", "April"],
  ["travelYear", "Year", "2026"],
  ["comments", "Comments", ""],
  ["dietaryNeeds", "Dietary needs", ""],
  ["heatWalkingComfort", "Mobility and pacing", ""],
];

// How many pills render at a time. Ten is what ws-03 WP6 asks for.
const PILL_BATCH = 10;

// The normalised fields worth putting beside the submitted record, and the raw
// keys each one can come from. A normalisation that silently falls back to a
// default built a 5-day trip from an 8-day request, and only both readings side
// by side make that visible.
//
// Two key names per field, because the curated form and the queue sheet name
// the same thing differently. Listing only one shape leaves the other's
// mismatches unmarked, which is how this pane first showed a party of two for a
// record that said one.
const NORMALIZED_FIELDS = [
  ["customer_name", "Name", ["name", "full_name"]],
  ["pax", "Party size", ["numberOfPeople", "number_of_people"]],
  ["day_count", "Days", ["tripDays", "trip_days"]],
  ["tour_type", "Tour type", []],
  ["hotel_tier", "Hotel tier", ["accommodation"]],
  ["vehicle_type", "Vehicle", ["transportation"]],
  ["requested_regions", "Regions", ["regions"]],
  ["travel_month", "Month", ["travelMonth"]],
  ["travel_year", "Year", ["travelYear"]],
  ["start_date", "Exact date", ["exactDate", "travel_date"]],
  ["special_notes", "Notes", []],
];

// What the data-entry team types for a column the submitter left blank. It is
// not a mismatch when the normalizer drops it.
const PLACEHOLDERS = new Set(["not known", "none", "n/a", "-", ""]);

let current = null;
let requests = [];
let shown = PILL_BATCH;

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 300)}`);
  return res.json();
}

function requestForm(row) {
  return `<h4>Request</h4>` + REQUEST_FIELDS.map(([key, label, hint]) =>
    `<div class="field"><label>${esc(label)}</label>
       <input type="text" data-key="${esc(key)}"
              value="${esc(row && row[key] !== undefined ? row[key] : "")}"
              placeholder="${esc(hint)}"></div>`).join("")
    + `<div class="bar"><button id="open-request" class="primary">Open and propose</button>
         <span class="msg note"></span></div>`;
}

function readForm(root) {
  const row = {};
  root.querySelectorAll("input[data-key]").forEach((input) => {
    row[input.dataset.key] = input.value;
  });
  return row;
}

// ── the request strip ────────────────────────────────────────────────────────

function pill(row) {
  const label = row.name || row.key;
  const doc = row.has_document ? `<span class="has-doc">doc</span>` : "";
  return `<button class="pill" data-key="${esc(row.key)}"
            aria-current="${current && current.request_id === row.key}"
            title="${esc((row.summary || []).join(" · "))}">
      <span class="dot ${esc(row.source)}"></span>
      <span class="who">${esc(label)}</span>
      <span class="st">${esc(row.status || "New")}</span>${doc}
    </button>`;
}

function renderPills() {
  const strip = $("pills");
  const batch = requests.slice(0, shown);
  strip.innerHTML = batch.length
    ? batch.map(pill).join("")
    : `<span class="note">no Curated or Queue requests</span>`;
  $("pill-count").textContent =
    `${batch.length} of ${requests.length} request(s)`;
  $("pill-more").style.display = shown < requests.length ? "" : "none";
  strip.querySelectorAll(".pill").forEach((button) =>
    button.addEventListener("click", () => openWorklistRequest(button.dataset.key)));
}

async function loadRequests() {
  try {
    const data = await api("/api/itinerary/requests");
    requests = data.requests || [];
    $("pill-error").textContent = "";
  } catch (e) {
    // The desk keeps no copy of the worklist, so there is nothing to fall back
    // on. Say so rather than showing an empty strip that reads as "no work".
    requests = [];
    $("pill-error").innerHTML =
      `<span class="err">the worklist did not answer: ${esc(e.message)}</span>`;
  }
  renderPills();
}

async function openWorklistRequest(key) {
  $("pill-error").textContent = "";
  $("answer-pane").innerHTML = `<div class="card"><div class="empty">reading ${esc(key)}…</div></div>`;
  try {
    renderDraft(await api("/api/itinerary/drafts/from-request", {
      method: "POST", body: JSON.stringify({ key }),
    }));
    await loadDrafts();
  } catch (e) {
    $("pill-error").innerHTML = `<span class="err">${esc(e.message)}</span>`;
    $("answer-pane").innerHTML =
      `<div class="card"><div class="empty">that request did not open</div></div>`;
  }
  renderPills();
}

// ── the two rule books ───────────────────────────────────────────────────────
//
// Rendered apart, and labelled apart. A counted rule says "199 of 289" and
// anyone holding the corpus can check it. A judged rule says what a reviewer
// knows. A reader who cannot tell them apart cannot weigh either.

const FAMILY_LABELS = {
  first_night: "First night", last_night: "Last night",
  move: "Move", trip_length: "Trip length",
};

function countedRule(rule) {
  return `<div class="rule">
    <div class="stat">${esc(rule.statement)}</div>
    <div class="n">${rule.count} of ${rule.total} · ${(rule.share * 100).toFixed(1)}%`
    + (rule.synced_at ? " · in the sheet" : " · not in the sheet yet") + `</div>
  </div>`;
}

function judgedRule(rule) {
  const verdict = rule.corpus_verdict || "silent";
  const evidence = rule.corpus_evidence
    ? `<div class="n">the corpus ${esc(verdict)}: ${esc(rule.corpus_evidence)}</div>`
    : `<div class="n">the corpus is silent on this</div>`;
  return `<div class="rule ${esc(verdict)}">
    <div class="stat">${esc(rule.statement)}</div>
    ${evidence}
    <div class="n">from a comment: ${esc(rule.comment_text || "")}</div>
  </div>`;
}

function renderRuleBooks(data) {
  const counted = data.counted || { summary: {}, rules: [] };
  const judged = data.judged || { summary: {}, rules: [] };
  const byFamily = counted.summary.families || {};

  const countedBody = Object.keys(FAMILY_LABELS)
    .filter((family) => byFamily[family])
    .map((family) => `<details class="book">
        <summary>${esc(FAMILY_LABELS[family])} — ${byFamily[family]}</summary>
        ${counted.rules.filter((r) => r.family === family).map(countedRule).join("")}
      </details>`).join("");

  $("rule-books").innerHTML =
    `<h4>Rule books</h4>
     <details class="book" open>
       <summary>Counted — ${counted.summary.count || 0} rule(s),
         ${counted.summary.unsynced || 0} not in the sheet</summary>
       <div class="note">Each one is a count over the sent offers. Check any of them
         against the corpus.</div>
       ${countedBody || '<div class="note">the counted book is empty</div>'}
     </details>
     <details class="book">
       <summary>Judged — ${judged.summary.count || 0} rule(s)</summary>
       <div class="note">Each one came from a comment. The corpus verdict beside it
         reports and never refuses.</div>
       ${judged.rules.map(judgedRule).join("")
         || '<div class="note">the judged book is empty</div>'}
     </details>`;
}

async function loadRuleBooks() {
  try {
    renderRuleBooks(await api("/api/itinerary/rules"));
  } catch (e) {
    $("rule-books").innerHTML =
      `<h4>Rule books</h4><div class="err">${esc(e.message)}</div>`;
  }
}

// ── what the proposers actually read ─────────────────────────────────────────

function normalizedBlock(draft) {
  const normalized = draft.normalized || {};
  if (normalized.error) {
    return `<div class="warn">${esc(normalized.error)}</div>`;
  }
  const raw = draft.request_row || {};
  const rows = NORMALIZED_FIELDS.map(([key, label, rawKeys]) => {
    const value = Array.isArray(normalized[key])
      ? normalized[key].join(", ") : normalized[key];
    if (value === null || value === undefined || value === "") return "";
    // A raw value the normalizer did not carry through is what a silent
    // fallback looks like. Mark it; do not resolve it here.
    const rawKey = rawKeys.find((k) => raw[k] !== undefined && String(raw[k]).trim() !== "");
    const submitted = rawKey === undefined ? undefined : String(raw[rawKey]).trim();
    const differs = submitted !== undefined
      && !PLACEHOLDERS.has(submitted.toLowerCase())
      && !String(value).trim().toLowerCase().includes(submitted.toLowerCase())
      && !submitted.toLowerCase().includes(String(value).trim().toLowerCase());
    return `<dt>${esc(label)}</dt><dd class="${differs ? "differs" : ""}">${esc(value)}`
      + (differs ? ` <span class="note">(submitted: ${esc(submitted)})</span>` : "")
      + `</dd>`;
  }).join("");
  return `<h4>As the proposers read it</h4><dl class="kv">${rows}</dl>`;
}

// The two answers are compared position by position. A difference is marked and
// never resolved here: neither proposer is authoritative.
function sequenceBlock(sequence, agreement, which) {
  if (!sequence) {
    return `<div class="note">the ${which} proposer has not answered yet</div>`;
  }
  const marks = agreement.positions || [];
  const chips = (sequence.day_codes || []).map((code, i) => {
    const mark = marks[i] === "same" ? "same"
      : marks[i] === "differ" ? "differ" : "only";
    return `<span class="code ${mark}">${i + 1}. ${esc(code)}</span>`;
  }).join("");
  const rejected = (sequence.rejected_codes || []).length
    ? `<div class="warn">Not in the catalogue, so dropped:
         ${esc(sequence.rejected_codes.join(", "))}</div>`
    : "";
  const stamp = sequence.model
    ? `<span class="note">${esc(sequence.model)} · ${esc(sequence.proposed_at || "")}</span>`
    : `<span class="note">${esc(sequence.proposed_at || "")}</span>`;
  return `
    <div class="row"><span class="tag ${which}">${which}</span>
      <span class="note">${(sequence.day_codes || []).length} days</span>
      <span class="grow"></span>${stamp}</div>
    <div class="seq">${chips || '<span class="note">no codes</span>'}</div>
    ${sequence.note ? `<div class="note">${esc(sequence.note)}</div>` : ""}
    ${rejected}
    <div class="bar"><button class="generate" data-source="${which}">Generate from this</button></div>`;
}

// Every comment, and every model answer, oldest first. A comment is shown even
// when no answer followed it: with the proposer off it is the whole record, and
// it is what the judged rule book reads.
function thread(draft) {
  const turns = (draft.comments || []).map((c) =>
    `<div class="turn"><strong>You</strong>
       <span class="note">${esc(c.at || "")} · ${esc(c.rule_state || "new")}</span>
       <div class="note">${esc(c.text)}</div></div>`);
  (draft.sequences || []).forEach((s) => {
    if (s.source !== "model") return;
    turns.push(`<div class="turn"><strong>Model</strong>
      <div class="note">${esc((s.day_codes || []).join(" → ")) || "no codes"}</div></div>`);
  });
  return turns.length ? `<div class="thread">${turns.join("")}</div>` : "";
}

function renderDraft(draft) {
  current = draft;
  const agreement = draft.agreement || { positions: [] };
  const latest = {};
  draft.sequences.forEach((s) => { latest[s.source] = s; });

  const submitted = Object.entries(draft.request_row || {})
    .filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== "")
    .map(([k, v]) =>
      `<div class="note"><strong>${esc(k)}:</strong> ${esc(
        typeof v === "object" ? JSON.stringify(v) : v)}</div>`)
    .join("");

  $("request-card").innerHTML =
    `<h4>Request ${esc(draft.request_id || draft.draft_id)}</h4>`
    + `<div class="note">${esc(draft.draft_id)} · ${esc(draft.origin)}</div>`
    + (draft.parse_warnings || []).map((w) => `<div class="warn">${esc(w)}</div>`).join("")
    + `<div style="margin-top:12px">${normalizedBlock(draft)}</div>`
    + `<h4 style="margin-top:16px">As submitted</h4>`
    + `<div class="thread">${submitted || '<div class="note">nothing</div>'}</div>`
    + `<div class="bar"><button id="back-to-form">New request</button></div>`;

  $("answer-pane").innerHTML =
    `<div class="card">
       <h4>Proposed sequences</h4>
       ${agreement.same
          ? `<div class="note">Both proposers agree.</div>`
          : `<div class="note">The two answers differ. Neither decides; you do.</div>`}
       <div style="margin-top:12px">${sequenceBlock(latest.model, agreement, "model")}</div>
       <hr style="border:none;border-top:1px solid var(--line);margin:16px 0">
       <div>${sequenceBlock(latest.rules, agreement, "rules")}</div>
     </div>
     <div class="card">
       <h4>Feedback</h4>
       <div class="note">A comment asks the model to answer again. The rules answer does not move.</div>
       ${thread(draft)}
       <div class="field" style="margin-top:10px">
         <textarea id="comment" placeholder="e.g. keep the first three days but end in Erbil"></textarea>
       </div>
       <div class="bar">
         <button id="save-comment">Save the comment</button>
         <button id="ask-model" class="primary"
                 ${draft.model_proposals_enabled ? "" : "disabled"}>
           ${latest.model ? "Ask again" : "Ask the model"}</button>
         <span class="msg note" id="model-msg">${draft.model_proposals_enabled ? ""
            : "the model proposer is off; the comment is still saved"}</span>
       </div>
     </div>
     ${draft.doc_url
        ? `<div class="card"><h4>Document</h4>
             <div class="note">generated from the ${esc(draft.generated_from)} sequence</div>
             <a href="${esc(draft.doc_url)}" target="_blank" rel="noopener">${esc(draft.doc_url)}</a>
           </div>`
        : ""}`;

  $("back-to-form")?.addEventListener("click", showForm);
  $("save-comment")?.addEventListener("click", saveComment);
  $("ask-model")?.addEventListener("click", askModel);
  document.querySelectorAll(".generate").forEach((b) =>
    b.addEventListener("click", () => generate(b.dataset.source)));
}

function showForm(row) {
  current = null;
  $("request-card").innerHTML = requestForm(row && row.Customize ? row : null);
  $("answer-pane").innerHTML =
    `<div class="card"><div class="empty">open a request to see a sequence</div></div>`;
  $("open-request").addEventListener("click", openRequest);
}

async function openRequest() {
  const msg = $("request-card").querySelector(".msg");
  const button = $("open-request");
  button.disabled = true;
  msg.textContent = "reading the request and running the rules…";
  try {
    const draft = await api("/api/itinerary/drafts", {
      method: "POST",
      body: JSON.stringify({ row: readForm($("request-card")), origin: "typed" }),
    });
    renderDraft(draft);
    await loadDrafts();
  } catch (e) {
    button.disabled = false;
    msg.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

async function saveComment() {
  const msg = $("model-msg");
  const button = $("save-comment");
  const comment = $("comment").value.trim();
  if (!comment) { msg.textContent = "a comment cannot be empty"; return; }
  button.disabled = true;
  msg.textContent = "saving…";
  try {
    renderDraft(await api(
      `/api/itinerary/drafts/${encodeURIComponent(current.draft_id)}/comment`,
      { method: "POST", body: JSON.stringify({ text: comment }) }));
  } catch (e) {
    button.disabled = false;
    msg.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

async function askModel() {
  const msg = $("model-msg");
  const button = $("ask-model");
  const comment = $("comment").value.trim();
  button.disabled = true;
  msg.textContent = "asking the model…";
  try {
    const draft = await api(
      `/api/itinerary/drafts/${encodeURIComponent(current.draft_id)}/model`,
      { method: "POST", body: JSON.stringify({ text: comment }) });
    renderDraft(draft);
  } catch (e) {
    button.disabled = false;
    msg.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

async function generate(source) {
  const msg = $("model-msg");
  msg.textContent = `generating from the ${source} sequence…`;
  try {
    const result = await api(
      `/api/itinerary/drafts/${encodeURIComponent(current.draft_id)}/generate`,
      { method: "POST", body: JSON.stringify({ source }) });
    if (!result.ok) {
      msg.innerHTML = `<span class="err">${esc((result.errors || []).join("; "))}</span>`;
      return;
    }
    renderDraft(result);
  } catch (e) {
    msg.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

async function loadDrafts() {
  try {
    const data = await api("/api/itinerary/drafts");
    const list = $("draft-list");
    list.innerHTML = `<option value="">${data.count} open request(s)</option>`
      + data.drafts.map((d) =>
          `<option value="${esc(d.draft_id)}">${esc(d.request_id || d.draft_id)}
             — ${esc((d.request_row || {}).tripDays || "?")} days</option>`).join("");
    $("summary").textContent = `${data.count} request(s) on the desk`;
  } catch (e) {
    $("summary").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

$("draft-list").addEventListener("change", async (ev) => {
  if (!ev.target.value) return;
  renderDraft(await api(`/api/itinerary/drafts/${encodeURIComponent(ev.target.value)}`));
});

$("new-request").addEventListener("click", () => { showForm(); renderPills(); });

$("pill-more").addEventListener("click", () => {
  shown += PILL_BATCH;
  renderPills();
});

(async function start() {
  showForm();
  await Promise.all([loadDrafts(), loadRequests(), loadRuleBooks()]);
  try {
    const codes = await api("/api/itinerary/templates");
    $("codes-note").textContent = `${codes.count} active day codes`;
  } catch (e) {
    $("codes-note").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
})();
