"""The Overview grid's markup must nest correctly, and its layout must survive a reload.

The panels became movable, which means the render no longer decides where a
panel ends up -- ``_applyLayout`` moves it after the markup lands. Two things
have to hold for that to work, and neither is visible from Python:

  1. The grid markup nests as intended. Wrapping the projects panel in a column
     added an element that has to be closed; an unbalanced tag would silently
     reparent panels and put them in the wrong column.
  2. A layout saved on a wide screen is not applied to a narrow one. The live
     instance is a phone, so a 1320px column split must never reach it.

Driven through Node against the real module, so these assert behaviour rather
than the presence of source text.
"""

import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERVIEW_JS = REPO_ROOT / "static" / "js" / "overview.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to drive the module"
)


def _run_node(script: str) -> dict:
    """Execute a Node script that prints one JSON object, and return it.

    The script carries the whole body template, which grows with every panel
    added. Passing it as an argv element caps it at the command-line limit
    (32 KB on Windows), so it goes to a temp .mjs file instead: a file has no
    such ceiling, and the extension gives module semantics without a flag.
    """
    with tempfile.TemporaryDirectory() as tmp:
        entry = Path(tmp) / "layout_probe.mjs"
        entry.write_text(textwrap.dedent(script), encoding="utf-8")
        result = subprocess.run(
            ["node", str(entry)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    if result.returncode != 0:
        pytest.fail(f"node exited {result.returncode}:\n{result.stderr}")
    tail = [ln for ln in result.stdout.strip().splitlines() if ln.startswith("{")]
    if not tail:
        pytest.fail(f"no JSON on stdout:\n{result.stdout}\n{result.stderr}")
    return json.loads(tail[-1])


def test_grid_markup_nests_every_panel_into_a_column():
    """Every panel must land inside a column, and each gutter between them.

    An unclosed wrapper still renders, so this counts the tree rather than the
    tags: four panels across the two columns the default layout fills, with the
    projects panel in the second. A third column is present but empty -- it
    holds panels only in 3-col mode, which _applyLayout switches to later.
    """
    source = OVERVIEW_JS.read_text(encoding="utf-8")

    # The body template is a single template literal assigned to innerHTML.
    # Pull it out and neutralise its interpolations so it can be parsed as HTML.
    start = source.index("  body.innerHTML = `")
    open_tick = source.index("`", start)
    end = source.index("\n  `;", open_tick)
    template = source[open_tick + 1:end]

    script = f"""
    const raw = {json.dumps(template)};
    // Replace every ${{...}} interpolation with nothing. Nesting inside an
    // interpolation is balanced by construction, so dropping them leaves the
    // static skeleton this test is about.
    let html = '', depth = 0;
    for (let i = 0; i < raw.length; i++) {{
      if (raw[i] === '$' && raw[i + 1] === '{{') {{ depth++; i++; continue; }}
      if (depth > 0) {{
        if (raw[i] === '{{') depth++;
        else if (raw[i] === '}}') depth--;
        continue;
      }}
      html += raw[i];
    }}

    // Minimal tag walker: enough to build a tree from well-formed markup.
    const stack = [{{ tag: 'root', attrs: '', children: [] }}];
    const tagRe = /<(\\/?)([a-zA-Z][\\w-]*)([^>]*?)(\\/?)>/g;
    const voids = new Set(['br', 'hr', 'img', 'input', 'meta', 'link']);
    let m;
    while ((m = tagRe.exec(html))) {{
      const [, closing, tag, attrs, selfClose] = m;
      if (closing) {{
        if (stack.length > 1) stack.pop();
      }} else if (!selfClose && !voids.has(tag.toLowerCase())) {{
        const node = {{ tag, attrs, children: [] }};
        stack[stack.length - 1].children.push(node);
        stack.push(node);
      }}
    }}

    const findAll = (node, pred, out = []) => {{
      for (const c of node.children) {{
        if (pred(c)) out.push(c);
        findAll(c, pred, out);
      }}
      return out;
    }};
    const root = stack[0];
    // The panel-size buttons carry data-panel-id as well, so the attribute
    // alone does not identify a panel -- only a div holding one does.
    const isPanel = n => n.tag === 'div' && n.attrs.includes('data-panel-id=');
    const grid = findAll(root, n => n.attrs.includes('data-main-grid'))[0];
    const columns = grid ? findAll(grid, n => n.attrs.includes('data-column=')) : [];

    console.log(JSON.stringify({{
      unclosed: stack.length - 1,
      gridFound: Boolean(grid),
      columnCount: columns.length,
      gutterIsDirectGridChild: grid
        ? grid.children.filter(c => c.attrs.includes('data-col-gutter')).length
        : 0,
      panelsPerColumn: columns.map(
        c => findAll(c, isPanel).length
      ),
      secondColumnHasProjects: columns.length > 1
        ? findAll(columns[1], n => isPanel(n) && n.attrs.includes('data-panel-id="projects"')).length
        : 0,
    }}));
    """

    got = _run_node(script)

    assert got["unclosed"] == 0, (
        f"{got['unclosed']} element(s) left open in the body template — "
        f"panels would reparent into the wrong column"
    )
    assert got["gridFound"] is True
    assert got["columnCount"] == 3, f"expected three columns, found {got['columnCount']}"
    assert got["gutterIsDirectGridChild"] == 2, (
        "each gutter must be a direct grid child, or it is not a grid track"
    )
    assert got["panelsPerColumn"] == [2, 2, 0], (
        f"default arrangement should be two panels in each filled column, "
        f"and none in the third: {got['panelsPerColumn']}"
    )
    assert got["secondColumnHasProjects"] == 1


def _extract(source: str, signature: str, next_marker: str) -> str:
    start = source.index(signature)
    end = source.index(next_marker, start)
    return source[start:end].rstrip()


def test_a_saved_layout_is_reconciled_against_the_panels_that_exist():
    """A stored layout must not strand, duplicate, or invent a panel.

    Someone carrying a layout from an older version has to keep seeing every
    panel this version renders, and a panel that has since been removed must
    not leave a hole. Driven directly, following the harness pattern the other
    *_js tests use, because overview.js touches the DOM at import time.
    """
    source = OVERVIEW_JS.read_text(encoding="utf-8")
    constants = _extract(source, "const PANEL_IDS =", "/**\n * The arrangement")
    default_fn = _extract(source, "function _defaultLayout()", "\nfunction _newState()")
    reconcile_fn = _extract(source, "function _reconcileLayout(raw)", "\nfunction _loadLayout()")

    script = f"""
    {constants}
    {default_fn}
    {reconcile_fn}

    const cases = {{
      // Nothing stored at all.
      empty: _reconcileLayout(null),
      // A panel this version does not have, and one it does, in one column.
      stale: _reconcileLayout({{
        columns: [['emails', 'weather'], ['projects']],
        split: 40,
      }}),
      // The same panel listed twice.
      duplicated: _reconcileLayout({{
        columns: [['emails', 'emails'], ['emails']],
        split: 50,
      }}),
      // A split dragged past the clamp.
      extremeSplit: _reconcileLayout({{ columns: [[], []], split: 99 }}),
      negativeSplit: _reconcileLayout({{ columns: [[], []], split: -20 }}),
      garbage: _reconcileLayout('not an object'),
    }};

    const flat = (l) => l.columns.flat();
    console.log(JSON.stringify({{
      emptyPanels: flat(cases.empty).sort(),
      stalePanels: flat(cases.stale).sort(),
      staleKeptOrder: cases.stale.columns,
      staleSplit: cases.stale.split,
      duplicatedPanels: flat(cases.duplicated).sort(),
      extremeSplit: cases.extremeSplit.split,
      negativeSplit: cases.negativeSplit.split,
      garbagePanels: flat(cases.garbage).sort(),
      panelIds: PANEL_IDS.slice().sort(),
      minSplit: MIN_SPLIT_PERCENT,
    }}));
    """

    got = _run_node(script)
    expected = got["panelIds"]

    assert got["emptyPanels"] == expected
    assert got["stalePanels"] == expected, "an unknown stored panel must be dropped"
    assert got["duplicatedPanels"] == expected, "a panel must not appear twice"
    assert got["garbagePanels"] == expected, "unparseable storage must fall back cleanly"

    assert got["staleSplit"] == 40, "a valid stored split is kept"
    assert got["extremeSplit"] == 100 - got["minSplit"], "a split past the clamp is pulled back"
    assert got["negativeSplit"] == got["minSplit"]

    # 'operations' was absent from the stored layout and must reappear, without
    # displacing the panels the user had deliberately arranged.
    assert got["staleKeptOrder"][0][0] == "emails"
    assert "operations" in got["staleKeptOrder"][0]
    assert got["staleKeptOrder"][1] == ["projects"]
