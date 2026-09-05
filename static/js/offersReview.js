/*
 * static/js/offersReview.js
 *
 * The catalogue review queue. Lives in a file rather than in a <script> block
 * inside offers_review.html, because the app sends
 * `script-src 'self' 'nonce-…'` on every response, and /offers is a
 * FileResponse that cannot carry a per-request nonce. An inline block is
 * therefore blocked, the page keeps its "loading…" placeholder forever, and
 * nothing appears in the console to say why. Every other page here already
 * loads its script this way.
 */
const $ = (id) => document.getElementById(id);
let filter = "pending";

// The queue holds hundreds of proposals after a full-corpus rebuild, and each
// card carries the whole proposed text. Building them all in one write locks a
// phone browser for a long time. Cards go in a batch at a time instead.
const PAGE_SIZE = 25;
let loaded = [];
let shown = 0;

// Near-duplicate proposals read as one thing and are decided as several. A full
// rebuild left 257, of which 95 sit in at least one pair scoring 0.60 or above.
// Grouping is a view: nothing is merged, no proposal is dropped, and no id
// changes. It is computed here rather than on the server because the response
// already carries every text, and the reviewer moves the line while reading.
let groupThreshold = 0.70;

const WORD_RE = /[a-z0-9]+/g;

function tokensOf(text) {
  return new Set(String(text || "").toLowerCase().match(WORD_RE) || []);
}

function overlap(a, b) {
  if (!a.size || !b.size) return 0;
  let shared = 0;
  for (const token of a) if (b.has(token)) shared += 1;
  return shared / (a.size + b.size - shared);
}

