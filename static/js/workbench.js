// static/js/workbench.js
/**
 * WorkBench — the single operational surface.
 *
 * C2 (cockpit drilldown) on an S2 layered view host, per SYSTEM_RECORD Rev Y.
 * Overview is the home layer; cards and rows drill into Projects, Operations
 * or Organisers rendered as sibling layers on the same surface, with a back
 * stack wired to the History API so the Android back gesture pops one level
 * instead of dismissing the whole surface.
 *
 * The load-bearing property is that a layer beneath the top is never
 * re-rendered — it is hidden, not destroyed — so back restores scroll position
 * and filter state with no capture-and-replay machinery. That is what S1
 * (body-swap) could not give, and it is the reason all layers stay resident.
 *
 * This module owns the shell, the registry, the stack and the history
 * integration. It owns no view content: every pixel below the header comes
 * from a registered view's mount().
 */

import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const SHELL_ID = 'workbench-modal';
const HOME_VIEW_ID = 'home';

/** Below this width the shell fills the viewport; above it, it is a window. */
const PHONE_MAX_WIDTH = 768;

/** id -> view descriptor. Populated at module-eval time by each view module. */
const _views = new Map();

let _shell = null;
let _layerHost = null;
let _titleEl = null;
let _backBtn = null;
let _stylesInjected = false;

/** [{ viewId, params, layerEl }] — index 0 is home, last is the visible top. */
let _stack = [];
let _open = false;

let _escHandler = null;
let _popHandler = null;

// ---------------------------------------------------------------------------
// View registry
// ---------------------------------------------------------------------------

/**
 * Register a view. Called at module-eval time; renders nothing.
 *
 * Pre:  `id` is a non-empty string; `mount` and `unmount` are functions;
 *       `path` is a route app.py already serves, since the WorkBench adds none.
 * Post: the view is navigable by id. Re-registering an id replaces the
 *       descriptor — module reload during development must not duplicate.
 * Inv:  registration never touches the DOM.
 *
 * @param {object} descriptor
 * @param {string} descriptor.id
 * @param {string} descriptor.title           Shown in the shell header.
 * @param {string} descriptor.path            Existing route, e.g. '/operations'.
 * @param {string} [descriptor.icon]          Inline SVG markup.
 * @param {(container: HTMLElement, params: object) => void} descriptor.mount
 * @param {(container: HTMLElement) => void} descriptor.unmount
 * @param {(params: object) => string} [descriptor.queryFromParams]
 *        Record identity as a query string. Never a path segment: app.py
 *        registers exact-path SPA handlers with no catch-all, so
 *        `/projects/abc123` would 404 on a hard reload.
 * @param {(search: URLSearchParams) => object} [descriptor.paramsFromQuery]
 */
export function registerView(descriptor) {
  if (!descriptor || !descriptor.id) return;
  if (typeof descriptor.mount !== 'function' || typeof descriptor.unmount !== 'function') {
    console.error(`[WorkBench] view "${descriptor.id}" needs both mount and unmount`);
    return;
  }
  _views.set(descriptor.id, descriptor);
}

/** Registered view descriptors, in registration order. Read-only. */
export function getRegisteredViews() {
  return Array.from(_views.values());
}

