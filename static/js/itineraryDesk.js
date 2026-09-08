/* static/js/itineraryDesk.js
 *
 * The itinerary desk: a queue on the left, one request on the right.
 *
 * The queue holds every tour request and a filter bar narrows it. The detail
 * pane holds one: what went in, what each layer did, and what came out
 * (ws-03 D49 to D53).
 *
 * Both buttons that start work live in the Operations modal (ws-03 G2). This
 * page reads, and it generates a document from a sequence a human chose.
 *
 * A prompt never renders until a reader asks for it. Three steps carry 16,205
 * characters of prompt against under 10,000 bytes of everything else, measured
 * 2026-09-08 (ws-03 D56, invariant 3.2).
 */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// The keys services/itinerary/normalizer.py reads for a curated request. A
// typed card must reach the normalizer as the payload a real request does, or
// it normalizes to the defaults and builds a trip nobody asked for.
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

// The normalised fields worth putting beside the submitted record. A silent
// fallback built a 5-day trip from an 8-day request, and only both readings
// side by side make that visible.
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

const PLACEHOLDERS = new Set(["not known", "none", "n/a", "-", ""]);

// What a status means for work. The Open preset is these, and it leaves 9 of
// 43 rows, measured 2026-09-08 (ws-03 item 27.5).
const OPEN_STATUSES = ["New", "In Progress", "Awaiting Reply"];

// The desk's own axis, which the Operations bar has no dropdown for. A queue
// that could not ask "which requests have no draft yet" could not ask this
// page's own question (ws-03 item 27.2).
const DESK_STATES = [
  ["no-draft", "No draft yet"],
  ["has-draft", "Has a draft"],
  ["has-run", "Has a run"],
  ["has-document", "Has a document"],
  ["orphan", "Draft with no request"],
];

let current = null;          // the detail pane's draft, or null
let currentRow = null;       // the worklist row it belongs to, for staging
let lastBuild = null;        // the newest generate answer, for the reply drafts
let stagedRows = [];         // what is queued and not yet sent
let requests = [];           // every worklist request
let draftRows = [];          // the light list from GET /drafts
let draftByKey = new Map();  // request_id -> draft row
let openDropdown = null;     // which filter panel is open, or null
let closeDropdownHandler = null;

const filters = {
  status: new Set(), flags: new Set(), source: new Set(),
  operator: new Set(), desk: new Set(), search: "", spam: false,
};

