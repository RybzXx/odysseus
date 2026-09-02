"""Pin the WorkBench layer stack, its history integration, and cold deep-links.

`static/js/workbench.js` is the view host the cockpit sits on (SYSTEM_RECORD
Rev Y): views are sibling layers, the layer beneath the top is hidden rather
than destroyed, and navigation runs through the History API so the Android back
gesture pops one level instead of dismissing the whole surface.

Two properties are load-bearing and easy to regress silently:

- **A covered layer is never re-mounted.** That is the whole reason S2 was
  chosen over a body-swap: back restores scroll position and filter state
  because nothing re-rendered. A refactor that re-mounts on reveal would still
  *look* right in a screenshot and would have lost the property entirely.
- **Record identity travels in query params.** `app.py` registers exact-path
  SPA handlers with no catch-all, so a pushed `/projects/<id>` would 404 on a
  hard reload — a break nobody sees until they reload.

Driven through Node against the real module, with `document`, `window` and
`history` stubbed the way test_startup_session_bootstrap_js.py stubs them. The
history stub keeps a real entry list so `back()` and `go(-n)` deliver genuine
popstate events rather than a scripted sequence.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_WORKBENCH = _REPO / "static" / "js" / "workbench.js"
_HAS_NODE = shutil.which("node") is not None

_IMPORT_REWRITES = {
    "import * as Modals from './modalManager.js';": "import * as Modals from './modalManager.mjs';",
    "import { makeWindowDraggable } from './windowDrag.js';": (
        "import { makeWindowDraggable } from './windowDrag.mjs';"
    ),
}

_STUBS = {
    "modalManager.mjs": r"""
export function register() {}
export function unregister() {}
export function minimize() {}
export function restore() {}
export function toggle() { return false; }
export function close() {}
export function isRegistered() { return false; }
export function isMinimized() { return false; }
""",
    "windowDrag.mjs": "export function makeWindowDraggable() {}\n",
}

# A DOM small enough to read and large enough for the shell: elements with
# children, a class list, `hidden`, and a querySelector that hands back a
# stable stub per selector (the shell finds its parts by id after setting
# innerHTML, which no stub can actually parse).
_HARNESS_PRELUDE = r"""
function makeClassList(el) {
  const values = new Set();
  return {
    add(...names) { names.forEach(n => values.add(n)); },
    remove(...names) { names.forEach(n => values.delete(n)); },
    contains(name) { return values.has(name); },
    toggle(name, force) {
      const on = force === undefined ? !values.has(name) : !!force;
      if (on) values.add(name); else values.delete(name);
      return on;
    },
  };
}

function makeElement(tag) {
  const found = new Map();
  const el = {
    tagName: String(tag).toUpperCase(),
    id: '',
    className: '',
    textContent: '',
    innerHTML: '',
    title: '',
    hidden: false,
    removed: false,
    dataset: {},
    style: {},
    children: [],
    parentElement: null,
    listeners: {},
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    removeEventListener() {},
    setAttribute(name, value) { this[name] = value; },
    getAttribute(name) { return this[name] === undefined ? null : this[name]; },
    appendChild(child) {
      this.children.push(child);
      child.parentElement = this;
      return child;
    },
    contains(node) {
      if (this.children.includes(node)) return true;
      return this.children.some(c => c.contains && c.contains(node));
    },
    remove() {
      if (this.parentElement) {
        const i = this.parentElement.children.indexOf(this);
        if (i >= 0) this.parentElement.children.splice(i, 1);
      }
      this.parentElement = null;
      this.removed = true;
    },
    querySelector(sel) {
      if (!found.has(sel)) found.set(sel, makeElement('div'));
      return found.get(sel);
    },
    querySelectorAll() { return []; },
    closest() { return null; },
    fire(type, event = {}) { (this.listeners[type] || []).forEach(fn => fn(event)); },
  };
  el.classList = makeClassList(el);
  return el;
}

const documentStub = {
  head: makeElement('head'),
  body: makeElement('body'),
  createElement: (tag) => makeElement(tag),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
};
globalThis.document = documentStub;

// A history with real entries, so back() and go(-n) produce genuine pops.
function makeHistory() {
  const entries = [{ state: { pre: true }, url: '/chat' }];
  let idx = 0;
  const emit = () => {
    const handlers = globalThis.__popHandlers.slice();
    handlers.forEach(fn => fn({ state: entries[idx].state }));
  };
  return {
    entries,
    get index() { return idx; },
    get state() { return entries[idx].state; },
    get url() { return entries[idx].url; },
    pushState(state, _title, url) {
      entries.splice(idx + 1);
      entries.push({ state, url });
      idx = entries.length - 1;
    },
    replaceState(state, _title, url) { entries[idx] = { state, url }; },
    back() { this.go(-1); },
    forward() { this.go(1); },
    go(delta) {
      const target = Math.max(0, Math.min(entries.length - 1, idx + delta));
      if (target === idx) return;
      idx = target;
      emit();
    },
  };
}

