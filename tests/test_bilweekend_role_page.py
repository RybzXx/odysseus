"""Contract tests for the Bil Weekend role document."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "bilweekend-role-and-responsibilities.html"
APP = ROOT / "app.py"


def test_page_is_a_complete_standalone_document():
    html = PAGE.read_text(encoding="utf-8")

    assert html.startswith("<!doctype html>")
    assert '<html lang="en">' in html
    assert '<meta charset="utf-8">' in html
    assert html.rstrip().endswith("</html>")


def test_page_preserves_the_role_boundary():
    html = PAGE.read_text(encoding="utf-8")

    assert "Keeping the published websites correct and available is" in html
    assert "Building new software is not part of this post" in html
    assert "Work outside the post" in html


def test_copy_control_supplies_rich_and_plain_text():
    html = PAGE.read_text(encoding="utf-8")

    assert 'id="copy"' in html
    assert 'nonce="{{CSP_NONCE}}"' in html
    assert '"text/html"' in html
    assert '"text/plain"' in html
    assert html.count("copyBySelection();") == 1


def test_page_uses_only_odysseus_font_assets():
    html = PAGE.read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert "/static/fonts/Inter-Regular.woff2" in html


def test_odysseus_exposes_the_published_page():
    app_source = APP.read_text(encoding="utf-8")

    assert '@app.get("/bilweekend-role")' in app_source
    assert '"docs/bilweekend-role-and-responsibilities.html"' in app_source
    assert "return serve_html_with_nonce(request, document_path)" in app_source
