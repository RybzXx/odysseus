"""
The UiAutomator parser and selector logic — pure, no phone.

This is the element-resolution core the driver trusts: a selector must match
the right node, find() must prefer the clickable one, and bounds must map to a
tap point. No adb here.
"""
from mahdawi.driver import uinode

_DUMP = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node text="Add a caption…" resource-id="com.instagram.android:id/caption_input_text_view"
        class="android.widget.AutoCompleteTextView" content-desc="Write a caption"
        clickable="true" bounds="[60,1359][1380,1539]"/>
  <node text="Share" resource-id="" class="android.widget.TextView"
        content-desc="" clickable="false" bounds="[645,2823][794,2891]"/>
  <node text="" resource-id="com.instagram.android:id/share_footer_button"
        class="android.widget.Button" content-desc="Share"
        clickable="true" bounds="[60,2775][1380,2940]"/>
</hierarchy>"""


def test_find_by_resource_id_substring():
    node = uinode.find(_DUMP, uinode.Selector(rid="caption_input_text_view"))
    assert node is not None and "caption_input_text_view" in node.rid


def test_find_prefers_clickable_over_label():
    # Two nodes carry "Share"; the clickable Button must win over the TextView.
    node = uinode.find(_DUMP, uinode.Selector(descs=["Share"]))
    assert node is not None and node.cls.endswith("Button") and node.clickable


def test_center_from_bounds():
    node = uinode.find(_DUMP, uinode.Selector(rid="share_footer_button"))
    assert node.center() == (720, 2857)


def test_empty_selector_matches_nothing():
    assert uinode.find(_DUMP, uinode.Selector()) is None


def test_missing_control_returns_none():
    assert uinode.find(_DUMP, uinode.Selector(rid="does_not_exist")) is None


def test_garbage_dump_is_empty():
    assert uinode.parse("not xml at all") == []


def test_from_map_builds_selector():
    sel = uinode.Selector.from_map({"rid": "share_footer_button", "texts": ["Next"]})
    assert sel.rid == "share_footer_button" and sel.texts == ["Next"]


_SPLIT = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node text="" content-desc="Next" class="android.widget.Button"
        resource-id="" clickable="true" bounds="[1200,80][1380,180]"/>
  <node text="Next" content-desc="" class="android.widget.TextView"
        resource-id="" clickable="false" bounds="[1240,110][1340,150]"/>
</hierarchy>"""


def test_split_label_matches_via_either_field():
    # The edit-screen Next: desc on the Button, text on a child TextView. A
    # selector listing both must match, and prefer the clickable Button.
    node = uinode.find(_SPLIT, uinode.Selector(texts=["Next"], descs=["Next"]))
    assert node is not None and node.clickable and node.cls.endswith("Button")
