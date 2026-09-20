/* Presentation state stays in this tab. Calculation and document validation remain server-owned. */
const workspaceViews = { overview: 'Overview', pricing: 'Group pricing', request: 'Request', sources: 'Rules and sources', activity: 'Activity' };
const draftPresentation = new Map();
let workspaceView = 'overview';
let workspaceList = false;
let queuePosition = 0;
let openRequestSerial = 0;
let dayTitles = new Map();

function rememberWorkspace() {
  if (!current || !$('detail').dataset.draft) return;
  const state = draftPresentation.get($('detail').dataset.draft) || {};
  state.comment = $('comment')?.value ?? state.comment ?? '';
  state.open = [...$('detail').querySelectorAll('details[id][open]')].map(e => e.id);
  state.view = workspaceView;
  state.scroll = $('detail').scrollTop;
  draftPresentation.set($('detail').dataset.draft, state);
}

function readiness(draft) {
  const sequence = (draft.sequences || []).at(-1);
  if (draft.stale || sequence?.stale) return { label: 'Recalculation required', ready: false };
  if (!sequence) return { label: 'Not calculated', ready: false };
  const ready = Boolean(sequence.day_codes?.length && sequence.check?.is_clean && sequence.generation?.ready);
  return { label: ready ? 'Ready to build' : 'Needs attention', ready };
}

function workspaceProblems(draft) {
  const sequence = (draft.sequences || []).at(-1);
  const check = sequence?.check || {};
  const problems = [...(check.faults || []).map(f => ({ text: f.statement, day: f.day })),
    ...(check.unknown_codes || []).map(code => ({ text: `Unknown day code: ${code}` })),
    ...(check.untested || []).map(text => ({ text })),
    ...(sequence?.plan?.issues || []).map(text => ({ text })),
    ...(sequence?.generation?.errors || []).map(text => ({ text }))];
  if (draft.stale) problems.unshift({ text: draft.stale.statement || 'The saved result requires recalculation.' });
  return problems.filter((p, i, all) => all.findIndex(other => other.text === p.text) === i);
}

function blockerHtml(draft) {
  const problems = workspaceProblems(draft);
  if (!problems.length) return '';
  return `<section class="attention" aria-labelledby="attention-title"><h3 id="attention-title">Needs attention · ${problems.length}</h3>
    <ul>${problems.map(p => {
      const day = Number(p.day) || Number(/\bDay\s+(\d+)/i.exec(p.text)?.[1]);
      const catalogue = /catalogue|template|day code/i.test(p.text);
      const request = /request|start date|date unknown/i.test(p.text);
      const target = day ? `day-${day}` : catalogue ? 'current-checks' : request ? 'sec-request' : 'current-checks';
      const view = day ? 'overview' : request && !catalogue ? 'request' : 'sources';
      return `<li><button class="text-link" data-view="${view}" data-target="${target}">${esc(p.text)}</button>
        <span class="note">${catalogue ? 'Catalogue' : request ? 'Request' : 'Check details'}</span></li>`;
    }).join('')}</ul></section>`;
}

function itineraryDays(sequence) {
  if (!sequence) return '<p>No itinerary calculated yet.</p>';
  const facts = new Map((sequence.plan?.days || []).map(day => [day.number, day]));
  return `<ol class="day-list">${(sequence.day_codes || []).map((code, index) => {
    const day = facts.get(index + 1);
    const title = dayTitles.get(code);
    return `<li id="day-${index + 1}" tabindex="-1"><div class="day-heading"><strong>Day ${index + 1}${title ? ` · ${esc(title)}` : ''}</strong><code>${esc(code)}</code></div>
      <div>${esc(day?.start_city || 'Unknown start')} → ${esc(day?.end_city || 'Unknown destination')}</div>
      <div class="day-facts"><span>Overnight: <strong>${esc(day?.overnight_status === 'present' ? day.overnight_city : day?.overnight_status || 'unknown')}</strong></span>
      <span>Accommodation: <strong>${esc(day?.accommodation || 'unknown')}</strong></span></div>
      <button class="text-link" data-view="sources" data-target="evidence-day-${index + 1}">Day ${index + 1} evidence</button></li>`;
  }).join('')}</ol>`;
}

function dayEvidence(sequence) {
  return (sequence?.plan?.days || []).map(day => `<details id="evidence-day-${day.number}" class="sec">
    <summary>Day ${day.number} · ${esc(day.code)} · evidence</summary><div class="body">
    <p>Role: ${esc(day.role)}. Source: ${esc(day.evidence?.place_source || 'catalogue')}.</p>
    ${day.evidence?.source_day ? `<p>Source day ${esc(day.evidence.source_day)}: ${esc(day.evidence.source_facts?.evidence || '')}</p>` : ''}
    <pre class="drawer">${esc(JSON.stringify(day, null, 2))}</pre></div></details>`).join('');
}

