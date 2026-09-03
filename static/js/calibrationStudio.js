/**
 * static/js/calibrationStudio.js
 * Dedicated Focus Studio for Taxonomy & Rule Calibration
 * 
 * Features:
 * - 100-email sampling and multi-category assignment (up to 3)
 * - Category management: list, add, and full deletion with cascade
 * - Up to 10 extracted rule parameters per row with instant edit/delete
 * - Continuous debounced auto-save to SQLite calibration_drafts table
 * - Inline row comments and category notes
 * - Full-corpus Agent Pass (Phase 2 evaluation on all 600+ emails)
 */

(function () {
  'use strict';

  // --- State ---
  const state = {
    stage: 'draft',
    categories: [],
    emails: [],
    totalCorpusEmails: 0,
    matchedUnique: 0,
    unassignedCount: 0,
    filterText: '',
    filterCat: '',
    filterUnassigned: false,
    saveTimer: null,
    isSaving: false,
    hasAgentPassed: false,
  };

  // --- DOM Elements ---
  const dom = {
    catList: document.getElementById('category-list-container'),
    emailFeed: document.getElementById('email-feed-container'),
    catPanelCount: document.getElementById('cat-panel-count'),
    catFilterSelect: document.getElementById('cat-filter-select'),
    unassignedToggle: document.getElementById('unassigned-filter-toggle'),
    searchInput: document.getElementById('email-search-input'),
    filterCounter: document.getElementById('filter-counter'),
    syncDot: document.getElementById('sync-dot'),
    syncText: document.getElementById('sync-text'),
    btnSaveDraft: document.getElementById('btn-save-draft'),
    btnResetDraft: document.getElementById('btn-reset-draft'),
    btnAddCategory: document.getElementById('btn-add-category'),
    btnAgentPass: document.getElementById('btn-agent-pass'),
    btnApplyTaxonomy: document.getElementById('btn-apply-taxonomy'),
    footerMatchedCount: document.getElementById('footer-matched-count'),
    modalContainer: document.getElementById('modal-container'),
  };

  // --- Utility Helpers ---
  function esc(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function getActiveCategories() {
    return state.categories.filter(c => !c.is_deleted);
  }

  function getCategoryBySlug(slug) {
    return state.categories.find(c => c.slug === slug && !c.is_deleted);
  }

  // --- Auto-Save Mechanism ---
  function triggerAutoSave(immediate = false) {
    if (state.saveTimer) {
      clearTimeout(state.saveTimer);
    }
    setSyncStatus('saving', 'Saving draft...');

    if (immediate) {
      executeSaveDraft();
    } else {
      state.saveTimer = setTimeout(executeSaveDraft, 1200);
    }
  }

  function setSyncStatus(status, text) {
    if (!dom.syncDot || !dom.syncText) return;
    if (status === 'saving') {
      dom.syncDot.className = 'sync-dot saving';
      dom.syncText.textContent = text || 'Saving draft...';
    } else if (status === 'saved') {
      dom.syncDot.className = 'sync-dot';
      dom.syncText.textContent = text || 'Draft Synced';
    } else if (status === 'error') {
      dom.syncDot.className = 'sync-dot';
      dom.syncDot.style.backgroundColor = 'var(--accent-red)';
      dom.syncText.textContent = text || 'Sync Failed';
    }
  }

  async function executeSaveDraft() {
    if (state.isSaving) return;
    state.isSaving = true;

    try {
      const payload = {
        stage: state.stage || 'draft',
        categories: state.categories,
        emails: state.emails,
      };

      const res = await fetch('/api/organisers/calibrate/draft', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      setSyncStatus('saved', `Draft Saved at ${timeStr}`);
    } catch (err) {
      console.error('Draft save failed:', err);
      setSyncStatus('error', 'Draft Save Error');
    } finally {
      state.isSaving = false;
    }
  }

  // --- Initial Data Load ---
  async function loadDraft() {
    setSyncStatus('saving', 'Loading 100-email draft...');
    try {
      const res = await fetch('/api/organisers/calibrate/draft');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      state.stage = data.stage || 'draft';
      state.categories = data.categories || [];
      state.emails = data.emails || [];
      state.totalCorpusEmails = data.total_corpus_emails || 0;
      state.matchedUnique = data.matched_unique || 0;
      state.unassignedCount = data.unassigned_count || 0;

      if (state.stage === 'agent_evaluated') {
        state.hasAgentPassed = true;
        if (dom.btnApplyTaxonomy) dom.btnApplyTaxonomy.style.display = 'inline-flex';
      }

      setSyncStatus('saved', 'Draft Synced');
      renderAll();
    } catch (err) {
      console.error('Failed loading draft:', err);
      setSyncStatus('error', 'Error loading draft');
      if (dom.emailFeed) {
        dom.emailFeed.innerHTML = `<div style="padding:40px;text-align:center;color:var(--accent-red);">Failed loading calibration draft: ${esc(err.message)}</div>`;
      }
    }
  }

  // --- Render All ---
  function renderAll() {
    renderCategoryPanel();
    renderCategoryFilterSelect();
    renderEmailFeed();
    updateFooterStats();
  }

  // --- Render Category Manager (Left Panel) ---
  function renderCategoryPanel() {
    if (!dom.catList) return;
    const activeCats = getActiveCategories();
    if (dom.catPanelCount) {
      dom.catPanelCount.textContent = `Categories (${activeCats.length})`;
    }

    if (activeCats.length === 0) {
      dom.catList.innerHTML = `<div style="padding:20px;text-align:center;color:var(--text-secondary);font-size:12px;">No active categories. Create one above.</div>`;
      return;
    }

    dom.catList.innerHTML = activeCats.map(cat => {
      const ruleCount = (cat.rules.keywords || []).length + (cat.rules.domains || []).length + (cat.rules.senders || []).length;
      return `
        <div class="cat-card" data-slug="${esc(cat.slug)}">
          <div class="cat-card-header">
            <div class="cat-name-box">
              <span class="cat-dot" style="background-color: ${esc(cat.color || '#61afef')};"></span>
              <span class="cat-name">${esc(cat.name)}</span>
            </div>
            <button class="btn-danger-outline btn-del-category" data-slug="${esc(cat.slug)}" title="Delete entire category">
              Delete
            </button>
          </div>
          <div class="cat-stats-row">
            <span class="cat-badge">${cat.coverage_count || 0} live matches</span>
            <span>${ruleCount} rules active</span>
          </div>
          <textarea class="cat-comment-box" data-slug="${esc(cat.slug)}" placeholder="Category notes / instructions...">${esc(cat.comments || '')}</textarea>
        </div>
      `;
    }).join('');

    // Attach listeners
    dom.catList.querySelectorAll('.btn-del-category').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const slug = e.currentTarget.getAttribute('data-slug');
        handleDeleteCategory(slug);
      });
    });

    dom.catList.querySelectorAll('.cat-comment-box').forEach(txt => {
      txt.addEventListener('input', (e) => {
        const slug = e.currentTarget.getAttribute('data-slug');
        const cat = getCategoryBySlug(slug);
        if (cat) {
          cat.comments = e.currentTarget.value;
          triggerAutoSave();
        }
      });
    });
  }

  function renderCategoryFilterSelect() {
    if (!dom.catFilterSelect) return;
    const activeCats = getActiveCategories();
    const curVal = dom.catFilterSelect.value;

    let html = `<option value="">All Categories</option>`;
    activeCats.forEach(c => {
      html += `<option value="${esc(c.slug)}" ${curVal === c.slug ? 'selected' : ''}>${esc(c.name)}</option>`;
    });
    dom.catFilterSelect.innerHTML = html;
  }

  // --- Category Deletion Cascade ---
  function handleDeleteCategory(slug) {
    const cat = getCategoryBySlug(slug);
    if (!cat) return;

    const confirmed = confirm(
      `Are you sure you want to delete the category "${cat.name}"?\n\nThis will remove it from all 100 emails and delete it from your active taxonomy.`
    );
    if (!confirmed) return;

    // Mark as deleted
    cat.is_deleted = true;

    // Cascade remove from all email assigned_categories
    state.emails.forEach(e => {
      if (e.assigned_categories && e.assigned_categories.includes(slug)) {
        e.assigned_categories = e.assigned_categories.filter(s => s !== slug);
      }
    });

    triggerAutoSave(true);
    renderAll();
  }

  // --- Add New Category ---
  function handleAddCategory() {
    const name = prompt('Enter new category name:');
    if (!name || !name.trim()) return;

    const cleanName = name.trim();
    const baseSlug = cleanName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || `cat-${Date.now()}`;
    let slug = baseSlug;
    let counter = 1;
    while (state.categories.some(c => c.slug === slug && !c.is_deleted)) {
      slug = `${baseSlug}-${counter++}`;
    }

    const newCat = {
      id: null,
      slug: slug,
      name: cleanName,
      description: '',
      category_group: 'operations',
      icon: 'briefcase',
      color: '#61afef',
      priority: 'normal',
      rules: { senders: [], domains: [], keywords: [] },
      comments: '',
      is_deleted: false,
      coverage_count: 0,
    };

    state.categories.push(newCat);
    triggerAutoSave(true);
    renderAll();
  }

  // --- Render Email Workbench Feed ---
  function renderEmailFeed() {
    if (!dom.emailFeed) return;

    const activeCats = getActiveCategories();
    const filtered = state.emails.filter(e => {
      // Text Search
      if (state.filterText) {
        const query = state.filterText.toLowerCase();
        const inSubj = (e.subject || '').toLowerCase().includes(query);
        const inSender = (e.from_name || '').toLowerCase().includes(query) || (e.from_address || '').toLowerCase().includes(query);
        const inRules = (e.extracted_parameters || []).some(p => (p.value || '').toLowerCase().includes(query));
        const inComment = (e.comments || '').toLowerCase().includes(query);
        if (!inSubj && !inSender && !inRules && !inComment) return false;
      }

      // Unassigned Only
      if (state.filterUnassigned) {
        if (e.assigned_categories && e.assigned_categories.length > 0) return false;
      }

      // Category Filter
      if (state.filterCat) {
        if (!e.assigned_categories || !e.assigned_categories.includes(state.filterCat)) return false;
      }

      return true;
    });

    if (dom.filterCounter) {
      dom.filterCounter.textContent = `Showing ${filtered.length} of ${state.emails.length} emails`;
    }

    if (filtered.length === 0) {
      dom.emailFeed.innerHTML = `<div style="padding:60px;text-align:center;color:var(--text-secondary);">No emails match your active filters.</div>`;
      return;
    }

    dom.emailFeed.innerHTML = filtered.map(e => {
      const emailKey = `${e.account_key}:${e.uid}`;
      const isSent = (e.folder || '').toLowerCase().includes('sent');
      const assignedCats = (e.assigned_categories || []).map(slug => getCategoryBySlug(slug)).filter(Boolean);
      const unassignedCats = activeCats.filter(c => !e.assigned_categories || !e.assigned_categories.includes(c.slug));
      const paramList = e.extracted_parameters || [];

      return `
        <article class="email-card" data-key="${esc(emailKey)}">
          <!-- Header -->
          <div class="email-header-row">
            <div class="email-sender-meta">
              <span class="folder-badge ${isSent ? 'sent' : ''}">${esc(e.folder || 'INBOX')}</span>
              <span class="email-from-name">${esc(e.from_name || e.from_address || 'Unknown')}</span>
              <span class="email-from-addr">&lt;${esc(e.from_address || '')}&gt;</span>
            </div>
            <span class="email-date">${esc(e.date_iso ? e.date_iso.slice(0, 10) : '')}</span>
          </div>

          <!-- Subject -->
          <div class="email-subject">${esc(e.subject || '(No Subject)')}</div>

          <!-- Email Content / Message Body -->
          <div class="email-content-box">
            <div class="email-content-header">
              <span class="content-badge">Email Content / Message Body</span>
              <button class="btn-toggle-content btn-toggle-email-content" data-key="${esc(emailKey)}" data-acct="${esc(e.account_key)}" data-uid="${esc(e.uid)}" data-folder="${esc(e.folder || 'INBOX')}">
                <span>View Full Message</span> ▾
              </button>
            </div>
            <div class="email-snippet-text" id="snippet-${esc(e.account_key)}-${esc(e.uid)}">${e.snippet ? esc(e.snippet) : '<span style="color:var(--text-muted);font-style:italic;">No summary cached — click "View Full Message" to load from mail server</span>'}</div>
            <div class="email-full-drawer" id="drawer-${esc(e.account_key)}-${esc(e.uid)}" style="display:none;"></div>
          </div>

          <!-- Assigned Categories (Up to 3) -->
          <div class="email-categories-bar">
            <span class="bar-label">Categories:</span>
            ${assignedCats.map(c => `
              <span class="category-chip" style="border-color:${esc(c.color || '#58a6ff')};color:${esc(c.color || '#79c0ff')};">
                ${esc(c.name)}
                <span class="chip-del btn-del-cat-assignment" data-key="${esc(emailKey)}" data-slug="${esc(c.slug)}" title="Remove category">&times;</span>
              </span>
            `).join('')}

            ${assignedCats.length < 3 && unassignedCats.length > 0 ? `
              <select class="add-cat-select btn-add-cat-select" data-key="${esc(emailKey)}">
                <option value="">+ Add Category (${assignedCats.length}/3)</option>
                ${unassignedCats.map(c => `<option value="${esc(c.slug)}">${esc(c.name)}</option>`).join('')}
              </select>
            ` : ''}
          </div>

          <!-- Extracted Rule Parameters (Up to 10) -->
          <div class="email-parameters-bar">
            <span class="bar-label">Parameters:</span>
            ${paramList.map((p, idx) => `
              <span class="param-chip ${esc(p.type)}">
                <strong>${esc(p.type[0])}:</strong> ${esc(p.value)}
                <span class="param-del btn-del-param" data-key="${esc(emailKey)}" data-idx="${idx}" title="Remove rule token">&times;</span>
              </span>
            `).join('')}

            ${paramList.length < 10 ? `
              <button class="btn-add-rule btn-add-param" data-key="${esc(emailKey)}">
                + Add Rule
              </button>
            ` : ''}

            <span class="rules-counter">${paramList.length}/10 rules</span>
          </div>

          <!-- Notes & Reasoning -->
          <div class="email-notes-row">
            <textarea class="row-comment-box" data-key="${esc(emailKey)}" placeholder="Feedback / Row notes (e.g. keep in Receipts only, exclude from Tour Ops)...">${esc(e.comments || '')}</textarea>
            <div class="row-reasoning-box">
              <div class="row-reasoning-label">Initial AI Justification</div>
              <div>${esc(e.reasoning || 'Extracted from correspondence patterns.')}</div>
            </div>
          </div>
        </article>
      `;
    }).join('');

    wireEmailEvents();
  }

  function wireEmailEvents() {
    if (!dom.emailFeed) return;

    // Toggle Email Full Content Drawer
    dom.emailFeed.querySelectorAll('.btn-toggle-email-content').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const button = e.currentTarget;
        const acct = button.getAttribute('data-acct');
        const uid = button.getAttribute('data-uid');
        const folder = button.getAttribute('data-folder');
        const drawer = document.getElementById(`drawer-${acct}-${uid}`);
        if (!drawer) return;

        if (drawer.style.display === 'block') {
          drawer.style.display = 'none';
          button.innerHTML = '<span>View Full Message</span> ▾';
          return;
        }

        drawer.style.display = 'block';
        button.innerHTML = '<span>Collapse Message</span> ▴';

        if (!drawer.getAttribute('data-loaded')) {
          drawer.innerHTML = `
            <div style="padding:12px;color:var(--text-secondary);display:flex;align-items:center;gap:8px;">
              <span class="sync-dot saving"></span> Loading full message body from mail server...
            </div>
          `;
          try {
            const res = await fetch(`/api/organisers/calibrate/email-content/${encodeURIComponent(acct)}/${encodeURIComponent(uid)}?folder=${encodeURIComponent(folder)}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            drawer.setAttribute('data-loaded', 'true');

            const emailObj = state.emails.find(m => m.account_key === acct && m.uid === uid);
            if (emailObj && !emailObj.snippet) {
              emailObj.snippet = data.summary || (data.body ? data.body.slice(0, 250) : '');
              const snipEl = document.getElementById(`snippet-${acct}-${uid}`);
              if (snipEl && emailObj.snippet) snipEl.textContent = emailObj.snippet;
              triggerAutoSave();
            }

            drawer.innerHTML = `
              <div class="email-drawer-meta">
                <div><strong>To:</strong> ${esc(data.to || '(none)')} ${data.cc ? `&nbsp;|&nbsp; <strong>Cc:</strong> ${esc(data.cc)}` : ''}</div>
                <div><strong>Date:</strong> ${esc(data.date || '')} &nbsp;|&nbsp; <strong>Folder:</strong> ${esc(data.folder || 'INBOX')}</div>
                ${data.summary ? `<div style="margin-top:4px;padding:6px 10px;background:rgba(88,166,255,0.1);border-left:2px solid var(--accent-blue);border-radius:4px;color:var(--text-main);"><strong>AI Brief:</strong> ${esc(data.summary)}</div>` : ''}
              </div>
              <div class="email-drawer-body">${esc(data.body || '(Empty body)')}</div>
            `;
          } catch (err) {
            drawer.innerHTML = `<div style="color:var(--accent-red);padding:10px;">Failed to load email body: ${esc(err.message)}</div>`;
          }
        }
      });
    });

    // Unassign Category
    dom.emailFeed.querySelectorAll('.btn-del-cat-assignment').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const key = e.currentTarget.getAttribute('data-key');
        const slug = e.currentTarget.getAttribute('data-slug');
        const email = state.emails.find(m => `${m.account_key}:${m.uid}` === key);
        if (email && email.assigned_categories) {
          email.assigned_categories = email.assigned_categories.filter(s => s !== slug);
          triggerAutoSave();
          renderEmailFeed();
        }
      });
    });

    // Add Category
    dom.emailFeed.querySelectorAll('.btn-add-cat-select').forEach(sel => {
      sel.addEventListener('change', (e) => {
        const key = e.currentTarget.getAttribute('data-key');
        const slug = e.currentTarget.value;
        if (!slug) return;
        const email = state.emails.find(m => `${m.account_key}:${m.uid}` === key);
        if (email) {
          if (!email.assigned_categories) email.assigned_categories = [];
          if (email.assigned_categories.length < 3 && !email.assigned_categories.includes(slug)) {
            email.assigned_categories.push(slug);
            triggerAutoSave();
            renderEmailFeed();
          }
        }
      });
    });

    // Delete Parameter Tag
    dom.emailFeed.querySelectorAll('.btn-del-param').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const key = e.currentTarget.getAttribute('data-key');
        const idx = parseInt(e.currentTarget.getAttribute('data-idx'), 10);
        const email = state.emails.find(m => `${m.account_key}:${m.uid}` === key);
        if (email && email.extracted_parameters && email.extracted_parameters[idx]) {
          email.extracted_parameters.splice(idx, 1);
          triggerAutoSave();
          renderEmailFeed();
        }
      });
    });

    // Add Parameter Tag
    dom.emailFeed.querySelectorAll('.btn-add-param').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const key = e.currentTarget.getAttribute('data-key');
        const email = state.emails.find(m => `${m.account_key}:${m.uid}` === key);
        if (!email) return;

        if (!email.extracted_parameters) email.extracted_parameters = [];
        if (email.extracted_parameters.length >= 10) {
          alert('Maximum 10 parameter tokens reached for this row.');
          return;
        }

        const input = prompt('Enter rule token (prefix with d: for domain, s: for sender, or k: for keyword):\n\nExample:\nk: invoice\nd: stripe.com\ns: Google Play');
        if (!input || !input.trim()) return;

        let type = 'keyword';
        let val = input.trim();
        if (val.startsWith('d:') || val.startsWith('domain:')) {
          type = 'domain';
          val = val.split(':')[1].trim();
        } else if (val.startsWith('s:') || val.startsWith('sender:')) {
          type = 'sender';
          val = val.split(':')[1].trim();
        } else if (val.startsWith('k:') || val.startsWith('keyword:')) {
          type = 'keyword';
          val = val.split(':')[1].trim();
        }

        if (!val) return;

        email.extracted_parameters.push({ type: type, value: val });
        triggerAutoSave();
        renderEmailFeed();
      });
    });

    // Row Comments Input (Debounced)
    dom.emailFeed.querySelectorAll('.row-comment-box').forEach(txt => {
      txt.addEventListener('input', (e) => {
        const key = e.currentTarget.getAttribute('data-key');
        const email = state.emails.find(m => `${m.account_key}:${m.uid}` === key);
        if (email) {
          email.comments = e.currentTarget.value;
          triggerAutoSave();
        }
      });
    });
  }

  function updateFooterStats() {
    if (dom.footerMatchedCount) {
      const assignedCount = state.emails.filter(e => e.assigned_categories && e.assigned_categories.length > 0).length;
      dom.footerMatchedCount.textContent = `${assignedCount} of ${state.emails.length}`;
    }
  }

  // --- Phase 2: Agent Pass Execution ---
  async function runAgentPass() {
    if (!confirm('Run Agent Pass?\n\nThe system will evaluate your refined taxonomy across every email in the database and present the full corpus breakdown.')) {
      return;
    }

    setSyncStatus('saving', 'Agent evaluating full corpus...');
    if (dom.btnAgentPass) {
      dom.btnAgentPass.disabled = true;
      dom.btnAgentPass.textContent = 'Agent evaluating 600+ emails...';
    }

    try {
      const payload = {
        days: 14,
        categories: getActiveCategories(),
      };

      const res = await fetch('/api/organisers/calibrate/agent-pass', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      state.stage = 'agent_evaluated';
      state.hasAgentPassed = true;
      setSyncStatus('saved', 'Agent Pass Complete');

      showAgentPassModal(data);
      if (dom.btnApplyTaxonomy) {
        dom.btnApplyTaxonomy.style.display = 'inline-flex';
      }
    } catch (err) {
      console.error('Agent pass error:', err);
      alert(`Agent evaluation failed: ${err.message}`);
      setSyncStatus('error', 'Agent Pass Error');
    } finally {
      if (dom.btnAgentPass) {
        dom.btnAgentPass.disabled = false;
        dom.btnAgentPass.textContent = '✓ All Categories Look Correct (Run Agent Pass)';
      }
    }
  }

  function showAgentPassModal(data) {
    if (!dom.modalContainer) return;

    const multi = data.multi_category_breakdown || {};
    const coverage = data.category_coverage || {};

    const coverageRows = Object.entries(coverage).map(([slug, count]) => {
      const cat = getCategoryBySlug(slug);
      const name = cat ? cat.name : slug;
      return `<tr><td style="padding:6px 12px;font-weight:600;">${esc(name)}</td><td style="padding:6px 12px;text-align:right;color:var(--accent-blue);font-weight:700;">${count} emails</td></tr>`;
    }).join('');

    dom.modalContainer.innerHTML = `
      <div class="studio-modal-overlay">
        <div class="studio-modal-card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <h2 style="font-size:18px;font-weight:700;color:var(--text-main);">Corpus-Wide Agent Evaluation Preview</h2>
            <button id="modal-close-btn" style="background:none;border:none;color:var(--text-secondary);font-size:20px;cursor:pointer;">&times;</button>
          </div>

          <p style="font-size:13px;color:var(--text-secondary);line-height:1.5;">
            The agent evaluated all <strong>${data.total_corpus_emails} emails</strong> in your active window using your calibrated rules and multi-category specifications.
          </p>

          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;text-align:center;">
            <div style="background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:8px;padding:12px;">
              <div style="font-size:22px;font-weight:800;color:var(--accent-green);">${data.matched_unique}</div>
              <div style="font-size:11px;color:var(--text-secondary);text-transform:uppercase;">Matched Emails</div>
            </div>
            <div style="background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:8px;padding:12px;">
              <div style="font-size:22px;font-weight:800;color:var(--accent-amber);">${data.unassigned_count}</div>
              <div style="font-size:11px;color:var(--text-secondary);text-transform:uppercase;">Unassigned</div>
            </div>
            <div style="background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:8px;padding:12px;">
              <div style="font-size:22px;font-weight:800;color:var(--accent-purple);">${(multi['2_categories'] || 0) + (multi['3_categories'] || 0)}</div>
              <div style="font-size:11px;color:var(--text-secondary);text-transform:uppercase;">Multi-Assigned</div>
            </div>
          </div>

          <div style="max-height:200px;overflow-y:auto;border:1px solid var(--border-subtle);border-radius:8px;background:var(--bg-canvas);">
            <table style="width:100%;border-collapse:collapse;font-size:13px;">
              <thead>
                <tr style="border-bottom:1px solid var(--border-subtle);color:var(--text-muted);text-align:left;">
                  <th style="padding:6px 12px;">Category</th>
                  <th style="padding:6px 12px;text-align:right;">Total Coverage</th>
                </tr>
              </thead>
              <tbody>
                ${coverageRows}
              </tbody>
            </table>
          </div>

          <div style="display:flex;justify-content:flex-end;gap:12px;margin-top:8px;">
            <button class="btn-secondary" id="modal-cancel-btn">Back to Workbench</button>
            <button class="btn-primary" id="modal-confirm-apply" style="background:#238636;">Confirm & Apply to Live System</button>
          </div>
        </div>
      </div>
    `;

    document.getElementById('modal-close-btn').addEventListener('click', () => dom.modalContainer.innerHTML = '');
    document.getElementById('modal-cancel-btn').addEventListener('click', () => dom.modalContainer.innerHTML = '');
    document.getElementById('modal-confirm-apply').addEventListener('click', () => {
      dom.modalContainer.innerHTML = '';
      applyTaxonomy();
    });
  }

  // --- Final Application ---
  async function applyTaxonomy() {
    const confirmed = confirm('Apply Taxonomy to Live System?\n\nThis will write the calibrated rules into your AI Work Organisers, reset the Overview cache, and update live triage.');
    if (!confirmed) return;

    setSyncStatus('saving', 'Applying taxonomy...');
    try {
      const payload = {
        categories: state.categories,
        clear_overview_cache: true,
      };

      const res = await fetch('/api/organisers/calibrate/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      alert(`Success! Taxonomy applied to live system.\n\nCreated: ${data.created || 0}\nUpdated: ${data.updated || 0}\nTotal Active Organisers: ${data.total_organisers || 0}`);
      setSyncStatus('saved', 'Applied to Live System');
      state.stage = 'applied';
    } catch (err) {
      console.error('Apply error:', err);
      alert(`Apply failed: ${err.message}`);
      setSyncStatus('error', 'Apply Failed');
    }
  }

  // --- Wire Top Controls ---
  function wireControls() {
    if (dom.searchInput) {
      dom.searchInput.addEventListener('input', (e) => {
        state.filterText = e.target.value.trim();
        renderEmailFeed();
      });
    }

    if (dom.catFilterSelect) {
      dom.catFilterSelect.addEventListener('change', (e) => {
        state.filterCat = e.target.value;
        renderEmailFeed();
      });
    }

    if (dom.unassignedToggle) {
      dom.unassignedToggle.addEventListener('change', (e) => {
        state.filterUnassigned = e.target.checked;
        renderEmailFeed();
      });
    }

    if (dom.btnSaveDraft) {
      dom.btnSaveDraft.addEventListener('click', () => triggerAutoSave(true));
    }

    if (dom.btnAddCategory) {
      dom.btnAddCategory.addEventListener('click', handleAddCategory);
    }

    if (dom.btnResetDraft) {
      dom.btnResetDraft.addEventListener('click', async () => {
        if (!confirm('Reset Draft to Fresh Baseline?\n\nAll current unsaved custom tags and row comments will be re-sampled from the live 100 emails.')) {
          return;
        }
        setSyncStatus('saving', 'Resetting draft...');
        try {
          const res = await fetch('/api/organisers/calibrate/draft/reset', { method: 'POST' });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          await loadDraft();
        } catch (err) {
          alert(`Reset failed: ${err.message}`);
          setSyncStatus('error', 'Reset Failed');
        }
      });
    }

    if (dom.btnAgentPass) {
      dom.btnAgentPass.addEventListener('click', runAgentPass);
    }

    if (dom.btnApplyTaxonomy) {
      dom.btnApplyTaxonomy.addEventListener('click', applyTaxonomy);
    }
  }

  // --- Initialization ---
  document.addEventListener('DOMContentLoaded', () => {
    wireControls();
    loadDraft();
  });

})();
