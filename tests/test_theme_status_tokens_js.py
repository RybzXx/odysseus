"""Operation-status colours must derive from the theme, in both copies.

Odysseus dresses sixteen presets from a five-colour seed. `deriveSyntaxColors`
established the rule: hue carries the meaning and is fixed, saturation follows
the theme's own foreground saturation clamped, lightness flips on
`isDark = bgL < 50`. `deriveStatusColors` is the same rule applied to
error/warn/busy/ok/idle, so no module needs to hardcode a status hex.

The derivation exists twice on purpose. `index.html`'s head script runs before
any module loads, so the first paint is already themed; `theme.js` re-runs it
on every theme change. Byte-identical constants are the whole contract between
them, and nothing but a test enforces it — the two copies of the *advanced*
variable map have already drifted apart in this codebase (index.html carries
--accent-primary, --accent-error, --section-accent and --toggle-bg; theme.js's
ADV_KEYS carries none of them), which is exactly the failure this prevents.

Two properties matter beyond parity, and both were measured, not assumed:

- **Legibility.** Every token must clear 3.0:1 against its own theme's panel.
  The worst case across all sixteen presets is 3.61 (cute/ok).
- **Distinctness.** The five must stay tellable apart in every theme. The
  closest hue pair anywhere is 33.2 degrees (paper, error/warn).

An earlier draft passed the accent through for `busy`. It failed both: 2.24:1
on `paper`, and on `terminal` — a theme whose accent is green — `busy` and `ok`
landed 0.4 degrees apart. The regression tests below would catch a return to it.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_THEME_JS = _REPO / "static" / "js" / "theme.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_HAS_NODE = shutil.which("node") is not None

_TOKENS = ("error", "warn", "busy", "ok", "idle")

# (hue, saturation addend, saturation cap, lightness dark, lightness light)
_EXPECTED = {
    "error": (358, 25, 65, 68, 45),
    "warn": (32, 25, 70, 66, 42),
    "busy": (200, 20, 60, 68, 42),
    "ok": (135, 15, 55, 65, 38),
    "idle": (280, 15, 55, 70, 48),
}


def _theme_js_constants():
    """Pull the five formulas out of deriveStatusColors."""
    src = _THEME_JS.read_text(encoding="utf-8")
    body = src[src.index("function deriveStatusColors"):]
    body = body[:body.index("\n}")]
    out = {}
    for name in _TOKENS:
        m = re.search(
            rf"{name}:\s*hslToHex\(\s*(\d+),\s*Math\.min\(fgS \+ (\d+), (\d+)\),"
            rf"\s*isDark \? (\d+) : (\d+)\)",
            body,
        )
        assert m, f"deriveStatusColors has no readable formula for {name!r}"
        out[name] = tuple(int(g) for g in m.groups())
    return out


def _head_script_constants():
    """Pull the same five out of the inline first-paint script."""
    src = _INDEX_HTML.read_text(encoding="utf-8")
    out = {}
    for name in _TOKENS:
        m = re.search(
            rf"--status-{name}'\s*,\s*hsl2h\(\s*(\d+),\s*Math\.min\(fH\[1\]\+(\d+),(\d+)\),"
            rf"dk\?(\d+):(\d+)\)",
            src,
        )
        assert m, f"index.html's head script has no readable formula for {name!r}"
        out[name] = tuple(int(g) for g in m.groups())
    return out


def test_both_copies_derive_the_same_colours():
    """The property that keeps the first paint from flashing a wrong colour."""
    assert _theme_js_constants() == _head_script_constants()


def test_the_constants_are_the_measured_ones():
    """Pins the tuned values. Falsification: any edit that changes a constant
    without re-running the contrast and distinctness sweeps."""
    assert _theme_js_constants() == _EXPECTED


def test_applycolors_emits_all_five():
    src = _THEME_JS.read_text(encoding="utf-8")
    for name in _TOKENS:
        assert f"'--status-{name}'" in src, f"applyColors never sets --status-{name}"


def test_head_script_emits_all_five():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    for name in _TOKENS:
        assert f"--status-{name}" in src


def test_hue_is_fixed_not_derived_from_the_accent():
    """The rule deriveSyntaxColors set: hue carries meaning. Only `keyword`
    derives its hue from the accent, and status must not copy that — a green
    accent would make the error badge green."""
    src = _THEME_JS.read_text(encoding="utf-8")
    body = src[src.index("function deriveStatusColors"):]
    body = body[:body.index("\n}")]
    assert "redH" not in body and "colors.red" not in body


# --------------------------------------------------------------------------
# Behavioural sweep across every shipped theme
# --------------------------------------------------------------------------

_SWEEP = r"""
function hexToHSL(hex){hex=hex.replace('#','');
 var r=parseInt(hex.substring(0,2),16)/255,g=parseInt(hex.substring(2,4),16)/255,b=parseInt(hex.substring(4,6),16)/255;
 var mx=Math.max(r,g,b),mn=Math.min(r,g,b),h,s,l=(mx+mn)/2;
 if(mx===mn){h=s=0}else{var d=mx-mn;s=l>0.5?d/(2-mx-mn):d/(mx+mn);
 if(mx===r)h=((g-b)/d+(g<b?6:0))/6;else if(mx===g)h=((b-r)/d+2)/6;else h=((r-g)/d+4)/6}
 return[h*360,s*100,l*100];}
