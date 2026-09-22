"""
tests/mahdawi/test_layer2_boundaries.py

Edge cases for Layer Two, its Layer One checks, and the Instagram driver.
Several tests pinned a defect found in the #test pass of 2026-09-22 and now
guard its fix.
"""
import json
import os
import struct
import subprocess
import sys

import pytest

from mahdawi.content import media_check, text_check
from mahdawi.layer2 import ranking
from mahdawi.messaging import reply_check, tiers
from mahdawi.messaging.models import AgentVerdict, GateFacts, ShopFacts, TIER_FAQ

from tests.mahdawi.fake_layer2 import FakeGateway

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FACTS_CLEAN = GateFacts(window_open=True, cap_available=True, is_repeat=False,
                        comment_reply_used=False, channel_can_send=True)


# -- media_check: corrupt files ---------------------------------------------------
# Suspected an endless loop on a segment length below 2; disproven — the scan
# falls through the zero bytes to EOF. Kept as a regression guard.
@pytest.mark.parametrize("seg_len", [0, 1])
def test_corrupt_jpeg_segment_length_terminates(tmp_path, seg_len):
    path = tmp_path / "bad.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0" + struct.pack(">H", seg_len) + b"\x00" * 16)
    code = ("import sys; sys.path.insert(0, %r); from mahdawi.content import media_check;"
            "print(media_check.image_size(%r))" % (REPO, str(path)))
    try:
        subprocess.run([sys.executable, "-c", code], timeout=5, check=True,
                       capture_output=True)
    except subprocess.TimeoutExpired:
        pytest.fail("image_size did not return within 5 s")


@pytest.mark.parametrize("head", [b"", b"\x89PNG\r\n\x1a\n", b"GIF89a", b"RIFF\x00\x00\x00\x00WEBP",
                                  b"\xff\xd8"])
def test_truncated_headers_drop_the_file_and_never_raise(tmp_path, head):
    path = tmp_path / "t.img"
    path.write_bytes(head)
    kept, dropped = media_check.check_media([str(path)])
    assert kept == [] and len(dropped) == 1


def test_exact_minimum_side_is_kept_and_one_below_is_dropped(tmp_path):
    def png(name, side):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", side, side)
                      + name.encode())
        return str(p)
    edge = media_check.MIN_IMAGE_SIDE
    kept, dropped = media_check.check_media([png("a.png", edge), png("b.png", edge - 1)])
    assert [os.path.basename(k) for k in kept] == ["a.png"]
    assert [n for n, _ in dropped] == ["b.png"]


def test_empty_media_list():
    assert media_check.check_media([]) == ([], [])


# -- text_check: number boundaries ------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("", []),
    ("٠", [0]),
    ("11,900 و ١١٬٩٠٠ و 11.900", [11900, 11900, 11900]),
    ("07701234567", [7701234567]),          # a phone number is a number, refused unless supplied
    ("11.9 ألف", [11, 9]),                   # a decimal splits; refusal fails safe
])
def test_numbers_in_boundaries(text, expected):
    assert text_check.numbers_in(text) == expected


def test_text_of_only_digits_counts_as_arabic_share_one():
    assert text_check.arabic_share("١١٬٩٠٠") == 1.0


def test_exact_length_limit_passes_and_one_over_fails():
    ok = "ا" * 10
    assert text_check.problems(ok, max_chars=10, min_arabic_share=0.7) == []
    assert text_check.problems(ok + "ا", max_chars=10, min_arabic_share=0.7)


# -- messaging: code must hold the tier -------------------------------------------
@pytest.mark.parametrize("intent", ["complaint", "return", "order", "negotiation", "other"])
def test_a_non_routine_intent_never_lands_in_faq(intent):
    verdict = AgentVerdict(intent, TIER_FAQ, "neutral", 0.99, "model said FAQ")
    assert tiers.assign(verdict, FACTS_CLEAN) != TIER_FAQ


def test_a_reply_with_another_products_price_is_refused():
    shop = ShopFacts(products=(("ستائر", 11900), ("مصباح", 25000)))
    # The customer asked about the curtains; the reply quotes the lamp's price.
    assert reply_check.problems("سعر الستائر ٢٥٬٠٠٠ دينار", shop, "بشكد الستائر؟")
    assert reply_check.problems("سعر الستائر ١١٬٩٠٠ دينار", shop, "بشكد الستائر؟") == []


def test_a_price_for_a_message_naming_no_product_is_refused():
    shop = ShopFacts(products=(("ستائر", 11900),))
    assert reply_check.problems("السعر ١١٬٩٠٠ دينار", shop, "بشكد؟")
    assert reply_check.problems("هلا بيك، أي منتج تقصد؟", shop, "بشكد؟") == []