/** The view whose `path` matches, or null. Used to resolve a cold deep link. */
export function viewForPath(path) {
  for (const view of _views.values()) {
    if (view.path === path) return view;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const ICONS = {
  back: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>`,
  close: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
};

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const style = document.createElement('style');
  style.id = 'odysseus-workbench-styles';
  style.textContent = `
    .workbench-modal {
      position: fixed;
      top: 36px;
      left: 50%;
      transform: translateX(-50%);
      width: min(1320px, calc(100vw - 32px));
      height: min(880px, calc(100vh - 64px));
      max-height: calc(100vh - 48px);
      background: var(--panel, #1e2227);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      border-radius: 10px;
      box-shadow: 0 16px 48px rgba(0,0,0,0.5);
      z-index: 310;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-family: var(--font-family, system-ui, sans-serif);
      color: var(--fg, #abb2bf);
    }
    .workbench-modal.hidden { display: none; }

    /* Phone: fill the viewport. Above the breakpoint: a draggable window.
       Operations opened maximized while Projects and Overview opened windowed;
       the shell is one surface, so it picks by width instead. */
    @media (max-width: ${PHONE_MAX_WIDTH}px) {
      .workbench-modal {
        top: 0;
        left: 0;
        transform: none;
        width: 100vw;
        height: 100dvh;
        max-height: 100dvh;
        border: none;
        border-radius: 0;
      }
    }

    .workbench-header {
      padding: 8px 12px;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--bg, #282c34);
      user-select: none;
      flex-shrink: 0;
    }
    .workbench-title {
      font-weight: 600;
      font-size: 14px;
      color: var(--fg, #fff);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .workbench-header-actions {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .workbench-btn {
      background: rgba(255,255,255,0.06);
      border: 1px solid var(--border, rgba(255,255,255,0.1));
      color: var(--fg, #abb2bf);
      padding: 5px 9px;
      border-radius: 4px;
      font-size: 12px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: background 0.15s ease, border-color 0.15s ease;
    }
    .workbench-btn:hover {
      background: rgba(255,255,255,0.12);
      border-color: rgba(255,255,255,0.2);
      color: #fff;
    }
    .workbench-btn[hidden] { display: none; }

    .workbench-layers {
      flex: 1;
      position: relative;
      min-height: 0;
      display: flex;
      background: var(--bg, #181a1f);
    }
    .wb-layer {
      flex: 1;
      min-width: 0;
      min-height: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    /* .wb-layer sets display:flex, which outranks the UA rule for [hidden].
       Without this the "hidden" layers would still paint on top of each other. */
    .wb-layer[hidden] { display: none; }

    /* A module mounted into a layer keeps its own markup but gives up its
       window chrome: the shell owns position, size, close and minimize. */
    .wb-layer > .modal,
    .wb-layer > .overview-modal,
    .wb-layer > .organisers-modal {
      position: static;
      inset: auto;
      transform: none;
      width: 100%;
      height: 100%;
      max-width: none;
      max-height: none;
      margin: 0;
      border: none;
      border-radius: 0;
      box-shadow: none;
      background: transparent;
      z-index: auto;
      pointer-events: auto;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    /* style.css insets the desktop tool windows past the sidebar and rail
       (#projects-modal, #operations-modal et al. under a min-width media
       query). Those are id selectors, so the block above cannot outrank them
       on specificity alone — only a selector carrying an id can. Without this
       a layer renders one sidebar-width narrow than its shell. */
    .wb-layer > #projects-modal,
    .wb-layer > #operations-modal,
    .wb-layer > #overview-modal,
    .wb-layer > #organisers-modal {
      left: 0;
      top: 0;
      width: 100%;
      height: 100%;
      transition: none;
    }
    /* Same reason one level down: each module sizes its own window through an
       id-scoped rule of its own, which a class-only selector cannot beat.
       A layer fills its shell. */
    .wb-layer > #operations-modal > .modal-content,
    .wb-layer > #projects-modal > .modal-content {
      width: 100%;
      height: 100%;
      max-width: none;
      max-height: none;
    }
    .wb-layer > .modal > .modal-content {
      width: 100%;
      height: 100%;
      max-width: none;
      max-height: none;
      border: none;
      border-radius: 0;
      box-shadow: none;
      animation: none;
    }
    /* The shell's back and close replace each module's own dismiss control. */
    .wb-layer #ops-close,
    .wb-layer #proj-close-btn,
    .wb-layer #org-modal-close,
    .wb-layer #overview-close-btn,
    .wb-layer #overview-minimize-btn {
      display: none !important;
    }
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

function _buildShell() {
  if (_shell && document.body.contains(_shell)) return _shell;
  _injectStyles();

  _shell = document.createElement('div');
  _shell.id = SHELL_ID;
  _shell.className = 'workbench-modal';
  _shell.setAttribute('role', 'dialog');
  _shell.setAttribute('aria-label', 'WorkBench');
  _shell.innerHTML = `
    <div class="workbench-header" id="workbench-drag-header">
      <button class="workbench-btn" id="workbench-back-btn" title="Back" aria-label="Back">${ICONS.back}</button>
      <span class="workbench-title" id="workbench-title"></span>
      <div class="workbench-header-actions">
        <button class="workbench-btn" id="workbench-minimize-btn" title="Minimize">_</button>
        <button class="workbench-btn" id="workbench-close-btn" title="Close (Esc)">${ICONS.close}</button>
      </div>
    </div>
    <div class="workbench-layers" id="workbench-layers"></div>
  `;
  document.body.appendChild(_shell);

  _layerHost = _shell.querySelector('#workbench-layers');
  _titleEl = _shell.querySelector('#workbench-title');
  _backBtn = _shell.querySelector('#workbench-back-btn');

  const header = _shell.querySelector('#workbench-drag-header');
  makeWindowDraggable(_shell, { content: _shell, header });

  _backBtn.addEventListener('click', back);
  _shell.querySelector('#workbench-close-btn').addEventListener('click', closeWorkBench);
  _shell.querySelector('#workbench-minimize-btn').addEventListener('click', () => {
    Modals.minimize(SHELL_ID);
  });

  return _shell;
}

function _syncHeader() {
  const top = _stack[_stack.length - 1];
  const view = top ? _views.get(top.viewId) : null;
  if (_titleEl) _titleEl.textContent = (view && view.title) || 'WorkBench';
  // Back is offered at every depth: at depth 1 it closes, which is the same
  // gesture the Android back button performs there.
  if (_backBtn) _backBtn.title = _stack.length > 1 ? 'Back' : 'Close';
}

// ---------------------------------------------------------------------------
// Layer stack
// ---------------------------------------------------------------------------

/**
 * Mount `viewId` as a new top layer.
 *
 * Pre:  the shell exists and `viewId` is registered.
 * Post: depth is one greater; the new layer is visible; every layer below is
 *       hidden but structurally untouched.
 * Inv:  no layer below the top is ever re-rendered or unmounted.
 */
function _pushLayer(viewId, params) {
  const view = _views.get(viewId);
  if (!view) {
    console.error(`[WorkBench] no view registered as "${viewId}"`);
    return false;
  }
  const below = _stack[_stack.length - 1];
  if (below) below.layerEl.hidden = true;

  const layerEl = document.createElement('div');
  layerEl.className = 'wb-layer';
  layerEl.dataset.viewId = viewId;
  _layerHost.appendChild(layerEl);

  _stack.push({ viewId, params: params || {}, layerEl });
  try {
    view.mount(layerEl, params || {});
  } catch (err) {
    console.error(`[WorkBench] view "${viewId}" failed to mount:`, err);
  }
  _syncHeader();
  return true;
}

/**
 * Unmount and discard the top layer, revealing the one beneath.
 *
 * Pre:  depth >= 2 — popping the home layer is closing, not popping.
 * Post: depth is one less; the revealed layer shows the scroll position and
 *       filter state it held when it was covered.
 */
function _popLayer() {
  if (_stack.length < 2) return false;
  const top = _stack.pop();
  const view = _views.get(top.viewId);
  try {
    if (view) view.unmount(top.layerEl);
  } catch (err) {
    console.error(`[WorkBench] view "${top.viewId}" failed to unmount:`, err);
  }
  top.layerEl.remove();
  const revealed = _stack[_stack.length - 1];
  if (revealed) revealed.layerEl.hidden = false;
  _syncHeader();
  return true;
}

function _unmountAllLayers() {
  while (_stack.length) {
    const layer = _stack.pop();
    const view = _views.get(layer.viewId);
    try {
      if (view) view.unmount(layer.layerEl);
    } catch (err) {
      console.error(`[WorkBench] view "${layer.viewId}" failed to unmount:`, err);
    }
    layer.layerEl.remove();
  }
}

// ---------------------------------------------------------------------------
// History integration
// ---------------------------------------------------------------------------

function _viewUrl(viewId, params) {
  const view = _views.get(viewId);
  const path = (view && view.path) || '/overview';
  const query = view && typeof view.queryFromParams === 'function'
    ? view.queryFromParams(params || {})
    : '';
  return query ? `${path}?${query}` : path;
}

/** Every entry the WorkBench owns carries `wb: 1`, so foreign entries are
 *  recognisable and a popstate into one closes the surface rather than
 *  confusing the stack. */
function _historyState(viewId, params, depth) {
  return { wb: 1, depth, viewId, params: params || {} };
}

function _onPopState(event) {
  if (!_open) return;
  const state = event.state;
  if (!state || !state.wb) {
    // Popped out of the WorkBench's own entries entirely.
    _teardown();
    return;
  }
  if (state.depth < _stack.length) {
    while (_stack.length > state.depth) _popLayer();
    return;
  }
  if (state.depth > _stack.length) {
    // Forward navigation back into a layer we already unmounted: remount it.
    _pushLayer(state.viewId, state.params);
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Open the WorkBench.
 *
 * Pre:  a view registered as 'home' exists.
 * Post: the shell is in the DOM with home as layer 1; when `viewId` names
 *       another view it sits above home as layer 2, so back from a cold deep
 *       link lands on the cockpit rather than dismissing the app.
 *
 * @param {object}  [opts]
 * @param {string}  [opts.viewId='home']
 * @param {object}  [opts.params={}]
 * @param {boolean} [opts.deepLink=false] The browser is already at this view's
 *        URL (a hard load of /operations). The home entry then replaces the
 *        arrival entry instead of being pushed in front of it, so the address
 *        bar still reads what the user typed.
 */
export function openWorkBench({ viewId = HOME_VIEW_ID, params = {}, deepLink = false } = {}) {
  if (!_views.has(HOME_VIEW_ID)) {
    console.error('[WorkBench] cannot open: no "home" view registered');
    return;
  }
  if (_open) {
    if (viewId !== HOME_VIEW_ID) navigate(viewId, params);
    Modals.restore(SHELL_ID);
    return;
  }

  const shell = _buildShell();
  shell.classList.remove('hidden', 'modal-minimized');
  shell.style.display = 'flex';
  _open = true;

  Modals.register(SHELL_ID, {
    railBtnId: 'rail-overview',
    sidebarBtnId: 'tool-overview-btn',
    label: 'WorkBench',
    closeFn: () => _teardown(),
    restoreFn: () => {},
  });

  _pushLayer(HOME_VIEW_ID, {});
  const homeState = _historyState(HOME_VIEW_ID, {}, 1);
  const homeUrl = _viewUrl(HOME_VIEW_ID, {});
  try {
    if (deepLink) {
      history.replaceState(homeState, '', homeUrl);
    } else {
      history.pushState(homeState, '', homeUrl);
    }
  } catch (_) { /* history is unavailable in some embedded webviews */ }

  _popHandler = _onPopState;
  window.addEventListener('popstate', _popHandler);

  _escHandler = (e) => {
    if (e.key !== 'Escape' || !_open) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    e.stopPropagation();
    back();
  };
  document.addEventListener('keydown', _escHandler);

  if (viewId !== HOME_VIEW_ID) navigate(viewId, params);
}

/**
 * Drill into `viewId`, stacking it above the current top.
 *
 * Pre:  the WorkBench is open (it is opened first if not) and `viewId` is
 *       registered.
 * Post: depth is one greater and the address bar carries the view's URL, so a
 *       reload lands on the same record.
 */
export function navigate(viewId, params = {}) {
  if (!_open) {
    openWorkBench({ viewId, params });
    return;
  }
  if (!_pushLayer(viewId, params)) return;
  try {
    history.pushState(
      _historyState(viewId, params, _stack.length),
      '',
      _viewUrl(viewId, params),
    );
  } catch (_) { /* see openWorkBench */ }
}

/**
 * Go back one level, or close when already at home.
 *
 * Routed through `history.back()` rather than popping directly, so the
 * in-shell control and the Android back gesture take the same path and the
 * history entries cannot drift out of step with the stack.
 */
export function back() {
  if (!_open) return;
  try {
    history.back();
  } catch (_) {
    if (!_popLayer()) _teardown();
  }
}

/** Tear down the DOM and listeners without touching history. */
function _teardown() {
  if (!_open) return;
  _open = false;
  if (_escHandler) {
    document.removeEventListener('keydown', _escHandler);
    _escHandler = null;
  }
  if (_popHandler) {
    window.removeEventListener('popstate', _popHandler);
    _popHandler = null;
  }
  _unmountAllLayers();
  Modals.unregister(SHELL_ID);
  if (_shell) _shell.remove();
  _shell = null;
  _layerHost = null;
  _titleEl = null;
  _backBtn = null;
}

/**
 * Close the WorkBench and unwind its history entries in one step.
 *
 * Post: the browser sits on the entry that preceded the open, so a subsequent
 *       back press does not walk the user through layers that no longer exist.
 */
export function closeWorkBench() {
  if (!_open) return;
  const depth = _stack.length;
  _teardown();
  try {
    if (depth > 0) history.go(-depth);
  } catch (_) { /* see openWorkBench */ }
}

export function isWorkBenchOpen() {
  return _open;
}

/** Stack contents without the layer elements — for tests and verification. */
export function getStack() {
  return _stack.map(({ viewId, params }) => ({ viewId, params }));
}

export function getStackDepth() {
  return _stack.length;
}

/**
 * Resolve a route the SPA was loaded on into a WorkBench open.
 * Returns true when the path belongs to a registered view.
 */
export function openFromRoute(path, search = window.location.search) {
  const view = viewForPath(path);
  if (!view) return false;
  const params = typeof view.paramsFromQuery === 'function'
    ? view.paramsFromQuery(new URLSearchParams(search || ''))
    : {};
  openWorkBench({ viewId: view.id, params, deepLink: true });
  return true;
}

const workBench = {
  registerView,
  getRegisteredViews,
  viewForPath,
  openWorkBench,
  openFromRoute,
  navigate,
  back,
  closeWorkBench,
  isWorkBenchOpen,
  getStack,
  getStackDepth,
};

if (typeof window !== 'undefined') {
  window.workBench = workBench;
}

export default workBench;
