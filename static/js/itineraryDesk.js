/*
 * static/js/itineraryDesk.js
 *
 * The itinerary desk. The request sits on the left. Two proposed day-code
 * sequences sit on the right, one from the model and one from the rules, with
 * a comment box that asks the model to answer again.
 *
 * In a file rather than a <script> block, because the app sends
 * `script-src 'self' 'nonce-…'` and a page served as a file carries no nonce.
 */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// The columns normalize_row reads. Multi-value cells are pipe separated, and
// the vocabularies are fixed, so the page states them rather than letting a
// typed value fall silently to a default.
const REQUEST_FIELDS = [
  ["Customize", "Request id", "cr-0001"],
  ["name", "Client name", ""],
  ["pax", "Party size", "2"],
  ["days", "Days", "8"],
  ["type", "Tour type", "individual"],
  ["hotel", "Hotel", "4_star"],
  ["transportation", "Transport", "suv"],
  ["regions", "Regions (pipe separated)", "central iraq & middle euphrates | iraqi kurdistan"],
  ["interests", "Interests (pipe separated)", "history | food"],
  ["range/exact", "Date mode", "range"],
  ["exact date", "Exact date", ""],
  ["month", "Month", "April"],
  ["year", "Year", "2026"],
  ["extra comments", "Comments", ""],
];

let current = null;

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

function thread(draft) {
  const turns = [];
  draft.sequences.forEach((s) => {
    if (s.in_reply_to) {
      turns.push(`<div class="turn"><strong>You</strong>
        <div class="note">${esc(s.in_reply_to)}</div></div>`);
    }
    if (s.source === "model") {
      turns.push(`<div class="turn"><strong>Model</strong>
        <div class="note">${esc((s.day_codes || []).join(" → ")) || "no codes"}</div></div>`);
    }
  });
  return turns.length ? `<div class="thread">${turns.join("")}</div>` : "";
}

function renderDraft(draft) {
  current = draft;
  const agreement = draft.agreement || { positions: [] };
  const latest = {};
  draft.sequences.forEach((s) => { latest[s.source] = s; });

  $("request-card").innerHTML =
    `<h4>Request ${esc(draft.request_id || draft.draft_id)}</h4>`
    + `<div class="note">${esc(draft.draft_id)} · ${esc(draft.origin)}</div>`
    + (draft.parse_warnings || []).map((w) => `<div class="warn">${esc(w)}</div>`).join("")
    + `<div class="thread">`
    + REQUEST_FIELDS.filter(([k]) => (draft.request_row || {})[k])
        .map(([k, label]) =>
          `<div class="note"><strong>${esc(label)}:</strong> ${esc(draft.request_row[k])}</div>`)
        .join("")
    + `</div>`
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
         <button id="ask-model" class="primary">${latest.model ? "Ask again" : "Ask the model"}</button>
         <span class="msg note" id="model-msg"></span>
       </div>
     </div>
     ${draft.doc_url
        ? `<div class="card"><h4>Document</h4>
             <div class="note">generated from the ${esc(draft.generated_from)} sequence</div>
             <a href="${esc(draft.doc_url)}" target="_blank" rel="noopener">${esc(draft.doc_url)}</a>
           </div>`
        : ""}`;

  $("back-to-form")?.addEventListener("click", showForm);
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
             — ${esc((d.request_row || {}).days || "?")} days</option>`).join("");
    $("summary").textContent = `${data.count} request(s) on the desk`;
  } catch (e) {
    $("summary").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

$("draft-list").addEventListener("change", async (ev) => {
  if (!ev.target.value) return;
  renderDraft(await api(`/api/itinerary/drafts/${encodeURIComponent(ev.target.value)}`));
});

$("new-request").addEventListener("click", () => showForm());

(async function start() {
  showForm();
  await loadDrafts();
  try {
    const codes = await api("/api/itinerary/templates");
    $("codes-note").textContent = `${codes.count} active day codes`;
  } catch (e) {
    $("codes-note").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
})();