def test_confidence_exactly_at_threshold_stays_faq():
    from mahdawi.messaging import settings
    v = AgentVerdict("price", TIER_FAQ, "neutral", settings.CONFIDENCE_THRESHOLD, "x")
    assert tiers.assign(v, FACTS_CLEAN) == TIER_FAQ


# -- ranking: one candidate, many candidates --------------------------------------
def test_one_candidate_is_ranked_one():
    c = ranking.Candidate("A", "t", None, "A", 50.0, 1000, "note")
    assert [(r.sku, r.rank) for r in ranking.rank(FakeGateway(), [c])] == [("A", 1)]


class _BudgetGateway(FakeGateway):
    def complete(self, model, messages, **kwargs):
        self.max_tokens = kwargs.get("max_tokens")
        return super().complete(model, messages, **kwargs)


def test_ranking_budget_grows_with_the_catalog():
    gw = _BudgetGateway()
    cands = [ranking.Candidate("S%03d" % i, "منتج", None, "B", 30.0, 10000, "note")
             for i in range(120)]
    ranking.rank(gw, cands)
    # ~40 tokens per {sku, rank, Arabic reason} entry.
    assert gw.max_tokens and gw.max_tokens >= 40 * len(cands)


def test_ranking_rejects_an_empty_answer_for_candidates():
    assert ranking.check_ranking([], ["A"]) is not None
    assert json.dumps(ranking.check_ranking([], [])) == "null"


# -- driver: which file the Instagram post uses -----------------------------------
def test_instagram_driver_posts_an_image_first(tmp_path):
    from mahdawi.driver.app_flow import first_image, read_package
    (tmp_path / "caption.txt").write_text("x", encoding="utf-8")
    (tmp_path / "1000.mp4").write_bytes(b"v")
    (tmp_path / "2000.png").write_bytes(b"i")
    _caption, media = read_package(str(tmp_path), "instagram")
    assert first_image(media).endswith("2000.png")


def test_images_beyond_the_carousel_cap_are_not_judged(tmp_path):
    from mahdawi.content import settings as content_settings
    from mahdawi.fedshi.models import ProductRecord
    from services import mahdawi as svc
    paths = []
    for i in range(content_settings.MEDIA_CAP + 3):
        p = tmp_path / ("%02d.png" % i)
        p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 800, 800)
                      + bytes([i]))
        paths.append(str(p))
    gw = FakeGateway()
    svc._layer2_content(gw, ProductRecord(sku="S", title="ستائر"), paths)
    assert gw.calls.count("image") <= content_settings.MEDIA_CAP


# -- per-channel captions ----------------------------------------------------------
def test_for_channel_caps_only_the_tag_line():
    from mahdawi.content import caption as caption_mod
    from mahdawi.content import settings as cs
    cap = "عنوان\nسطر\n\n#a #b #c #d #e"
    insta = caption_mod.for_channel(cap, "instagram")
    assert insta.startswith("عنوان\nسطر\n\n")
    assert insta.split("\n\n")[-1].split() == ["#a", "#b", "#c", "#d", "#e"][:cs.HASHTAG_CAP_INSTAGRAM]
    assert caption_mod.for_channel("بلا وسوم", "instagram") == "بلا وسوم"
    assert caption_mod.for_channel("سطر\n\nنص عادي", "tiktok") == "سطر\n\nنص عادي"


# -- 9router wire format -----------------------------------------------------------
def test_gateway_asks_for_a_non_streamed_answer():
    # 9router streams SSE when "stream" is absent (2026-09-22).
    import httpx
    from mahdawi.layer2.gateway import Gateway
    seen = {}

    def post(url, json=None, headers=None, timeout=None):
        seen.update(json)
        return httpx.Response(200, json={"choices": [{"message": {"content": "هلا"}}]},
                              request=httpx.Request("POST", url))
    Gateway("http://x/v1", post=post).complete("m", [])
    assert seen["stream"] is False


@pytest.mark.parametrize("raw,clean", [
    ('**"كل الهلا بيك عيني، نوّرتنا!"**', "كل الهلا بيك عيني، نوّرتنا!"),
    ("«خوش اختيار للبيت»", "خوش اختيار للبيت"),
    ("خوش `اختيار`", "خوش اختيار"),
    ("", ""),
])
def test_strip_markup(raw, clean):
    assert text_check.strip_markup(raw) == clean


def test_markdown_left_inside_text_is_refused():
    assert text_check.problems("خوش * اختيار", max_chars=100, min_arabic_share=0.7)