function workspaceHeader(draft) {
  const n = draft.normalized || {};
  const state = readiness(draft);
  return `<div class="workspace-heading"><button id="back-requests">← Back to requests</button>
    <div><h2 id="workspace-title" tabindex="-1">${esc(n.customer_name || draft.request_id || draft.draft_id)}</h2>
    <div class="note">${esc(draft.request_id || draft.draft_id)} · ${esc(draft.origin || '')}</div></div>
    <strong class="readiness ${state.ready ? 'ready' : ''}" role="status">${state.label}</strong></div>
    <nav class="workspace-nav" aria-label="Request views">${Object.entries(workspaceViews).map(([key, label]) =>
      `<button data-view="${key}" ${workspaceView === key ? 'aria-current="page"' : ''}>${label}</button>`).join('')}</nav>`;
}

// Pre: draft is the server response for one request. Post: all data remains reachable in the workspace views.
function renderDetail(draft) {
  rememberWorkspace();
  const sameDraft = current?.draft_id === draft.draft_id;
  current = draft;
  const saved = draftPresentation.get(draft.draft_id);
  if (!sameDraft) workspaceView = saved?.view || workspaceView;
  const n = draft.normalized || {};
  const chosen = (draft.sequences || []).at(-1);
  const state = readiness(draft);
  const detail = $('detail');
  detail.dataset.draft = draft.draft_id;
  detail.innerHTML = `${workspaceHeader(draft)}
    <section class="workspace-panel" id="view-overview" aria-label="Overview">
      <div class="request-summary"><span><strong>${esc(n.day_count ?? '?')} days</strong> · ${esc(n.pax ?? '?')} travellers</span>
      <span>${esc(n.start_date || [n.travel_month, n.travel_year].filter(Boolean).join(' ') || 'Date not specified')}</span>
      <span>${esc(n.requested_regions?.join(', ') || 'Default route · no regions specified')}</span>
      ${n.region_basis ? `<span class="note">${esc(n.region_basis)}</span>` : ''}</div>
      ${(draft.parse_warnings || []).map(w => `<p class="warn">${esc(w)}</p>`).join('')}
      ${blockerHtml(draft)}
      <div class="workspace-actions"><button class="run-offer">Recalculate itinerary</button>
      <button class="generate primary" data-source="${esc(chosen?.source || 'rules')}" ${state.ready ? '' : 'disabled'}>Build Google Doc</button>
      <button data-view="activity" data-target="sec-feedback">Comments (${(draft.comments || []).length})</button></div>
      <p class="note">${chosen ? `Current result: ${esc(chosen.source)} · ${esc(chosen.proposed_at || '')}` : 'Recalculate to propose an itinerary.'}</p>
      <p>${draft.doc_url ? `<a href="${esc(draft.doc_url)}" target="_blank" rel="noopener">Open existing document</a> <span class="note">Saved document. Recalculation does not update it.</span>` : 'No document created.'}</p>
      <h3>Itinerary · ${(chosen?.day_codes || []).length} of ${esc(n.day_count ?? '?')} days</h3>
      ${itineraryDays(chosen)}
      ${chosen?.note ? `<details id="proposal-note"><summary>Proposal explanation</summary><p>${esc(chosen.note)}</p></details>` : ''}
      ${chosen?.rejected_codes?.length ? `<p class="warn">Rejected codes: ${esc(chosen.rejected_codes.join(', '))}</p>` : ''}
      ${!chosen ? runResultHtml(draft) : ''}
    </section>
    <section class="workspace-panel" id="view-pricing" aria-label="Group pricing" hidden>
      <h3>Group pricing</h3><p>Compare Coaster and VIP coach prices, with one free tour leader in a single room.</p>
      <form id="group-quote-form">
        <label class="quote-night"><input id="quote-omit-night" type="checkbox" checked> Omit the final hotel night and depart after the last tour</label>
        <div class="quote-fields">
          <label>Office markup (%)<input id="quote-office" type="number" min="0" max="100" step="0.1" value="10" required></label>
          <label>Margin markup (%)<input id="quote-margin" type="number" min="0" max="100" step="0.1" value="20" required></label>
          <label>Single supplement (USD)<input id="quote-single" type="number" min="0" max="10000" step="0.01" placeholder="Calculate from hotel rates"></label>
        </div><button type="submit">Save options and calculate</button>
      </form><p id="group-quote-status" role="status"></p><div id="group-quote-result"></div>
    </section>
    <section class="workspace-panel" id="view-request" aria-label="Request" hidden>
      ${draft.conversation_link ? `<p><a href="${esc(draft.conversation_link)}" target="_blank" rel="noopener">Open conversation</a></p>` : '<p>No conversation link.</p>'}
      ${section('sec-request', 'Submitted and interpreted request', '', normalizedBlock(draft), true, '', 'rules')}
      ${section('sec-brief', 'Model interpretation', draft.brief ? 'Historical model brief' : 'No model brief', window.BriefCard ? BriefCard.html(draft.brief) : '', false, '', 'model')}
    </section>
    <section class="workspace-panel" id="view-sources" aria-label="Rules and sources" hidden>
      <section id="current-checks" tabindex="-1"><h3>Current checks</h3>${checkBlock(chosen?.check)}
      ${(chosen?.generation?.errors || []).map(e => `<p class="warn">${esc(e)}</p>`).join('')}</section>
      ${dayEvidence(chosen)}
      ${section('plan-reference', 'Resolved plan and references', '', resolvedPlanBlock(chosen?.plan), false, '', 'rules')}
      ${referencePoolBlock(draft.reference_pool)}
      ${section('sec-rules', 'Rule books', '', '<div id="rule-books">Open to load rule books.</div>', false, '', 'rules')}
    </section>
    <section class="workspace-panel" id="view-activity" aria-label="Activity" hidden>
      ${section('sec-feedback', 'Comments', `${(draft.comments || []).length} saved`, `${thread(draft)}<label for="comment">Your comment</label><textarea id="comment"></textarea><div class="workspace-actions"><button id="save-comment">Save comment</button><button id="discard-comment">Discard unsaved text</button><span id="comment-msg" role="status"></span></div>`, true, '', 'human')}
      ${section('sec-history', 'Previous results', `${Math.max(0, (draft.sequences || []).length - 1)} results`, (draft.sequences || []).slice(0, -1).reverse().map((s, i) => `<details id="history-${i}"><summary>${esc(s.proposed_at || 'Undated')} · ${esc(s.source)} · historical result</summary>${sequenceBlock(s, draft.agreement, s.source, draft.day_count)}</details>`).join('') || '<p>No earlier result.</p>', false, '', '')}
      ${section('sec-layers', 'Run history', `${(draft.runs || []).length} runs`, runsBody(draft), false, '', '')}
      ${section('sec-notes', 'Machine notes', `${(draft.notes || []).length} notes`, notesBody(draft), false, '', 'model')}
      ${section('sec-move', 'Worklist and reply drafts', currentRow?.status || 'No worklist row', `<div id="wl-move">${window.DeskWorklist ? DeskWorklist.moveHtml(currentRow) + DeskWorklist.replyHtml(lastBuild) : ''}</div>`, false, '', 'human')}
      ${section('sec-send', 'Queued replies and changes · all requests', `${stagedRows.length} queued${stagedRows.some(s => s.conflict) ? ' · conflict' : ''}`, `<div id="wl-send-box">${window.DeskWorklist ? DeskWorklist.sendHtml(stagedRows) : ''}</div>`, Boolean(stagedRows.length), '', 'human')}
      ${legend()}
    </section>`;
  detail.querySelectorAll('#sec-history .generate').forEach(button => { button.parentElement.textContent = 'Historical result. Build from the current Overview result.'; });
  $('comment').value = saved?.comment || '';
  if (saved?.open) detail.querySelectorAll('details[id]').forEach(e => { e.open = saved.open.includes(e.id); });
  $('comment').addEventListener('input', rememberWorkspace);
  $('discard-comment').addEventListener('click', () => { $('comment').value = ''; rememberWorkspace(); });
  $('save-comment').addEventListener('click', saveComment);
  $('group-quote-form').addEventListener('submit', event => { event.preventDefault(); loadGroupQuote(true); });
  $('group-quote-form').addEventListener('input', () => {
    $('group-quote-status').textContent = 'Options changed. Save and calculate to update the prices.';
    $('group-quote-result').dataset.outdated = 'true';
  });
  detail.querySelector('.run-offer').addEventListener('click', recalculateRules);
  detail.querySelector('.generate').addEventListener('click', e => generate(e.currentTarget.dataset.source));
  $('back-requests').addEventListener('click', () => showRequestList(true));
  detail.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => selectWorkspaceView(button.dataset.view, button.dataset.target, true)));
  if (window.DeskWorklist) {
    DeskWorklist.wireMove($('wl-move'), currentRow, reloadStaged);
    DeskWorklist.wireSend($('wl-send-box'), reloadStaged);
    DeskWorklist.wireReply($('wl-move'), lastBuild, currentRow, reloadStaged);
  }
  $('sec-rules').addEventListener('toggle', () => { if ($('sec-rules').open && !$('rule-books').dataset.loaded) { $('rule-books').dataset.loaded = 'true'; loadRuleBooks(); } });
  $('sec-layers').addEventListener('toggle', () => { if ($('sec-layers').open) detail.querySelectorAll('.steps[data-run]').forEach(loadSteps); });
  applyWorkspaceView();
  if ($('sec-rules').open) { $('rule-books').dataset.loaded = 'true'; loadRuleBooks(); }
  detail.scrollTop = sameDraft ? saved?.scroll || 0 : 0;
}