globalThis.__popHandlers = [];
globalThis.history = makeHistory();
globalThis.window = {
  document: documentStub,
  innerWidth: 390,
  location: { pathname: '/overview', search: '' },
  addEventListener(type, fn) { if (type === 'popstate') globalThis.__popHandlers.push(fn); },
  removeEventListener(type, fn) {
    if (type !== 'popstate') return;
    const i = globalThis.__popHandlers.indexOf(fn);
    if (i >= 0) globalThis.__popHandlers.splice(i, 1);
  },
};
globalThis.location = globalThis.window.location;

// Records every mount/unmount so a test can prove a covered layer was left
// alone rather than quietly rebuilt.
globalThis.__log = [];

function makeView(id, extra = {}) {
  return Object.assign({
    id,
    title: id,
    path: '/' + id,
    mount(container, params) { globalThis.__log.push(['mount', id, params || {}]); container.dataset.mounted = id; },
    unmount(container) { globalThis.__log.push(['unmount', id]); container.dataset.mounted = ''; },
  }, extra);
}
"""


def _run(body: str) -> dict:
    """Run `body` with the real workbench module imported as `wb`."""
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        source = _WORKBENCH.read_text(encoding="utf-8")
        for original, replacement in _IMPORT_REWRITES.items():
            assert original in source, f"import line moved: {original}"
            source = source.replace(original, replacement)
        (tmpdir / "workbench.mjs").write_text(source, encoding="utf-8")
        for name, text in _STUBS.items():
            (tmpdir / name).write_text(text, encoding="utf-8")

        entry = (
            _HARNESS_PRELUDE
            + f"\nconst wb = await import({json.dumps((tmpdir / 'workbench.mjs').as_uri())});\n"
            + body
        )
        proc = subprocess.run(
            ["node", "--input-type=module"],
            input=entry, capture_output=True, text=True, encoding="utf-8",
            cwd=str(_REPO), timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip())


_REGISTER_THREE = """
// The real home view is overview.js, registered at path /overview.
wb.registerView(makeView('home', { path: '/overview' }));
wb.registerView(makeView('projects', {
  queryFromParams: (p) => (p.projectId ? 'project=' + encodeURIComponent(p.projectId) : ''),
  paramsFromQuery: (s) => ({ projectId: s.get('project') || null }),
}));
wb.registerView(makeView('operations'));
"""


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_push_and_pop_three_levels():
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    const d1 = wb.getStackDepth();
    wb.navigate('projects', { projectId: 'p1' });
    const d2 = wb.getStackDepth();
    wb.navigate('operations', {});
    const d3 = wb.getStackDepth();
    wb.back();
    const d4 = wb.getStackDepth();
    wb.back();
    const d5 = wb.getStackDepth();
    console.log(JSON.stringify({
      depths: [d1, d2, d3, d4, d5],
      top: wb.getStack().map(l => l.viewId),
    }));
    """)
    assert out["depths"] == [1, 2, 3, 2, 1]
    assert out["top"] == ["home"]


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_covered_layer_is_hidden_not_remounted():
    # The property S2 exists for: back must restore state, not rebuild it.
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    wb.navigate('projects', { projectId: 'p1' });
    wb.back();
    wb.navigate('operations', {});
    wb.back();
    console.log(JSON.stringify({ log: globalThis.__log }));
    """)
    mounts = [entry for entry in out["log"] if entry[0] == "mount"]
    assert [m[1] for m in mounts] == ["home", "projects", "operations"]
    # home mounted exactly once across two drills and two returns
    assert sum(1 for m in mounts if m[1] == "home") == 1


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_pop_unmounts_only_the_top_layer():
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    wb.navigate('projects', { projectId: 'p1' });
    wb.back();
    console.log(JSON.stringify({ log: globalThis.__log }));
    """)
    unmounts = [entry[1] for entry in out["log"] if entry[0] == "unmount"]
    assert unmounts == ["projects"]


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_back_at_depth_one_closes_the_workbench():
    # Falsification for the spec's "back at depth 1 leaving an empty shell".
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    wb.back();
    console.log(JSON.stringify({
      open: wb.isWorkBenchOpen(),
      depth: wb.getStackDepth(),
      unmounted: globalThis.__log.filter(e => e[0] === 'unmount').map(e => e[1]),
    }));
    """)
    assert out["open"] is False
    assert out["depth"] == 0
    assert out["unmounted"] == ["home"]


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_popstate_into_a_foreign_entry_closes_the_surface():
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    wb.navigate('projects', { projectId: 'p1' });
    // Two levels deep, jump straight past the WorkBench's own entries.
    history.go(-2);
    console.log(JSON.stringify({
      open: wb.isWorkBenchOpen(),
      unmounted: globalThis.__log.filter(e => e[0] === 'unmount').map(e => e[1]),
      url: history.url,
    }));
    """)
    assert out["open"] is False
    assert sorted(out["unmounted"]) == ["home", "projects"]
    assert out["url"] == "/chat"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_record_identity_is_a_query_param_not_a_path_segment():
    # /projects/p1 would 404 on a hard reload: app.py has exact-path handlers.
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    wb.navigate('projects', { projectId: 'p1' });
    console.log(JSON.stringify({ url: history.url }));
    """)
    assert out["url"] == "/projects?project=p1"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_cold_deep_link_synthesises_a_home_layer_beneath():
    out = _run(_REGISTER_THREE + """
    // A hard load of /operations: openFromRoute is what app.js calls.
    const claimed = wb.openFromRoute('/operations', '');
    const stackAfterLoad = wb.getStack().map(l => l.viewId);
    const urlAfterLoad = history.url;
    wb.back();
    console.log(JSON.stringify({
      claimed,
      stackAfterLoad,
      urlAfterLoad,
      afterBack: wb.getStack().map(l => l.viewId),
      open: wb.isWorkBenchOpen(),
      urlAfterBack: history.url,
    }));
    """)
    assert out["claimed"] is True
    assert out["stackAfterLoad"] == ["home", "operations"]
    # The address bar still reads what the user typed.
    assert out["urlAfterLoad"] == "/operations"
    # One back press lands on the cockpit, not out of the app.
    assert out["afterBack"] == ["home"]
    assert out["open"] is True
    assert out["urlAfterBack"] == "/overview"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_open_from_route_declines_a_path_no_view_claims():
    # app.js falls back to the module's own window on false; a silent true
    # would swallow the route and open nothing.
    out = _run(_REGISTER_THREE + """
    console.log(JSON.stringify({
      claimed: wb.openFromRoute('/calendar', ''),
      open: wb.isWorkBenchOpen(),
    }));
    """)
    assert out["claimed"] is False
    assert out["open"] is False


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_deep_link_params_come_from_the_query_string():
    out = _run(_REGISTER_THREE + """
    wb.openFromRoute('/projects', '?project=p9');
    console.log(JSON.stringify({ stack: wb.getStack() }));
    """)
    assert out["stack"][1]["viewId"] == "projects"
    assert out["stack"][1]["params"]["projectId"] == "p9"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_close_unmounts_every_layer_and_unwinds_history():
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    wb.navigate('projects', { projectId: 'p1' });
    wb.navigate('operations', {});
    wb.closeWorkBench();
    console.log(JSON.stringify({
      open: wb.isWorkBenchOpen(),
      depth: wb.getStackDepth(),
      unmounted: globalThis.__log.filter(e => e[0] === 'unmount').map(e => e[1]),
      url: history.url,
    }));
    """)
    assert out["open"] is False
    assert out["depth"] == 0
    # Top-down, so a view never unmounts while one above it still exists.
    assert out["unmounted"] == ["operations", "projects", "home"]
    # Back after closing must not walk the user through dead layers.
    assert out["url"] == "/chat"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_forward_navigation_remounts_the_layer_it_popped():
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    wb.navigate('projects', { projectId: 'p1' });
    wb.back();
    history.forward();
    console.log(JSON.stringify({
      stack: wb.getStack().map(l => l.viewId),
      params: wb.getStack().map(l => l.params),
    }));
    """)
    assert out["stack"] == ["home", "projects"]
    assert out["params"][1]["projectId"] == "p1"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_navigating_to_an_unregistered_view_leaves_the_stack_intact():
    # Pre violated by the caller: the stack must not gain a broken layer.
    out = _run(_REGISTER_THREE + """
    wb.openWorkBench({});
    wb.navigate('nosuchview', {});
    console.log(JSON.stringify({
      depth: wb.getStackDepth(),
      url: history.url,
    }));
    """)
    assert out["depth"] == 1
    assert out["url"] == "/overview"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_registering_the_same_id_twice_replaces_rather_than_duplicates():
    out = _run("""
    wb.registerView(makeView('home'));
    wb.registerView(makeView('home'));
    console.log(JSON.stringify({ ids: wb.getRegisteredViews().map(v => v.id) }));
    """)
    assert out["ids"] == ["home"]


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_a_view_without_both_lifecycle_hooks_is_refused():
    # Registering a half-built view would fail later, inside a push, with the
    # stack already mutated.
    out = _run("""
    wb.registerView({ id: 'broken', title: 'Broken', path: '/broken', mount: () => {} });
    console.log(JSON.stringify({ ids: wb.getRegisteredViews().map(v => v.id) }));
    """)
    assert out["ids"] == []
