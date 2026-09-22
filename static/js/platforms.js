// static/js/platforms.js — the Mahdawi Platforms dashboard.
// Reads /api/mahdawi/*, renders platform cards + the gathered-product grid,
// and drives approve -> package -> mark-posted. Fetch runs in the background
// and this polls /runs/{id}. Nothing here posts to a platform.

const $ = (id) => document.getElementById(id);

async function api(path, opts) {
  const res = await fetch("/api/mahdawi" + path, Object.assign(
    { headers: { "Content-Type": "application/json" } }, opts || {}));
  if (!res.ok) throw new Error((await res.text()) || res.status);
  return res.json();
}


function card(name, rows) {
  const body = rows.map(([k, v]) => `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join("");
  return `<div class="card"><h2>${name}</h2>${body}</div>`;
}

async function loadStatus() {
  const s = await api("/platforms/status");
  const c = s.counts || {};
  const sess = (on) => `<span class="dot ${on ? "on" : "off"}"></span>${on ? "connected" : "not connected"}`;
  $("cards").innerHTML = [
    card("Instagram", [["session", "manual"], ["staged", c.staged || 0], ["posted", c.posted || 0]]),
    card("TikTok", [["session", "manual"], ["staged", c.staged || 0], ["posted", c.posted || 0]]),
    card("Fedshi", [["session", sess(s.fedshi_session)], ["gathered", s.gathered || 0],
                    ["approved", c.approved || 0]]),
    layer2Card(s.layer2 || {}),
  ].join("");
}

// Layer Two: Gemini via 9router writes and judges. Waiting products retry here.
function layer2Card(l2) {
  if (!l2.enabled) return card("Gemini (9router)", [["layer two", "off"]]);
  const rows = [["writer", esc(l2.writer_model)], ["judge", esc(l2.judge_model)],
                ["waiting", l2.waiting || 0]];
  let html = card("Gemini (9router)", rows);
  if (l2.waiting) {
    html = html.replace(/<\/div>$/, `<div class="sub" title="${esc(l2.last_error)}">last error: ${esc(l2.last_error)}</div>
      <button id="layer2-retry" data-act-l2="retry">Retry waiting</button></div>`);
  }
  return html;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, ch =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
}

function statusPill(st) { return `<span class="pill ${st}">${st}</span>`; }

function actionsFor(p) {
  if (p.status === "staged")
    return `<button class="primary" data-act="approve" data-sku="${p.sku}">Approve</button>`;
  if (p.status === "approved")
    return `<button class="primary" data-act="package" data-sku="${p.sku}">Package</button>`;
  if (p.status === "packaged")
    return `<button data-act="posted" data-sku="${p.sku}">Mark posted</button>`;
  return "";
}

function row(p) {
  const fmt = (n) => n == null ? "—" : Number(n).toLocaleString();
  const links = [`<a href="${p.fedshi_url}" target="_blank" rel="noopener">Fedshi</a>`];
  if (p.package_dir) links.push(`<span title="${p.package_dir}">package ✓</span>`);
  const thumb = p.thumb_url
    ? `<img class="thumb" src="${p.thumb_url}" alt="" onerror="this.style.visibility='hidden'">`
    : `<div class="thumb"></div>`;
  const rank = p.rank ? `<span title="${esc(p.rank_reason)}">#${p.rank}</span>` : "";
  const l2 = p.status === "waiting_layer2"
    ? `<div class="note">waiting for Gemini: ${esc(p.layer2_error)}</div>`
    : (p.market_note ? `<div class="note">${esc(p.market_note).replace(/\n/g, "<br>")}</div>` : "");
  return `<div class="row">
    ${thumb}
    <div class="prod">
      <div class="t" title="${esc(p.title || p.sku)}">${esc(p.title || p.sku)}</div>
      <div class="m">${rank}<span>${p.sku}</span><span>سعر: ${fmt(p.price)} د.ع</span>
        <span>ربح: ${fmt(p.profit)}</span>${links.map(l => `<span>${l}</span>`).join("")}
        ${(p.flags || []).map(f => `<span>⚑ ${esc(f)}</span>`).join("")}</div>
      ${l2}
    </div>
    <div class="acts">${statusPill(p.status)}${actionsFor(p)}</div>
  </div>`;
}

async function loadGrid() {
  const { products } = await api("/products");
  // Gemini's rank orders the open products; unranked ones keep their order after.
  products.sort((a, b) => (a.rank || 1e9) - (b.rank || 1e9));
  $("grid").innerHTML = products.length
    ? products.map(row).join("")
    : `<div class="sub">No products gathered yet. Fetch some above.</div>`;
}

function replyRow(r) {
  const p = r.payload || {};
  const msg = (p.message || {}).text || "";
  const draft = (p.draft || {}).text;
  const problems = (p.check_problems || []).map(x => `<span>⚑ ${esc(x)}</span>`).join("");
  return `<div class="row reply">
    <div class="prod">
      <div class="t">${esc(msg)}</div>
      <div class="note">${draft ? esc(draft) : "no draft: " + esc(r.reason)}</div>
      <div class="m"><span>${esc(r.channel)}</span><span>${esc(p.tier || "")}</span>
        <span>${esc(r.reason)}</span>${problems}</div>
    </div></div>`;
}

async function loadReplies() {
  const { replies } = await api("/replies");
  $("replies").innerHTML = replies.length
    ? replies.map(replyRow).join("")
    : `<div class="sub">No replies waiting for approval.</div>`;
}

async function refresh() { await Promise.all([loadStatus(), loadGrid(), loadReplies()]); }

async function retryLayer2(button) {
  button.disabled = true;
  $("run-msg").textContent = "Gemini is working on waiting products…";
  try {
    const r = await api("/layer2/retry", { method: "POST" });
    $("run-msg").textContent = `Gemini: ${r.staged} staged, ${r.still_waiting} still waiting`
      + (r.rank_error ? ` — ranking failed: ${r.rank_error}` : "");
  } catch (e) { $("run-msg").textContent = "Error: " + e.message; }
  await refresh();
}

async function act(button) {
  const { act, sku } = button.dataset;
  button.disabled = true;
  try {
    await api("/" + act, { method: "POST", body: JSON.stringify({ sku }) });
    await refresh();
  } catch (e) { $("run-msg").textContent = "Error: " + e.message; button.disabled = false; }
}

async function pollRun(runId) {
  const msg = $("run-msg");
  for (;;) {
    let s;
    try { s = await api("/runs/" + runId); } catch { break; }
    if (s.state === "running" || s.state === "queued" || s.state === "writing") {
      msg.textContent = s.state === "writing" ? "Gemini is writing…"
                                              : `Fetching… ${s.done}/${s.total}`;
      await new Promise(r => setTimeout(r, 1500));
      continue;
    }
    if (s.state === "error") msg.textContent = "Fetch error: " + s.error;
    else msg.textContent = `Fetched: ${s.staged} staged, ${s.waiting_layer2 || 0} waiting for Gemini, `
      + `${s.skipped} skipped` + (s.rank_error ? ` — ranking failed: ${s.rank_error}` : "");
    await refresh();
    break;
  }
}

async function startFetch(payload) {
  $("run-msg").textContent = "Starting…";
  try {
    const { run_id } = await api("/fetch", { method: "POST", body: JSON.stringify(payload) });
    pollRun(run_id);
  } catch (e) { $("run-msg").textContent = "Error: " + e.message; }
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-act]");
  if (b) act(b);
  const r = e.target.closest("button[data-act-l2]");
  if (r) retryLayer2(r);
});
$("fetch-skus").onclick = () => {
  const skus = $("skus").value.split(",").map(s => s.trim()).filter(Boolean);
  if (skus.length) startFetch({ skus });
};
$("fetch-best").onclick = () => startFetch({ collection: "bestseller" });
$("fetch-new").onclick = () => startFetch({ collection: "new" });
$("refresh").onclick = refresh;

refresh().catch(e => { $("run-msg").textContent = "Load error: " + e.message; });