const UNASSIGNED = "\0none";

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 300)}`);
  return res.json();
}

/* ── the queue's rows ─────────────────────────────────────────────────────── */

/**
 * Post: every row the queue can show, requests first, then every draft that no
 *       request row matches.
 *
 * One list keyed by request (ws-03 D50). A draft whose request row is gone
 * still has to be reachable, or work already done becomes invisible
 * (invariant 3.3).
 *
 * A draft carries no request id at all when it was typed and named nothing,
 * and `open_draft` produces exactly that. Keying the orphan test on a truthy
 * request id left one such draft in no row on 2026-09-08: the header counted
 * 11 drafts and the queue reached 10.
 */
function queueRows() {
  const rows = requests.map((row) => ({
    key: row.key,
    name: row.name || row.key,
    source: row.source,
    status: row.status || "New",
    operator: row.operator || "",
    risk: row.risk || "",
    summary: row.summary || [],
    draft: draftByKey.get(row.key) || null,
    orphan: false,
  }));
  const known = new Set(rows.map((r) => r.key));
  draftRows.filter((d) => !d.request_id || !known.has(d.request_id))
    .forEach((d) => rows.push({
      // The draft id is the key when the draft names no request. Every row
      // needs one, and it is the only name this draft has.
      key: d.request_id || d.draft_id,
      name: d.request_id || d.draft_id,
      source: "draft", status: "—", operator: "", risk: "", summary: [],
      draft: d, orphan: true,
    }));
  return rows;
}

function deskStateOf(row) {
  const states = [];
  if (row.orphan) states.push("orphan");
  if (!row.draft) states.push("no-draft");
  else {
    states.push("has-draft");
    if (row.draft.run_count) states.push("has-run");
    if (row.draft.has_document) states.push("has-document");
  }
  return states;
}

function isSpam(row) {
  return row.risk === "confirmed-spam" || row.risk === "suspected";
}

function matchesSearch(row) {
  if (!filters.search) return true;
  const needle = filters.search.toLowerCase();
  return [row.name, row.key, row.operator, ...(row.summary || [])]
    .some((v) => String(v || "").toLowerCase().includes(needle));
}

/**
 * Post: the rows that pass every filter except `skip`.
 *
 * A dropdown counts its own options against the pool that excludes its own
 * dimension, so a count does not change when that dropdown changes. Mirrors
 * `_matchingExcept` in operations.js, which does this for the same rows.
 */
function matchingExcept(skip) {
  return queueRows().filter((row) => {
    if (skip !== "spam" && !filters.spam && isSpam(row)) return false;
    if (skip !== "status" && filters.status.size && !filters.status.has(row.status)) return false;
    if (skip !== "source" && filters.source.size && !filters.source.has(row.source)) return false;
    if (skip !== "flags" && filters.flags.size && !filters.flags.has(row.risk)) return false;
    if (skip !== "operator" && filters.operator.size
        && !filters.operator.has(row.operator || UNASSIGNED)) return false;
    if (skip !== "desk" && filters.desk.size
        && !deskStateOf(row).some((s) => filters.desk.has(s))) return false;
    if (skip !== "search" && !matchesSearch(row)) return false;
    return true;
  });
}

const visibleRows = () => matchingExcept(null);

/* ── the filter bar ───────────────────────────────────────────────────────── */

function dropdownHtml(dim, label, values, labelOf, chosen, countOf) {
  const open = openDropdown === dim;
  const active = chosen.size;
  const options = values.map((value) => `
    <label class="dd-option">
      <input type="checkbox" data-dim="${esc(dim)}" value="${esc(value)}"
             ${chosen.has(value) ? "checked" : ""}>
      <span>${esc(labelOf(value))}</span>
      <span class="dd-count">${countOf(value)}</span>
    </label>`).join("");
  return `<div class="dropdown">
      <button type="button" class="dd-toggle${active ? " active" : ""}"
              data-toggle="${esc(dim)}">${esc(label)}${active ? ` (${active})` : ""}
        <span class="dd-caret">${open ? "▴" : "▾"}</span></button>
      ${open ? `<div class="dd-panel">${options || '<span class="note">nothing</span>'}</div>` : ""}
    </div>`;
}

function renderFilters() {
  const all = queueRows();
  const pools = {
    status: matchingExcept("status"), flags: matchingExcept("flags"),
    source: matchingExcept("source"), operator: matchingExcept("operator"),
    desk: matchingExcept("desk"),
  };
  const statuses = [...new Set(all.map((r) => r.status))].sort();
  const sources = [...new Set(all.map((r) => r.source))].sort();
  const risks = [...new Set(all.map((r) => r.risk).filter(Boolean))].sort();
  const operators = [UNASSIGNED,
    ...new Set(all.map((r) => r.operator).filter(Boolean))].sort(
      (a, b) => (a === UNASSIGNED ? -1 : b === UNASSIGNED ? 1 : a.localeCompare(b)));

  const openActive = OPEN_STATUSES.every((s) => filters.status.has(s))
    && filters.status.size === OPEN_STATUSES.length;
  const anyActive = filters.status.size || filters.flags.size || filters.source.size
    || filters.operator.size || filters.desk.size || filters.search || filters.spam;

  $("filters").innerHTML = `
    <div class="filters-row">
      <button type="button" class="chip${openActive ? " active" : ""}" id="preset-open">Still open</button>
      ${dropdownHtml("status", "Status", statuses, (v) => v, filters.status,
        (v) => pools.status.filter((r) => r.status === v).length)}
      ${dropdownHtml("flags", "Flags", risks, (v) => v, filters.flags,
        (v) => pools.flags.filter((r) => r.risk === v).length)}
      ${dropdownHtml("source", "Source", sources, (v) => v, filters.source,
        (v) => pools.source.filter((r) => r.source === v).length)}
      ${dropdownHtml("operator", "Operator", operators,
        (v) => (v === UNASSIGNED ? "No operator assigned" : v), filters.operator,
        (v) => pools.operator.filter((r) => (r.operator || UNASSIGNED) === v).length)}
      ${dropdownHtml("desk", "Draft state", DESK_STATES.map((s) => s[0]),
        (v) => (DESK_STATES.find((s) => s[0] === v) || [v, v])[1], filters.desk,
        (v) => pools.desk.filter((r) => deskStateOf(r).includes(v)).length)}
    </div>
    <div class="filters-row">
      <input type="text" class="search" id="filter-search"
             placeholder="Search name, reference, operator…"
             value="${esc(filters.search)}">
      <button type="button" class="chip${filters.spam ? " active" : ""}"
              id="toggle-spam">Show spam</button>
      ${anyActive ? '<button type="button" class="chip" id="clear-filters">Clear filters</button>' : ""}
      <span class="grow"></span>
      <span class="note" id="filter-error"></span>
    </div>`;
  wireFilters();
}

function wireFilters() {
  $("preset-open").addEventListener("click", () => {
    const on = OPEN_STATUSES.every((s) => filters.status.has(s))
      && filters.status.size === OPEN_STATUSES.length;
    filters.status = on ? new Set() : new Set(OPEN_STATUSES);
    redraw();
  });
  $("toggle-spam").addEventListener("click", () => {
    filters.spam = !filters.spam; redraw();
  });
  $("clear-filters")?.addEventListener("click", () => {
    filters.status.clear(); filters.flags.clear(); filters.source.clear();
    filters.operator.clear(); filters.desk.clear();
    filters.search = ""; filters.spam = false;
    redraw();
  });

  const search = $("filter-search");
  search.addEventListener("input", () => {
    filters.search = search.value;
    renderQueue();          // the bar keeps its focus; only the list moves
    writeFiltersToUrl();
  });

  // One panel open at a time, and one outside-click listener for all of them.
  document.querySelectorAll(".dd-toggle").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openDropdown = openDropdown === button.dataset.toggle
        ? null : button.dataset.toggle;
      redraw();
    });
  });
  document.querySelectorAll(".dd-panel input[data-dim]").forEach((box) => {
    box.addEventListener("change", () => {
      const chosen = filters[box.dataset.dim];
      if (box.checked) chosen.add(box.value); else chosen.delete(box.value);
      redraw();
    });
  });
  document.querySelectorAll(".dd-panel").forEach((panel) =>
    panel.addEventListener("click", (event) => event.stopPropagation()));

  if (closeDropdownHandler) document.removeEventListener("click", closeDropdownHandler);
  closeDropdownHandler = () => { if (openDropdown) { openDropdown = null; redraw(); } };
  document.addEventListener("click", closeDropdownHandler);
}

/**
 * Post: the filters travel in the query string, so a link carries a view
 *       (ws-03 item 27.7). The chosen draft travels with them.
 */
function writeFiltersToUrl() {
  const params = new URLSearchParams();
  ["status", "flags", "source", "operator", "desk"].forEach((dim) => {
    if (filters[dim].size) params.set(dim, [...filters[dim]].join("|"));
  });
  if (filters.search) params.set("q", filters.search);
  if (filters.spam) params.set("spam", "1");
  if (current) params.set("draft", current.draft_id);
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

function readFiltersFromUrl() {
  const params = new URLSearchParams(location.search);
  ["status", "flags", "source", "operator", "desk"].forEach((dim) => {
    const raw = params.get(dim);
    if (raw) filters[dim] = new Set(raw.split("|").filter(Boolean));
  });
  filters.search = params.get("q") || "";
  filters.spam = params.get("spam") === "1";
  return params.get("draft") || "";
}

/* ── the queue ────────────────────────────────────────────────────────────── */

function queueRowHtml(row) {
  const draft = row.draft;
  const marks = [];
  if (row.orphan) marks.push('<span class="badge orphan">no request</span>');
  if (draft) marks.push('<span class="badge draft">draft</span>');
  if (draft && draft.fault_count)
    marks.push(`<span class="badge fault">${draft.fault_count} fault</span>`);
  if (draft && draft.flag_count)
    marks.push(`<span class="badge flag">${draft.flag_count} flag</span>`);
  // A code the catalogue does not hold is not a fault, and a row that showed
  // only faults read two invented codes as two finished days.
  if (draft && draft.unknown_code_count)
    marks.push(`<span class="badge fault">${draft.unknown_code_count} unknown</span>`);
  if (draft && draft.has_document) marks.push('<span class="badge doc">doc</span>');
  if (isSpam(row)) marks.push('<span class="badge spam">spam</span>');

  const chosen = current && draft && current.draft_id === draft.draft_id;
  return `<button class="qrow" data-key="${esc(row.key)}"
            data-draft="${esc(draft ? draft.draft_id : "")}"
            aria-current="${chosen ? "true" : "false"}">
      <div class="who">${esc(row.name)}</div>
      <div class="meta">${esc(row.source)} · ${esc(row.status)}${
        row.operator ? " · " + esc(row.operator) : ""}</div>
      ${marks.length ? `<div class="marks">${marks.join("")}</div>` : ""}
    </button>`;
}

function renderQueue() {
  const rows = visibleRows();
  const all = queueRows();
  $("queue").innerHTML =
    `<div class="qcount">${rows.length} of ${all.length} request(s)</div>`
    + (rows.length ? rows.map(queueRowHtml).join("")
       : `<div class="empty">No request matches these filters.</div>`);
  $("queue").querySelectorAll(".qrow").forEach((button) =>
    button.addEventListener("click", () => openRow(button.dataset.key,
                                                   button.dataset.draft)));
  $("summary").textContent =
    `${rows.length} of ${all.length} request(s) · ${draftRows.length} draft(s)`;
}

function redraw() { renderFilters(); renderQueue(); writeFiltersToUrl(); }

/**
 * Open one queue row in the detail pane.
 *
 * Pre:  `key` names a worklist request, and `draftId` is its draft or "".
 * Post: the pane holds that draft. A row with no draft opens one from the
 *       request, which is what the desk has always done on a first read.
 */
async function openRow(key, draftId) {
  $("detail").innerHTML = `<div class="empty">reading ${esc(key)}…</div>`;
  currentRow = queueRows().find((r) => r.key === key) || null;
  lastBuild = null;
  try {
    const draft = draftId
      ? await api(`/api/itinerary/drafts/${encodeURIComponent(draftId)}`)
      : await api("/api/itinerary/drafts/from-request", {
          method: "POST", body: JSON.stringify({ key }) });
    renderDetail(draft);
    await loadDrafts();
    renderQueue();
    writeFiltersToUrl();
  } catch (e) {
    $("detail").innerHTML = `<div class="empty err">${esc(e.message)}</div>`;
  }
}

/* ── the detail pane ──────────────────────────────────────────────────────── */

// A section opens when its own content asks to be read (ws-03 D53). The check
// already did this before this phase: `<details ... ${fault_count ? "open" : ""}>`.
// `actor` is "model", "rules", "human" or "" — it puts a coloured stripe on the
// section and a chip in its summary, so a reader knows who produced the
// content before opening it.
const ACTOR_LABEL = { model: "model", rules: "rules", human: "you" };

function section(id, title, headline, body, open, tone, actor) {
  const chip = actor
    ? `<span class="by ${esc(actor)}">${esc(ACTOR_LABEL[actor] || actor)}</span>`
    : "";
  return `<details class="sec ${actor ? "by-" + esc(actor) : ""}" id="${esc(id)}"
             ${open ? "open" : ""}>
      <summary class="${tone || ""}">${esc(title)}${chip}
        <span class="headline">${esc(headline || "")}</span></summary>
      <div class="body">${body}</div>
    </details>`;
}

function legend() {
  return `<div class="legend">
      <span class="eyebrow">who did the work</span>
      <span class="lg"><span class="by model">model</span> a layer wrote it</span>
      <span class="lg"><span class="by rules">rules</span> the catalogue and the checks</span>
      <span class="lg"><span class="by human">you</span> yours to type or press</span>
    </div>`;
}

function normalizedBlock(draft) {
  const normalized = draft.normalized || {};
  if (normalized.error) return `<div class="warn">${esc(normalized.error)}</div>`;
  const raw = draft.request_row || {};
  const rows = NORMALIZED_FIELDS.map(([key, label, rawKeys]) => {
    const value = Array.isArray(normalized[key])
      ? normalized[key].join(", ") : normalized[key];
    if (value === null || value === undefined || value === "") return "";
    const rawKey = rawKeys.find((k) => raw[k] !== undefined && String(raw[k]).trim() !== "");
    const submitted = rawKey === undefined ? undefined : String(raw[rawKey]).trim();
    const differs = submitted !== undefined
      && !PLACEHOLDERS.has(submitted.toLowerCase())
      && !String(value).trim().toLowerCase().includes(submitted.toLowerCase())
      && !submitted.toLowerCase().includes(String(value).trim().toLowerCase());
    return `<div class="k">${esc(label)}</div><div>${esc(value)}`
      + (differs ? ` <span class="warn">submitted: ${esc(submitted)}</span>` : "")
      + `</div>`;
  }).join("");
  const submittedRows = Object.entries(raw)
    .filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== "")
    .map(([k, v]) => `<div class="k">${esc(k)}</div><div>${
      esc(typeof v === "object" ? JSON.stringify(v) : v)}</div>`).join("");
  return `<div class="kv">${rows}</div>
    <div class="note" style="margin:10px 0 4px">As submitted</div>
    <div class="kv">${submittedRows || '<div class="k">nothing</div><div></div>'}</div>`;
}

function checkBlock(check) {
  if (!check) return `<div class="note">the check did not run</div>`;
  const faults = (check.faults || []).map((f) =>
    `<div class="fault"><span class="kind">${esc(f.kind)}</span>
       <span>day ${f.day}: ${esc(f.statement)}</span></div>`).join("");
  const flags = (check.flags || []).map((f) =>
    `<div class="fault flag"><span class="kind">${esc(f.kind)}</span>
       <span>day ${f.day}: ${esc(f.statement)}</span></div>`).join("");
  const unknown = (check.unknown_codes || []).length
    ? `<div class="warn">not in the catalogue: ${esc(check.unknown_codes.join(", "))}</div>` : "";
  const untested = (check.untested || []).map((u) =>
    `<div class="warn">${esc(u)}</div>`).join("");
  const notFound = Object.entries(check.not_yet_found || {}).map(([name, why]) =>
    `<div class="note">not yet found — ${esc(name)}: ${esc(why)}</div>`).join("");
  return faults + flags + unknown + untested + notFound
    || `<div class="note">no fault found by the checks this desk runs</div>`;
}

function sequenceBlock(sequence, agreement, which, askedDays) {
  if (!sequence) return `<div class="note">the ${which} proposer has not answered yet</div>`;
  const marks = (agreement && agreement.positions) || [];
  const check = sequence.check;
  const faultyDays = new Set(((check && check.faults) || []).map((f) => f.day));
  const chips = (sequence.day_codes || []).map((code, i) =>
    `<span class="code${faultyDays.has(i + 1) ? " faulty" : ""}"
       title="${esc(marks[i] || "")}">${i + 1}. ${esc(code)}</span>`).join("");
  const rejected = (sequence.rejected_codes || []).length
    ? `<div class="warn">not in the catalogue, so dropped:
         ${esc(sequence.rejected_codes.join(", "))}</div>` : "";
  const given = (sequence.day_codes || []).length;
  const days = (askedDays === null || askedDays === undefined)
    ? `${given} day(s), and the request names no day count`
    : given === askedDays ? `${given} of ${askedDays} day(s)`
      : `${given} day(s) for a ${askedDays}-day request, ${
          given < askedDays ? `${askedDays - given} short` : `${given - askedDays} over`}`;
  const actor = which === "model" ? "model" : "rules";
  return `<div class="card ${actor}">
      <div class="row"><span class="by ${actor}">${
        esc(ACTOR_LABEL[actor])}</span>
        <span class="note">${esc(days)}</span><span class="grow"></span>
        <span class="note">${esc(sequence.model || "")} ${esc(sequence.proposed_at || "")}</span></div>
      <div>${chips || '<span class="note">no codes</span>'}</div>
      ${sequence.note ? `<div class="note">${esc(sequence.note)}</div>` : ""}
      ${rejected}
      <div style="margin-top:8px">${checkBlock(check)}</div>
      <div class="row" style="margin-top:8px">
        <button class="generate" data-source="${esc(which)}" ${given ? "" : "disabled"}>
          Build from the ${esc(which)} sequence</button>
        ${given ? "" : '<span class="note">no codes to generate from</span>'}
      </div>
    </div>`;
}

// Who did the work, per step. Colour carries provenance on this desk, so a
// reader can tell a model's answer from the catalogue's without reading a word
// (ws-03 D53's sibling: the section says what, the stripe says who).
//
// `read_link` reads a column. `candidates` and `check` are the binder and the
// phase four checks. The other three call a model.
const STEP_ACTOR = {
  read_link: "rules", extract: "model", brief: "model",
  candidates: "rules", check: "rules", rank: "model", review: "model",
};

/**
 * The seven steps of one run, each on one line (ws-03 D56, WP29).
 *
 * Post: the outcome, the milliseconds and the endpoint on the surface. The
 *       prompt and the raw answer open in a drawer and never before.
 */
function stepsHtml(run) {
  return (run.steps || []).map((step, i) => {
    const tone = step.outcome === "untested" ? " untested"
      : step.outcome === "failed" ? " failed" : "";
    const actor = STEP_ACTOR[step.name] || "rules";
    const opens = step.prompt || step.answer;
    return `<div class="step ${actor}${tone}">
        <span class="n">${i + 1}</span>
        <span class="name">${esc(step.name)}</span>
        <span class="ms">${step.ms ? step.ms + "ms" : "—"}</span>
        <span class="where">${esc(step.where || "—")}</span>
        <span>${opens ? `<button class="step-open" data-run="${esc(run.run_id)}"
          data-step="${esc(step.name)}" title="prompt and answer">⟩</button>` : ""}</span>
        ${step.statement ? `<span class="said">${esc(step.statement)}</span>` : ""}
      </div>
      <pre class="drawer" id="drawer-${esc(run.run_id)}-${esc(step.name)}" hidden></pre>`;
  }).join("");
}

function runsBody(draft) {
  const runs = draft.runs || [];
  if (!runs.length) {
    return `<div class="note">No run yet. The create button is in Operations.</div>`;
  }
  return runs.map((run) => `<div class="card">
      <div class="row"><strong>${esc(run.statement)}</strong>
        <span class="grow"></span>
        <span class="note">${esc(run.started_at || "")}</span></div>
      <div class="note">${(run.endpoints_reached || []).length
        ? esc(run.endpoints_reached.join(", ")) : "no model ran"}</div>
      ${(run.failures || []).map((f) => `<div class="fault">
          <span class="kind">failed</span><span>${esc(f)}</span></div>`).join("")}
      <div class="steps" data-run="${esc(run.run_id)}">
        <div class="note">loading the steps…</div></div>
    </div>`).join("");
}

/**
 * Fill one run's step rows from `GET /runs/{id}`.
 *
 * Pre:  the section holds a `.steps` element naming the run.
 * Post: seven rows, each with its outcome, time and endpoint. The prompts stay
 *       in the answer and reach no surface until a reader opens a drawer.
 */
async function loadSteps(holder) {
  const runId = holder.dataset.run;
  try {
    const run = await api(`/api/itinerary/runs/${encodeURIComponent(runId)}`);
    holder.dataset.loaded = JSON.stringify(run);
    holder.innerHTML = stepsHtml(run);
    holder.querySelectorAll(".step-open").forEach((button) =>
      button.addEventListener("click", () => toggleDrawer(holder, button)));
  } catch (e) {
    holder.innerHTML = `<div class="warn">the run could not be read: ${esc(e.message)}</div>`;
  }
}

function toggleDrawer(holder, button) {
  const drawer = $(`drawer-${button.dataset.run}-${button.dataset.step}`);
  if (!drawer.hidden) { drawer.hidden = true; return; }
  const run = JSON.parse(holder.dataset.loaded || "{}");
  const step = (run.steps || []).find((s) => s.name === button.dataset.step) || {};
  drawer.textContent =
    (step.prompt ? `PROMPT\n${step.prompt}\n\n` : "")
    + (step.answer ? `ANSWER\n${step.answer}` : "")
    || "this step sent nothing and received nothing";
  drawer.hidden = false;
}

function thread(draft) {
  const turns = [];
  (draft.comments || []).forEach((c) => turns.push(
    `<div class="turn"><strong>you</strong>
       <span class="note">${esc(c.at || "")} · ${esc(c.rule_state || "new")}</span>
       <div>${esc(c.text)}</div></div>`));
  (draft.sequences || []).filter((s) => s.in_reply_to).forEach((s) => turns.push(
    `<div class="turn"><strong>${esc(s.source)}</strong>
       <span class="note">${esc(s.proposed_at || "")}</span>
       <div class="note">${esc(s.note || "")}</div></div>`));
  return turns.join("") || `<div class="note">no comment yet</div>`;
}

function notesBody(draft) {
  const list = draft.notes || [];
  if (!list.length) return `<div class="note">no machine note</div>`;
  return list.map((n) => `<div class="turn">
      <strong>${esc(n.source === "check" ? "Check" : "Model")}</strong>
      <span class="note">${esc(n.at || "")}</span>
      <div>${esc(n.text)}</div></div>`).join("");
}

/* ── the strip, and the whole pane ────────────────────────────────────────── */

/**
 * Explain why the newest run produced no usable proposal.
 *
 * Post: a prominent error panel when the run failed or produced no day codes.
 *       A usable proposal with only optional untested steps shows no panel.
 */
function runResultHtml(draft) {
  const run = draft.run || (draft.runs || [])[0];
  if (!run) return "";
  const failures = run.failures || [];
  const untested = run.untested || [];
  const responseCodes = (draft.chosen && draft.chosen.day_codes) || [];
  const savedModelCodes = (draft.sequences || [])
    .filter((sequence) => sequence.source === "model")
    .flatMap((sequence) => sequence.day_codes || []);
  const hasProposal = responseCodes.length > 0 || savedModelCodes.length > 0;
  if (hasProposal && !failures.length) return "";

  const problems = [...failures, ...untested];
  const visible = problems.slice(0, 4);
  const hiddenCount = Math.max(0, problems.length - visible.length);
  const title = hasProposal ? "The proposal finished with errors"
    : "No itinerary was proposed";
  const explanation = hasProposal
    ? "The run kept its proposal, but one or more steps failed."
    : "The run finished, but it could not build a candidate. Open What ran for the full trace.";
  return `<section id="run-result" class="run-result error" role="alert">
      <h2>${esc(title)}</h2>
      <p>${esc(explanation)}</p>
      ${visible.length ? `<ul>${visible.map((problem) =>
        `<li>${esc(problem)}</li>`).join("")}</ul>` : ""}
      ${hiddenCount ? `<p style="margin-top:8px">${hiddenCount} more issue(s) appear below.</p>` : ""}
    </section>`;
}

function showRunRequestError(message) {
  const detail = $("detail");
  if (!detail) return;
  detail.querySelector("#run-result")?.remove();
  detail.insertAdjacentHTML("afterbegin",
    `<section id="run-result" class="run-result error" role="alert">
       <h2>The proposal request failed</h2>
       <p>${esc(message || "The server did not return a usable answer.")}</p>
     </section>`);
}

function stripHtml(draft) {
  const normalized = draft.normalized || {};
  const newest = {};
  (draft.sequences || []).forEach((s) => { newest[s.source] = s; });
  const chosen = newest.model || newest.rules;
  const check = chosen && chosen.check;
  const runs = draft.runs || [];
  const run = runs[0];

  const faults = check ? check.fault_count : 0;
  const flags = check ? check.flag_count : 0;
  const given = chosen ? (chosen.day_codes || []).length : 0;

  return `<div class="strip">
      <div>
        <h3>What they asked for</h3>
        <div class="big">${esc(normalized.day_count ?? "?")} day(s)</div>
        <div class="sub">${esc(normalized.pax ?? "?")} traveller(s)</div>
        <div class="sub">${esc((normalized.requested_regions || []).join(", ") || "no region")}</div>
        <div class="sub">${draft.conversation_link
          ? `<a href="${esc(draft.conversation_link)}" target="_blank" rel="noopener"
               style="color:var(--accent)">conversation</a>`
          : "no conversation link"}</div>
      </div>
      <div>
        <h3>What ran</h3>
        <div class="big">${run ? esc(run.statement) : "no run yet"}</div>
        <div class="sub">${run && (run.endpoints_reached || []).length
          ? esc(run.endpoints_reached.join(", ")) : "no model ran"}</div>
        <div class="sub">${runs.length} run(s) on this draft</div>
        <div class="bar">
          <button class="run-offer" data-draft="${esc(draft.draft_id)}"
                  title="Reads the conversation, reasons about it and chooses an itinerary. Builds no document.">
            <span class="by model">model</span> Read it and propose</button>
        </div>
      </div>
      <div class="output">
        <h3>What came out</h3>
        <div class="big">${given} day(s)</div>
        <div class="sub">${faults} fault(s) · ${flags} flag(s)</div>
        <div class="sub">${draft.doc_url
          ? `<a href="${esc(draft.doc_url)}" target="_blank" rel="noopener"
               style="color:var(--status-ok)">the document</a>`
          : "no document yet"}</div>
        <div class="bar">
          <button class="generate primary" data-source="${newest.model ? "model" : "rules"}"
                  ${given ? "" : "disabled"}
                  title="Creates a real document in Drive. This is the first press that leaves this machine."
                  >Build the Google Doc</button>
        </div>
      </div>
    </div>`;
}

function renderDetail(draft) {
  current = draft;
  const normalized = draft.normalized || {};
  const newest = {};
  (draft.sequences || []).forEach((s) => { newest[s.source] = s; });
  const chosen = newest.model || newest.rules;
  const check = chosen && chosen.check;
  const runs = draft.runs || [];
  const brief = draft.brief || null;

  // Each section opens on its own content (ws-03 D53, item 28.3).
  const runFailed = runs.some((r) => (r.failures || []).length);
  const runUntested = runs.some((r) => (r.untested || []).length);
  const briefDisagrees = brief && (brief.contradiction_count
    || (brief.refused || []).length);

  $("detail").innerHTML = `
    ${runResultHtml(draft)}
    <div class="who-line">
      <h2>${esc(normalized.customer_name || draft.request_id || draft.draft_id)}</h2>
      <div class="note">${esc(draft.request_id || draft.draft_id)} · ${esc(draft.origin)}${
        draft.day_count ? " · " + esc(draft.day_count) + " day(s) asked" : ""}</div>
      ${(draft.parse_warnings || []).map((w) =>
        `<div class="warn">${esc(w)}</div>`).join("")}
    </div>
    ${legend()}
    ${stripHtml(draft)}
    ${section("sec-layers", "What ran",
      runs.length ? `${runs.length} run(s)` : "no run yet",
      runsBody(draft), runFailed || runUntested,
      runFailed ? "bad" : runUntested ? "warn" : "", "")}
    ${section("sec-brief", "What the customer asked for",
      brief ? (window.BriefCard ? BriefCard.headline(brief) : "") : "layer 1 did not run",
      window.BriefCard ? BriefCard.html(brief) : "", Boolean(briefDisagrees),
      briefDisagrees ? "warn" : "", "model")}
    ${section("sec-sequences", "The itinerary",
      chosen ? `${(chosen.day_codes || []).length} day(s)` : "nothing proposed",
      sequenceBlock(newest.model, draft.agreement, "model", draft.day_count)
      + sequenceBlock(newest.rules, draft.agreement, "rules", draft.day_count),
      true, (check && check.fault_count) ? "bad" : "", "")}
    ${section("sec-request", "The request as read", "",
      normalizedBlock(draft), false, "", "rules")}
    ${section("sec-feedback", "Your comments",
      `${(draft.comments || []).length} comment(s)`,
      `${thread(draft)}
       <div style="margin-top:10px"><textarea id="comment"
         placeholder="e.g. keep the first three days but end in Erbil — the judged rule book reads this"></textarea></div>
       <div class="row" style="margin-top:8px">
         <button id="save-comment">Save this comment</button>
         <span class="note" id="comment-msg"></span></div>`,
      false, "", "human")}
    ${section("sec-notes", "What the machine noticed",
      `${(draft.notes || []).length} note(s)`, notesBody(draft),
      Boolean((draft.notes || []).length), "", "model")}
    ${section("sec-move", "Move this request",
      currentRow ? esc(currentRow.status || "New") : "no worklist row",
      `<div id="wl-move">${window.DeskWorklist
        ? DeskWorklist.moveHtml(currentRow) : ""}</div>
       ${window.DeskWorklist ? DeskWorklist.replyHtml(lastBuild) : ""}`,
      false, "", "human")}
    ${section("sec-send", "Waiting to send",
      `${stagedRows.length} queued`,
      `<div id="wl-send-box">${window.DeskWorklist
        ? DeskWorklist.sendHtml(stagedRows) : ""}</div>`,
      Boolean(stagedRows.length), stagedRows.some((s) => s.conflict) ? "bad" : "",
      "human")}
    ${section("sec-rules", "The rule books", "",
      `<div id="rule-books"><div class="note">loading…</div></div>`,
      false, "", "rules")}`;

  $("save-comment")?.addEventListener("click", saveComment);
  document.querySelectorAll(".generate").forEach((b) =>
    b.addEventListener("click", () => generate(b.dataset.source)));
  document.querySelector(".run-offer")?.addEventListener("click", runTheLayers);
  if (window.DeskWorklist) {
    DeskWorklist.wireMove($("wl-move"), currentRow, reloadStaged);
    DeskWorklist.wireSend($("wl-send-box"), reloadStaged);
    DeskWorklist.wireReply($("wl-move"), lastBuild, currentRow, reloadStaged);
  }
  document.querySelectorAll(".steps[data-run]").forEach(loadSteps);
  $("sec-rules").addEventListener("toggle", function once() {
    if (this.open) { this.removeEventListener("toggle", once); loadRuleBooks(); }
  });
}

/* ── the rule books ───────────────────────────────────────────────────────── */

const FAMILY_LABELS = {
  first_night: "First night", last_night: "Last night",
  move: "Move", trip_length: "Trip length",
};

async function loadRuleBooks() {
  const holder = $("rule-books");
  if (!holder) return;
  try {
    const data = await api("/api/itinerary/rules");
    const counted = (data.counted || []).map((r) =>
      `<div class="turn"><strong>${esc(FAMILY_LABELS[r.family] || r.family)}</strong>
         <span class="note">${esc(r.subject || "")}</span>
         <div>${esc(r.statement)}</div></div>`).join("");
    const judged = (data.judged || []).map((r) =>
      `<div class="turn"><strong>${esc(r.rule_id)}</strong>
         <div>${esc(r.statement)}</div>
         <div class="note">${esc(r.corpus_verdict || "")}</div></div>`).join("");
    holder.innerHTML =
      `<div class="note">Counted — ${(data.counted || []).length} rule(s)</div>${counted}
       <div class="note" style="margin-top:10px">Judged — ${(data.judged || []).length}</div>${judged}`;
  } catch (e) {
    holder.innerHTML = `<div class="warn">${esc(e.message)}</div>`;
  }
}

/* ── the actions this page still owns ─────────────────────────────────────── */

/**
 * Run the seven steps on the open draft.
 *
 * Pre:  a draft is open.
 * Post: the draft carries a new run and a `model` sequence, and the pane shows
 *       them. No document is built — that is the next press.
 *
 * Blame: a layer the owner did not configure records itself untested and the
 * run finishes, so this reports a proposal rather than a failure.
 */
async function runTheLayers() {
  if (!current) return;
  $("run-result")?.remove();
  const button = document.querySelector(".run-offer");
  if (button) { button.disabled = true; button.textContent = "reading…"; }
  try {
    const answer = await api(
      `/api/itinerary/drafts/${encodeURIComponent(current.draft_id)}/create-offer`,
      { method: "POST", body: JSON.stringify({ force_read: false }) });
    renderDetail(answer);
    await loadDrafts();
    renderQueue();
  } catch (e) {
    showRunRequestError(e.message);
    if (button) { button.disabled = false; }
  }
}

/** Post: `stagedRows` matches the store, and the pane redraws around it. */
async function reloadStaged() {
  if (!window.DeskWorklist) return;
  try {
    const out = await DeskWorklist.staged();
    stagedRows = out.staged || [];
  } catch (e) { stagedRows = []; }
  if (current) renderDetail(current);
}

async function saveComment() {
  const text = $("comment").value.trim();
  if (!text || !current) return;
  $("comment-msg").textContent = "saving…";
  try {
    const draft = await api(
      `/api/itinerary/drafts/${encodeURIComponent(current.draft_id)}/comment`,
      { method: "POST", body: JSON.stringify({ text }) });
    renderDetail(draft);
  } catch (e) {
    $("comment-msg").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

/**
 * Build the document from a chosen sequence.
 *
 * Pre:  the sequence holds at least one day code, which the button enforces.
 * Post: a real Google Doc, and the draft names it. This is the only side
 *       effect this page has.
 */
async function generate(source) {
  if (!current) return;
  const buttons = [...document.querySelectorAll(".generate")];
  buttons.forEach((b) => { b.disabled = true; });
  try {
    const answer = await api(
      `/api/itinerary/drafts/${encodeURIComponent(current.draft_id)}/generate`,
      { method: "POST", body: JSON.stringify({ source }) });
    lastBuild = answer;
    renderDetail(answer);
    await loadDrafts();
    renderQueue();
  } catch (e) {
    $("detail").insertAdjacentHTML("afterbegin",
      `<div class="warn" style="margin:12px 18px">${esc(e.message)}</div>`);
    buttons.forEach((b) => { b.disabled = false; });
  }
}

function newRequestForm() {
  current = null;
  $("detail").innerHTML = `<div class="who-line"><h2>New request</h2></div>
    <div style="margin:0 18px">
      ${REQUEST_FIELDS.map(([key, label, hint]) => `
        <div style="margin-bottom:8px">
          <div class="note">${esc(label)}</div>
          <input type="text" data-key="${esc(key)}" placeholder="${esc(hint)}"></div>`).join("")}
      <div class="row"><button id="open-typed" class="primary">Open and propose</button>
        <span class="note" id="typed-msg"></span></div>
    </div>`;
  $("open-typed").addEventListener("click", openTyped);
}

async function openTyped() {
  const row = {};
  $("detail").querySelectorAll("input[data-key]").forEach((input) => {
    row[input.dataset.key] = input.value;
  });
  $("typed-msg").textContent = "opening…";
  try {
    const draft = await api("/api/itinerary/drafts",
      { method: "POST", body: JSON.stringify({ row, origin: "typed" }) });
    renderDetail(draft);
    await loadDrafts();
    renderQueue();
  } catch (e) {
    $("typed-msg").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

/* ── loading ──────────────────────────────────────────────────────────────── */

async function loadDrafts() {
  try {
    const data = await api("/api/itinerary/drafts");
    draftRows = data.drafts || [];
    draftByKey = new Map(draftRows.filter((d) => d.request_id)
      .map((d) => [d.request_id, d]));
  } catch (e) {
    draftRows = []; draftByKey = new Map();
    $("filter-error") && ($("filter-error").innerHTML =
      `<span class="err">the drafts did not load: ${esc(e.message)}</span>`);
  }
}

async function loadRequests() {
  try {
    const data = await api("/api/itinerary/requests");
    requests = data.requests || [];
  } catch (e) {
    // The desk keeps no copy of the worklist, so there is nothing to fall back
    // on. Say so rather than showing an empty queue that reads as "no work"
    // (ws-03 D14, invariant 3.5).
    requests = [];
    redraw();
    $("filter-error").innerHTML =
      `<span class="err">the worklist did not answer: ${esc(e.message)}</span>`;
    throw e;
  }
}

$("new-request").addEventListener("click", newRequestForm);

(async function start() {
  const asked = readFiltersFromUrl();
  await loadDrafts();
  await reloadStaged();
  if (asked) {
    // Operations links here with the draft it just created. It runs before the
    // worklist read, which reaches Supabase.
    try { renderDetail(await api(`/api/itinerary/drafts/${encodeURIComponent(asked)}`)); }
    catch (e) { $("detail").innerHTML = `<div class="empty err">${esc(e.message)}</div>`; }
  }
  try { await loadRequests(); } catch (e) { return; }
  redraw();
  // The worklist rows arrive after the deep-linked draft, so the row it
  // belongs to is found here. Without this the move controls read "no worklist
  // row" on exactly the path the Operations modal links down.
  if (asked && current && !currentRow) {
    currentRow = queueRows().find((r) => r.draft
      && r.draft.draft_id === current.draft_id) || null;
    if (currentRow) renderDetail(current);
  }
  try {
    const codes = await api("/api/itinerary/templates");
    $("codes-note").textContent = `${codes.count} active day codes`;
  } catch (e) {
    $("codes-note").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
})();