function groupByLikeness(proposals, threshold) {
  const sets = proposals.map((p) => tokensOf(p.proposed_text));
  const parent = proposals.map((_, i) => i);
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  for (let a = 0; a < proposals.length; a += 1) {
    for (let b = a + 1; b < proposals.length; b += 1) {
      if (overlap(sets[a], sets[b]) >= threshold) {
        const ra = find(a), rb = find(b);
        if (ra !== rb) parent[ra] = rb;
      }
    }
  }
  const byRoot = new Map();
  proposals.forEach((p, i) => {
    const root = find(i);
    if (!byRoot.has(root)) byRoot.set(root, []);
    byRoot.get(root).push(p);
  });
  // Strongest evidence first, both between groups and inside one.
  const groups = [...byRoot.values()];
  groups.forEach((g) => g.sort((x, y) => (y.weight ?? 0) - (x.weight ?? 0)));
  groups.sort((x, y) => (y[0].weight ?? 0) - (x[0].weight ?? 0));
  return groups;
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

// The figure is shown even when it is stale, with the warning beside it. The
// number says how far the queue has drifted, which is the thing a reviewer
// needs most at the moment it stops being current.
function provenanceWarning(provenance) {
  if (!provenance || provenance.state === "current") return "";
  const live = provenance.live || {};
  if (provenance.state === "unknown") {
    return `<div class="warn">Measured before corpus stamping. `
      + `It is not known which corpus this came from. `
      + `The corpus now holds ${esc(live.count)} offers.</div>`;
  }
  const stored = provenance.stored || {};
  // Two corpora can hold the same number of offers and different text. A
  // re-extraction rewrote 90 records and left the count at 335, so printing
  // "335 offers then, 335 now" would read as no change at all.
  const change = stored.count === live.count
    ? `The corpus still holds ${esc(live.count)} offers, and their text has changed since.`
    : `Derived from a corpus of ${esc(stored.count)} offers. `
      + `The corpus now holds ${esc(live.count)}.`;
  return `<div class="warn">Stale. ${change} `
    + `Re-derive before you act on these numbers.</div>`;
}

async function loadGap() {
  try {
    const g = await api("/api/offers/gap");
    if (!g.measured) { $("gap").textContent = g.detail; return; }
    $("gap").innerHTML =
      esc(`${g.offers} offers · ${g.total_days} days · ${g.matched} matched `
      + `(${(g.coverage * 100).toFixed(1)}%) · ${g.near_miss} edited · ${g.unmatched} uncovered`
      + ` · measured ${g.measured_at}`)
      + provenanceWarning(g.provenance);
  } catch (e) {
    $("gap").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

function card(p) {
  const isRevision = p.kind === "revision";
  const heading = isRevision
    ? `Revise <strong>${esc(p.target_code)}</strong>`
    : `New template${p.overnight_city ? ` — ${esc(p.overnight_city)}` : ""}`;
  const nearest = p.nearest_code
    ? `nearest existing: <strong>${esc(p.nearest_code)}</strong> at ${p.nearest_score.toFixed(2)}`
    : "no comparable template";
  const decided = p.status !== "pending";
  // A proposal from an older corpus sits in the same queue as a current one.
  // The reviewer is told which, because the evidence behind a stale proposal
  // may no longer be in the corpus at all.
  const stale = p.provenance && p.provenance !== "current"
    ? `<span class="tag stale">${esc(p.provenance)} corpus</span>`
    : "";

  return `
  <div class="card" data-id="${esc(p.proposal_id)}">
    <div class="row">
      <span class="tag ${esc(p.kind)}">${esc(p.kind)}</span>
      ${stale}
      <strong>${heading}</strong>
      <span class="grow"></span>
      <span class="note">written ${p.occurrences}× · weighted ${(p.weight ?? 0).toFixed(1)} · ${nearest}</span>
    </div>
    <div class="note" style="margin-top:6px">${esc(p.internal_notes)}</div>
    ${p.reordered_codes && p.reordered_codes.length
        ? `<div class="mirror">Same content as <strong>${p.reordered_codes.map(esc).join(", ")}</strong>
           in a different order. Check whether this is that route reversed before you create a new template.</div>`
        : ""}
    ${p.diff && p.diff.length
        ? `<div class="col" style="margin-top:12px">
             <h4>What changes</h4>
             <pre class="diff">${p.diff.map(([op, words]) =>
                 op === "added" ? `<ins>${esc(words)}</ins>`
               : op === "removed" ? `<del>${esc(words)}</del>`
               : esc(words)).join(" ")}</pre>
           </div>`
        : ""}
    <div class="cols">
      <div class="col">
        <h4>${isRevision ? "Currently in the catalogue" : "No current text"}</h4>
        <pre class="current">${esc(p.current_text || "—")}</pre>
      </div>
      <div class="col">
        <h4>Proposed — edit before approving</h4>
        <textarea class="text" ${decided ? "disabled" : ""}>${esc(p.proposed_text)}</textarea>
      </div>
    </div>
    <div class="fields">
      <label>Code <input type="text" class="code" value="${esc(p.fields.code || p.target_code || "")}"
             placeholder="e.g. MO2" ${decided ? "disabled" : ""}></label>
      <label>Region <input type="text" class="region" value="${esc(p.fields.region || "")}"
             placeholder="Central Iraq" ${decided ? "disabled" : ""}></label>
      <label>Overnight <input type="text" class="overnight"
             value="${esc(p.fields.overnight_city || "")}" ${decided ? "disabled" : ""}></label>
    </div>
    <details class="evidence">
      <summary>${p.evidence_day_keys.length} sent day(s) behind this</summary>
      <div class="days"></div>
    </details>
    <div class="actions">
      ${decided
        ? `<span class="note">${esc(p.status)}${p.reviewer_note ? " — " + esc(p.reviewer_note) : ""}</span>`
        : `<input type="text" class="why" placeholder="note (optional)" style="flex:1">
           <button class="primary approve">Approve</button>
           <button class="danger reject">Reject</button>`}
      <span class="msg note"></span>
    </div>
  </div>`;
}

function wire(el, p) {
  el.querySelector(".evidence").addEventListener("toggle", async (ev) => {
    const box = el.querySelector(".days");
    if (!ev.target.open || box.dataset.loaded) return;
    box.dataset.loaded = "1";
    for (const key of p.evidence_day_keys.slice(0, 12)) {
      try {
        const d = await api(`/api/offers/evidence/${encodeURIComponent(key)}`);
        box.insertAdjacentHTML("beforeend",
          `<pre><strong>${esc(d.attachment_name)}</strong> · day ${d.day_number}`
          + `${d.overnight_city ? " · " + esc(d.overnight_city) : ""}\n\n${esc(d.text)}</pre>`);
      } catch (e) {
        box.insertAdjacentHTML("beforeend", `<pre class="err">${esc(key)}: ${esc(e.message)}</pre>`);
      }
    }
  });

  const decide = async (status) => {
    const msg = el.querySelector(".msg");
    const code = el.querySelector(".code").value.trim();
    if (status === "approved" && !code) {
      msg.innerHTML = '<span class="err">a template needs a code before it can be approved</span>';
      return;
    }
    el.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    msg.textContent = "saving…";
    try {
      await api(`/api/offers/proposals/${encodeURIComponent(p.proposal_id)}/verdict`, {
        method: "POST",
        body: JSON.stringify({
          status,
          reviewer_note: el.querySelector(".why").value,
          edited_fields: {
            code,
            full_text: el.querySelector(".text").value,
            region: el.querySelector(".region").value.trim(),
            overnight_city: el.querySelector(".overnight").value.trim(),
          },
        }),
      });
      await render();
    } catch (e) {
      msg.innerHTML = `<span class="err">${esc(e.message)}</span>`;
      el.querySelectorAll("button").forEach((b) => { b.disabled = false; });
    }
  };

  el.querySelector(".approve")?.addEventListener("click", () => decide("approved"));
  el.querySelector(".reject")?.addEventListener("click", () => decide("rejected"));
}

function groupBlock(group, index) {
  if (group.length === 1) return card(group[0]);
  return `<div class="group">
    <div class="group-head">
      <strong>${group.length} near-duplicate proposals</strong>
      <span class="note">decided together, or one at a time</span>
      <span class="grow"></span>
      <button class="group-approve" data-group="${index}">Approve all ${group.length}</button>
      <button class="group-reject danger" data-group="${index}">Reject all ${group.length}</button>
      <span class="msg note" data-group-msg="${index}"></span>
    </div>
    ${group.map(card).join("")}
  </div>`;
}

function wireGroup(container, group, index) {
  const decideAll = async (status) => {
    const msg = container.querySelector(`[data-group-msg="${index}"]`);
    // One verdict, one proposal at a time. Each still needs its own code, and a
    // proposal the server refuses must not silently take the others down.
    const refused = [];
    for (const p of group) {
      const el = container.querySelector(`.card[data-id="${CSS.escape(p.proposal_id)}"]`);
      const code = el?.querySelector(".code")?.value.trim();
      if (status === "approved" && !code) { refused.push(p.proposal_id); continue; }
      try {
        await api(`/api/offers/proposals/${encodeURIComponent(p.proposal_id)}/verdict`, {
          method: "POST",
          body: JSON.stringify({
            status,
            reviewer_note: el?.querySelector(".why")?.value || "",
            edited_fields: {
              code,
              full_text: el?.querySelector(".text")?.value,
              region: el?.querySelector(".region")?.value.trim(),
              overnight_city: el?.querySelector(".overnight")?.value.trim(),
            },
          }),
        });
      } catch (e) { refused.push(p.proposal_id); }
    }
    if (refused.length) {
      msg.innerHTML = `<span class="err">${refused.length} of ${group.length} not decided`
        + ` — a template needs a code before it can be approved</span>`;
    }
    await render();
  };
  container.querySelector(`.group-approve[data-group="${index}"]`)
    ?.addEventListener("click", () => decideAll("approved"));
  container.querySelector(`.group-reject[data-group="${index}"]`)
    ?.addEventListener("click", () => decideAll("rejected"));
}

function appendBatch() {
  const list = $("list");
  const batch = loaded.slice(shown, shown + PAGE_SIZE);
  const before = list.children.length;
  list.insertAdjacentHTML("beforeend",
    batch.map((group, i) => groupBlock(group, shown + i)).join(""));
  batch.forEach((group, i) => {
    const container = list.children[before + i];
    const cards = container.classList.contains("group")
      ? container.querySelectorAll(".card") : [container];
    group.forEach((p, j) => wire(cards[j], p));
    if (group.length > 1) wireGroup(container, group, shown + i);
  });
  shown += batch.length;

  const proposals = loaded.reduce((n, g) => n + g.length, 0);
  const more = $("more");
  if (shown < loaded.length) {
    const next = Math.min(PAGE_SIZE, loaded.length - shown);
    more.innerHTML = `<button id="show-more">Show ${next} more</button>`
      + `<span class="note">${shown} of ${loaded.length} blocks shown`
      + ` · ${proposals} proposals</span>`;
    $("show-more").addEventListener("click", appendBatch);
  } else {
    more.innerHTML = loaded.length > PAGE_SIZE
      ? `<span class="note">all ${loaded.length} blocks shown · ${proposals} proposals</span>` : "";
  }
}

let lastFetched = [];

function regroup() {
  const list = $("list");
  $("more").innerHTML = "";
  shown = 0;
  loaded = groupByLikeness(lastFetched, groupThreshold);
  const grouped = loaded.filter((g) => g.length > 1).length;
  $("grouping-count").textContent =
    `${loaded.length} blocks from ${lastFetched.length} proposals · ${grouped} grouped`;
  list.innerHTML = "";
  appendBatch();
}

async function render() {
  const list = $("list");
  $("more").innerHTML = "";
  loaded = [];
  lastFetched = [];
  shown = 0;
  try {
    const data = await api(`/api/offers/proposals?status=${encodeURIComponent(filter)}`);
    const q = data.queue;
    $("summary").textContent =
      `${q.pending} pending · ${q.approved} approved · ${q.rejected} rejected`;
    if (!data.proposals.length) {
      list.innerHTML = `<div class="empty">nothing ${esc(filter)}</div>`;
      $("grouping-count").textContent = "";
      return;
    }
    lastFetched = data.proposals;
    regroup();
  } catch (e) {
    list.innerHTML = `<div class="empty err">${esc(e.message)}</div>`;
  }
}

$("grouping").addEventListener("input", (ev) => {
  groupThreshold = Number(ev.target.value) / 100;
  $("grouping-value").textContent = groupThreshold.toFixed(2);
  if (lastFetched.length) regroup();
});

for (const status of ["pending", "approved", "rejected"]) {
  $(`f-${status}`).addEventListener("click", () => {
    filter = status;
    for (const s of ["pending", "approved", "rejected"]) {
      $(`f-${s}`).classList.toggle("primary", s === status);
    }
    render();
  });
}

$("rebuild").addEventListener("click", async (ev) => {
  ev.target.disabled = true;
  ev.target.textContent = "re-deriving…";
  try {
    await api("/api/offers/proposals/rebuild", { method: "POST" });
    await Promise.all([loadGap(), render()]);
  } catch (e) {
    $("summary").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
  ev.target.disabled = false;
  ev.target.textContent = "Re-derive from corpus";
});

loadGap();
render();
