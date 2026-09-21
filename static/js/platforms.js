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
  ].join("");
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
  return `<div class="row">
    ${thumb}
    <div class="prod">
      <div class="t" title="${(p.title || p.sku)}">${p.title || p.sku}</div>
      <div class="m"><span>${p.sku}</span><span>سعر: ${fmt(p.price)} د.ع</span>
        <span>ربح: ${fmt(p.profit)}</span>${links.map(l => `<span>${l}</span>`).join("")}
        ${(p.flags || []).map(f => `<span>⚑ ${f}</span>`).join("")}</div>
    </div>
    <div class="acts">${statusPill(p.status)}${actionsFor(p)}</div>
  </div>`;
}

async function loadGrid() {
  const { products } = await api("/products");
  $("grid").innerHTML = products.length
    ? products.map(row).join("")
    : `<div class="sub">No products gathered yet. Fetch some above.</div>`;
}

async function refresh() { await Promise.all([loadStatus(), loadGrid()]); }

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
    if (s.state === "running" || s.state === "queued") {
      msg.textContent = `Fetching… ${s.done}/${s.total}`;
      await new Promise(r => setTimeout(r, 1500));
      continue;
    }
    if (s.state === "error") msg.textContent = "Fetch error: " + s.error;
    else msg.textContent = `Fetched: ${s.staged} staged, ${s.skipped} skipped`;
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
});
$("fetch-skus").onclick = () => {
  const skus = $("skus").value.split(",").map(s => s.trim()).filter(Boolean);
  if (skus.length) startFetch({ skus });
};
$("fetch-best").onclick = () => startFetch({ collection: "bestseller" });
$("fetch-new").onclick = () => startFetch({ collection: "new" });
$("refresh").onclick = refresh;

refresh().catch(e => { $("run-msg").textContent = "Load error: " + e.message; });
