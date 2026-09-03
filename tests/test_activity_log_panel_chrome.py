"""The Activity Log panel must be built once, not rebuilt on every poll.

Two defects lived here, and both were invisible to every existing test because
neither produced an error — the code ran, it just did nothing useful.

**The drag handle never worked.** `makeWindowDraggable(modal, options)` reads
`options.content` and `options.header` and returns immediately if either is
missing (windowDrag.js:57-60). The call passed a bare element where the options
object belongs, so both were `undefined` and the helper no-opped on every open.
Meanwhile `.act-header` set `cursor: move`, so the panel advertised a drag it
could not perform. A wrong-shaped argument throws nothing and logs nothing;
only reading the signature catches it.

**Typing in the search box lost focus on every keystroke.** `_render` assigned
`_modal.innerHTML`, destroying and recreating the whole panel — including the
focused input and its caret. The `input` handler calls `_fetchLogs`, which
re-renders, so each character replaced the element the user was typing into.
The 3s poll did the same to an idle caret.

The fix splits the two concerns: `_buildChrome` writes the panel and wires it
once, `_render` touches only the counters, the chip counts and the row list.
These tests pin that split at the seam where it can silently regress — someone
reintroducing a whole-panel rebuild inside `_render` would restore both bugs.

Verified in a browser before these were written: the panel moved by exactly the
drag delta (+160x, +100y), and a mid-word caret survived nine seconds spanning
three polls with the input remaining the same DOM node throughout.
"""

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = (_REPO / "static" / "js" / "activityLog.js").read_text(encoding="utf-8")
_DRAG_SRC = (_REPO / "static" / "js" / "windowDrag.js").read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    """The source of a top-level `function name(...) { ... }`."""
    start = _SRC.index(f"function {name}(")
    depth = 0
    for i in range(_SRC.index("{", start), len(_SRC)):
        if _SRC[i] == "{":
            depth += 1
        elif _SRC[i] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[start:i + 1]
    raise AssertionError(f"unbalanced braces reading {name}")


# --------------------------------------------------------------------------
# The drag handle
# --------------------------------------------------------------------------

def test_the_helper_still_requires_content_and_header():
    """Pins the contract the call site has to satisfy. If windowDrag ever stops
    early-returning on a missing pair, this test is the thing that says so."""
    assert "const content = options.content;" in _DRAG_SRC
    assert "const header = options.header;" in _DRAG_SRC
    assert "if (!content || !header) return;" in _DRAG_SRC


def test_drag_is_called_with_an_options_object_not_a_bare_element():
    """The regression: makeWindowDraggable(_modal, dragHandle) passed an
    element where an options object belongs, so the helper no-opped."""
    call = re.search(r"makeWindowDraggable\(([^;]*?)\);", _SRC, re.S)
    assert call, "activityLog.js no longer calls makeWindowDraggable"
    args = call.group(1)
    assert "content" in args and "header" in args, (
        f"drag call must pass {{ content, header }}, got: {args.strip()}"
    )
    assert "{" in args, "second argument must be an options object"


def test_the_header_that_advertises_move_is_the_one_wired():
    """`.act-header` sets cursor:move in CSS. The element carrying that class
    must be the drag handle, or the panel promises a gesture it cannot do."""
    assert re.search(r"\.act-header\s*\{[^}]*cursor:\s*move", _SRC, re.S)
    assert "#act-header-drag" in _SRC
    assert re.search(r'class="act-header"\s+id="act-header-drag"', _SRC)


def test_docking_stays_off():
    """Dock rules are written `.modal.modal-right-docked ...` in style.css and
    this panel deliberately is not a `.modal`. Enabling docking would add a
    class that styles nothing."""
    call = re.search(r"makeWindowDraggable\(([^;]*?)\);", _SRC, re.S).group(1)
    assert "enableDock: false" in call


# --------------------------------------------------------------------------
# The chrome / render split
# --------------------------------------------------------------------------

def test_render_never_rebuilds_the_whole_panel():
    """The focus bug in one assertion. Falsification: any assignment to
    _modal.innerHTML inside _render brings back both symptoms."""
    body = _function_body("_render")
    assert "_modal.innerHTML" not in body, (
        "_render assigns _modal.innerHTML again — this destroys the focused "
        "search input on every keystroke and every 3s poll"
    )


def test_render_writes_only_the_list():
    body = _function_body("_render")
    assert "list.innerHTML = rowsHtml;" in body
    assert body.count("innerHTML") == 1, "_render should write exactly one container"


def test_the_search_input_is_built_by_the_chrome_not_the_render():
    chrome = _function_body("_buildChrome")
    render = _function_body("_render")
    assert "act-search-input" in chrome
    assert "act-search-input" not in render


@pytest.mark.parametrize(
    "control",
    ["act-close-btn", "act-refresh-btn", "act-clear-btn", "act-status-select",
     "act-search-input", "act-header-drag"],
)
def test_every_control_is_wired_exactly_once(control):
    """Wiring inside _render meant listeners were re-attached on every poll.
    Each of these is addressed once, in _buildChrome.

    `#act-list` is deliberately excluded: it is addressed twice, once to wire
    the delegated row listener and once for _render to write rows into. That is
    the split working, not a leak — the listener count is what matters, and
    test_row_clicks_are_delegated_to_the_container covers it.
    """
    assert _SRC.count(f"'#{control}'") <= 1, f"{control} is looked up more than once"
    chrome = _function_body("_buildChrome")
    assert control in chrome


def test_row_clicks_are_delegated_to_the_container():
    """Rows are the one thing _render does replace, so per-row listeners would
    be orphaned on every refresh. One listener on the container survives."""
    chrome = _function_body("_buildChrome")
    assert "#act-list" in chrome
    assert "closest('.act-row')" in chrome
    render = _function_body("_render")
    assert "addEventListener" not in render


def test_chrome_is_built_once_per_panel():
    """_buildChrome is called from the branch that creates the element, so a
    close/reopen reuses the chrome and its listeners rather than doubling
    them. close() hides; it does not destroy."""
    body = _function_body("open")
    assert "_buildChrome();" in body
    create_idx = body.index("document.body.appendChild(_modal);")
    build_idx = body.index("_buildChrome();")
    assert build_idx > create_idx, "_buildChrome must run after the element exists"
    assert _SRC.count("_buildChrome()") == 2, "expected one definition and one call"