function applyWorkspaceView() {
  document.body.classList.toggle('show-workspace', !workspaceList);
  for (const key of Object.keys(workspaceViews)) {
    if ($(`view-${key}`)) $(`view-${key}`).hidden = key !== workspaceView;
  }
  document.querySelectorAll('.workspace-nav [data-view]').forEach(button => {
    if (button.dataset.view === workspaceView) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  if (workspaceView === 'pricing' && !workspaceList && $('group-quote-form') && !$('group-quote-form').dataset.loaded) loadGroupQuote();
}

function groupQuoteHtml(quote) {
  const dollars = amount => `$${Number(amount).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  const priceCell = (row, vehicle) => `${dollars(row[vehicle])}${row.revenue_checks?.[vehicle]?.increase_per_person > 0 ? `<br><small>Raised from ${dollars(row.calculated_prices[vehicle])}</small>` : ''}`;
  return `<h3>${esc(quote.num_days)} days / ${esc(quote.num_nights)} nights</h3>
    <p>${esc(quote.basis_label)}${quote.basis_is_operations_variant ? ' · Operations planning variant. The Overview proposal and its document checks remain separate.' : ''}</p>
    <p>${esc(quote.options.office_markup_percent)}% office + ${esc(quote.options.margin_markup_percent)}% margin, compounded: cost × ${esc(quote.multiplier)}.</p>
    <div class="quote-table-wrap"><table class="quote-table"><caption>USD per paying guest · ${esc(quote.hotel_tier)} · twin sharing</caption>
      <thead><tr><th scope="col">Paying guests + FOC</th><th scope="col">Coaster</th><th scope="col">VIP coach</th></tr></thead>
      <tbody>${quote.rows.map(row => `<tr><th scope="row">${esc(row.paying_min === row.paying_max ? row.paying_min : `${row.paying_min}–${row.paying_max}`)} + ${esc(row.foc)} FOC</th><td>${priceCell(row, 'TOYOTA_COASTER')}</td><td>${priceCell(row, 'VIP_BUS')}</td></tr>`).join('')}</tbody></table></div>
    <p>The FOC traveller’s room, transport, transfers and entry costs are shared among the paying guests. First, each range covers its highest calculated per-person cost, rounded up to $25. The second check raises prices where needed to protect total revenue.</p>
    ${groupRevenueHtml(quote, dollars)}
    <p>Single supplement: ${dollars(quote.single_supplement)}${quote.options.single_supplement_override === null ? ' (calculated)' : ' (fixed override)'}. ${esc(quote.guide_days)} guide days; ${esc(quote.transport_days)} tour vehicle days.</p>
    <p>Vehicle rates: Coaster ${dollars(quote.vehicle_daily_rates.TOYOTA_COASTER)}/day; VIP coach ${dollars(quote.vehicle_daily_rates.VIP_BUS)}/day.</p>
    <p>Hotel nights: ${Object.entries(quote.nights_by_city).map(([city, nights]) => `${esc(city)} ${esc(nights)}`).join(' · ')}.</p>
    <details class="sec"><summary>Operating checks and pricing assumptions (${quote.warnings.length})</summary><ul>${quote.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></details>
    <details class="sec"><summary>Full itinerary used for these prices</summary><ol class="day-list">${quote.days.map(day => `<li><strong>Day ${esc(day.number)} · ${esc(day.date || '')} · ${esc(day.title)}</strong><p class="quote-day-text">${esc(day.text)}</p><p>Overnight: ${esc(day.overnight_city || 'None · departure')}</p></li>`).join('')}</ol></details>`;
}

function groupRevenueHtml(quote, dollars) {
  const confirmation = quote.revenue_confirmation;
  if (!confirmation?.passed) return '<p class="warn">Revenue confirmation is unavailable or failed. Recalculate before using these prices.</p>';
  return `<p><strong>Revenue check passed.</strong> At its minimum paying headcount, each higher band receives at least ${dollars(confirmation.minimum_increase_usd)} more than the preceding band at its maximum headcount. FOC travellers do not count as revenue.</p>
    <details class="sec"><summary>Revenue confirmation details</summary>${[['TOYOTA_COASTER', 'Coaster'], ['VIP_BUS', 'VIP coach']].map(([vehicle, label]) => `<div class="quote-table-wrap"><table class="quote-table"><caption>${label} · USD received from paying guests</caption><thead><tr><th scope="col">Paying guests</th><th scope="col">Total received</th><th scope="col">Previous band maximum</th><th scope="col">Increase at minimum</th></tr></thead><tbody>${quote.rows.map(row => {
      const check = row.revenue_checks[vehicle];
      return `<tr><th scope="row">${esc(row.paying_min)}${row.paying_max === row.paying_min ? '' : `–${esc(row.paying_max)}`}</th><td>${dollars(check.minimum_revenue)}–${dollars(check.maximum_revenue)}</td><td>${check.previous_maximum_revenue === null ? 'First band' : dollars(check.previous_maximum_revenue)}</td><td>${check.revenue_increase === null ? '—' : dollars(check.revenue_increase)}</td></tr>`;
    }).join('')}</tbody></table></div>`).join('')}</details>`;
}

async function loadGroupQuote(save = false) {
  const form = $('group-quote-form');
  if (!current || !form || form.dataset.busy) return;
  const draftId = current.draft_id;
  form.dataset.loaded = 'true';
  form.dataset.busy = 'true';
  const controls = [...form.querySelectorAll('input, button')];
  const options = save ? { omit_final_night: $('quote-omit-night').checked,
    office_markup_percent: Number($('quote-office').value), margin_markup_percent: Number($('quote-margin').value),
    single_supplement_override: $('quote-single').value === '' ? null : Number($('quote-single').value) } : null;
  controls.forEach(control => { control.disabled = true; });
  $('group-quote-status').textContent = save ? 'Saving and calculating…' : 'Loading group prices…';
  try {
    const quote = await api(`/api/itinerary/drafts/${encodeURIComponent(draftId)}/group-quote`,
      save ? { method: 'POST', body: JSON.stringify(options) } : undefined);
    if (current?.draft_id !== draftId || $('group-quote-form') !== form) return;
    $('quote-omit-night').checked = quote.options.omit_final_night;
    $('quote-office').value = quote.options.office_markup_percent;
    $('quote-margin').value = quote.options.margin_markup_percent;
    $('quote-single').value = quote.options.single_supplement_override ?? '';
    $('group-quote-result').innerHTML = groupQuoteHtml(quote);
    delete $('group-quote-result').dataset.outdated;
    $('group-quote-status').textContent = save ? 'Options saved. Planning estimate updated.' : 'Planning estimate loaded.';
  } catch (error) {
    if (current?.draft_id === draftId && $('group-quote-form') === form) {
      $('group-quote-status').textContent = `Prices could not be calculated. ${error.message}`;
    }
  } finally {
    delete form.dataset.busy;
    controls.forEach(control => { control.disabled = false; });
  }
}

function selectWorkspaceView(view, target, push = false) {
  rememberWorkspace();
  workspaceView = Object.hasOwn(workspaceViews, view) ? view : 'overview';
  workspaceList = false;
  applyWorkspaceView();
  writeFiltersToUrl(push);
  const node = target ? $(target) : $('workspace-title');
  if (node) {
    if (node.tagName === 'DETAILS') node.open = true;
    node.scrollIntoView({ block: 'nearest' });
    (node.querySelector('summary') || node).focus({ preventScroll: true });
  }
  rememberWorkspace();
}

function showRequestList(push = false) {
  rememberWorkspace();
  openRequestSerial++;
  workspaceList = true;
  applyWorkspaceView();
  writeFiltersToUrl(push);
  $('queue').scrollTop = queuePosition;
  $('filter-search')?.focus({ preventScroll: true });
}

function initializeWorkspace() {
  $('queue').addEventListener('scroll', () => { queuePosition = $('queue').scrollTop; });
  window.addEventListener('beforeunload', event => {
    rememberWorkspace();
    if ([...draftPresentation.values()].some(state => state.comment)) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('popstate', async () => {
    rememberWorkspace();
    const asked = readFiltersFromUrl();
    renderFilters(); renderQueue();
    if (!asked || workspaceList) { showRequestList(); return; }
    const view = workspaceView;
    await openRow('', asked, false);
    selectWorkspaceView(view);
  });
}
