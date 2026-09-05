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
  return `<div class="warn">Stale. Derived from a corpus of `
    + `${esc(stored.count)} offers. The corpus now holds ${esc(live.count)}. `
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

function appendBatch() {
  const list = $("list");
  const batch = loaded.slice(shown, shown + PAGE_SIZE);
  const before = list.children.length;
  list.insertAdjacentHTML("beforeend", batch.map(card).join(""));
  batch.forEach((p, index) => wire(list.children[before + index], p));
  shown += batch.length;

  const more = $("more");
  if (shown < loaded.length) {
    const next = Math.min(PAGE_SIZE, loaded.length - shown);
    more.innerHTML = `<button id="show-more">Show ${next} more</button>`
      + `<span class="note">${shown} of ${loaded.length} shown</span>`;
    $("show-more").addEventListener("click", appendBatch);
  } else {
    more.innerHTML = loaded.length > PAGE_SIZE
      ? `<span class="note">all ${loaded.length} shown</span>` : "";
  }
}

async function render() {
  const list = $("list");
  $("more").innerHTML = "";
  loaded = [];
  shown = 0;
  try {
    const data = await api(`/api/offers/proposals?status=${encodeURIComponent(filter)}`);
    const q = data.queue;
    $("summary").textContent =
      `${q.pending} pending · ${q.approved} approved · ${q.rejected} rejected`;
    if (!data.proposals.length) {
      list.innerHTML = `<div class="empty">nothing ${esc(filter)}</div>`;
      return;
    }
    loaded = data.proposals;
    list.innerHTML = "";
    appendBatch();
  } catch (e) {
    list.innerHTML = `<div class="empty err">${esc(e.message)}</div>`;
  }
}

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
