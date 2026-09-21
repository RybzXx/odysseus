"""
mahdawi.driver.uinode — read a UiAutomator XML dump, find a control, give its tap point.

Pure parsing, no adb. This is what makes the driver element-based rather than
pixel-based: a Selector describes a control by resource-id / content-desc /
text, and find() returns the matching node's centre from its bounds string.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass
class Node:
    """One control from the dump, with enough to identify and tap it."""
    rid: str
    desc: str
    text: str
    cls: str
    clickable: bool
    bounds: str

    def center(self) -> tuple:
        """Post: (x, y) at the middle of bounds. Raises ValueError if unparsable."""
        m = _BOUNDS.match(self.bounds or "")
        if not m:
            raise ValueError("unparsable bounds %r" % self.bounds)
        x1, y1, x2, y2 = (int(g) for g in m.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2


@dataclass
class Selector:
    """
    How to find a control. Any field that is set must match; unset fields are
    ignored. text/desc match by substring so a label like "Add a caption…" is
    found by "Add a caption". rid and cls match by substring too, which lets a
    map name "EditText" without the full class path.
    """
    rid: Optional[str] = None
    desc: Optional[str] = None
    text: Optional[str] = None
    cls: Optional[str] = None
    texts: List[str] = field(default_factory=list)   # any-of visible text
    descs: List[str] = field(default_factory=list)    # any-of content-desc

    @classmethod
    def from_map(cls, spec: dict) -> "Selector":
        """Build a Selector from a selector-map entry (all keys optional)."""
        return cls(
            rid=spec.get("rid"), desc=spec.get("desc"), text=spec.get("text"),
            cls=spec.get("class_contains"),
            texts=list(spec.get("texts", [])), descs=list(spec.get("descs", [])),
        )

    def matches(self, n: Node) -> bool:
        # rid and cls are structural AND-constraints — every one set must hold.
        if self.rid and self.rid not in n.rid:
            return False
        if self.cls and self.cls not in n.cls:
            return False
        # Label terms (text/desc, singular or list) are alternatives: a control
        # matches when ANY label term hits. A labelled control often splits its
        # text and content-desc across two nodes, so requiring both would miss it.
        label_terms = []
        if self.text:
            label_terms.append(("text", self.text))
        label_terms += [("text", t) for t in self.texts]
        if self.desc:
            label_terms.append(("desc", self.desc))
        label_terms += [("desc", d) for d in self.descs]
        if label_terms:
            hit = any((term in n.text) if kind == "text" else (term in n.desc)
                      for kind, term in label_terms)
            if not hit:
                return False
        # A selector with no criteria matches nothing (avoid tapping at random).
        return bool(label_terms or self.rid or self.cls)


def parse(dump_xml: str) -> List[Node]:
    """Post: every node in the dump, in document order. [] on empty/garbage."""
    try:
        root = ET.fromstring(dump_xml)
    except ET.ParseError:
        return []
    out: List[Node] = []
    for el in root.iter("node"):
        a = el.attrib
        out.append(Node(
            rid=a.get("resource-id", ""), desc=a.get("content-desc", ""),
            text=a.get("text", ""), cls=a.get("class", ""),
            clickable=a.get("clickable") == "true", bounds=a.get("bounds", ""),
        ))
    return out


def find(dump_xml: str, selector: Selector) -> Optional[Node]:
    """
    The first node that the selector matches, or None.

    A clickable match wins over a non-clickable one, so a label inside a button
    does not shadow the button itself.
    """
    nodes = [n for n in parse(dump_xml) if selector.matches(n)]
    if not nodes:
        return None
    for n in nodes:
        if n.clickable:
            return n
    return nodes[0]