function hslToHex(h,s,l){h=((h%360)+360)%360;s=Math.max(0,Math.min(100,s))/100;l=Math.max(0,Math.min(100,l))/100;
 var a=s*Math.min(l,1-l);function f(n){var k=(n+h/30)%12;return l-a*Math.max(-1,Math.min(k-3,9-k,1))}
 function th(v){return Math.round(v*255).toString(16).padStart(2,'0')}
 return'#'+th(f(0))+th(f(8))+th(f(4));}
function lum(hex){hex=hex.replace('#','');var o=[];
 for(var i=0;i<6;i+=2){var c=parseInt(hex.substr(i,2),16)/255;o.push(c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4));}
 return 0.2126*o[0]+0.7152*o[1]+0.0722*o[2];}
function contrast(a,b){var la=lum(a),lb=lum(b),hi=Math.max(la,lb),lo=Math.min(la,lb);return (hi+0.05)/(lo+0.05);}
DERIVE_FN
var out={worstContrast:[99,null,null],closestHue:[999,null,null],perTheme:{}};
for(var name in THEMES){
  var c=THEMES[name];
  var t=deriveStatusColors(c);
  out.perTheme[name]=t;
  for(var k in t){
    var cr=contrast(t[k], c.panel);
    if(cr<out.worstContrast[0]) out.worstContrast=[cr,name,k];
  }
  var keys=Object.keys(t);
  for(var i=0;i<keys.length;i++)for(var j=i+1;j<keys.length;j++){
    var ha=hexToHSL(t[keys[i]])[0], hb=hexToHSL(t[keys[j]])[0];
    var dh=Math.min(Math.abs(ha-hb),360-Math.abs(ha-hb));
    if(dh<out.closestHue[0]) out.closestHue=[dh,name,keys[i]+'/'+keys[j]];
  }
}
console.log(JSON.stringify(out));
"""


def _run_sweep() -> dict:
    """Run the real deriveStatusColors over the real THEMES table."""
    src = _THEME_JS.read_text(encoding="utf-8")
    themes = src[src.index("export const THEMES = {"):]
    themes = themes[:themes.index("\n};") + 3].replace("export const", "const")
    fn = src[src.index("function deriveStatusColors"):]
    fn = fn[:fn.index("\n}") + 2]
    js = themes + "\n" + _SWEEP.replace("DERIVE_FN", fn)
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=js, capture_output=True, text=True, encoding="utf-8",
        cwd=str(_REPO), timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_every_token_is_legible_on_its_own_theme_panel():
    """Falsification: any theme/token pair below 3.0:1 fails the sweep that
    tuned these constants in the first place."""
    out = _run_sweep()
    worst, theme, token = out["worstContrast"]
    assert worst >= 3.0, f"{token} on {theme} is only {worst:.2f}:1 against its panel"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_the_five_stay_distinguishable_in_every_theme():
    """Guards the collision that killed the accent-passthrough draft: on
    terminal, busy and ok were 0.4 degrees apart."""
    out = _run_sweep()
    closest, theme, pair = out["closestHue"]
    assert closest >= 25.0, f"{pair} on {theme} are only {closest:.1f} degrees apart"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_light_themes_get_darker_tokens_than_dark_themes():
    """The isDark flip is what makes one seed serve both. Falsification: a
    light theme rendering the same lightness as a dark one."""
    out = _run_sweep()

    def lightness(hex_):
        h = hex_.lstrip("#")
        return max(int(h[i:i + 2], 16) for i in (0, 2, 4))

    for token in _TOKENS:
        dark = lightness(out["perTheme"]["midnight"][token])
        light = lightness(out["perTheme"]["paper"][token])
        assert dark > light, f"{token}: midnight {dark} should out-lighten paper {light}"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_every_shipped_theme_is_covered():
    """Sixteen presets today. A new one must pass the same gates, so this
    fails loudly rather than silently narrowing the sweep."""
    out = _run_sweep()
    assert len(out["perTheme"]) >= 16
    for name, tokens in out["perTheme"].items():
        assert set(tokens) == set(_TOKENS), f"{name} is missing a status token"
        for token, value in tokens.items():
            assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{name}/{token} = {value!r}"
