"""Contract tests for the Bil Weekend role description."""

import re
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

    assert "Website upkeep is part of the Operations Manager role" in html
    assert "is a separate objective" in html
    assert "Website development line-up" in html


def test_page_reads_as_a_role_description_not_an_evidence_report():
    html = PAGE.read_text(encoding="utf-8")
    visible_text = re.sub(r"<[^>]+>", " ", html)

    assert "Expected standards" in html
    assert "What this document was drawn from" not in html
    assert "Sources:" not in html
    assert "commits" not in visible_text.lower()
    assert "recorded page views" not in visible_text.lower()


def test_page_does_not_name_specific_agencies_or_operational_counts():
    html = PAGE.read_text(encoding="utf-8")
    article = re.search(r'<article id="document">(.*?)</article>', html, re.DOTALL)
    assert article is not None
    visible_text = re.sub(r"<[^>]+>", " ", article.group(1))

    assert "Against the Compass" not in html
    assert "Pinto Lopes" not in html
    assert "Millennium" not in html
    assert "164 routes" not in html
    assert "20 contracted hotels" not in html
    assert not re.search(r"\d", visible_text)


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
