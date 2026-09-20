"""Versioned day facts shared by checking, pricing, and document generation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
from pathlib import Path

from services.itinerary.places import normalize_place

PLAN_VERSION = 2
_pricing_cache = None


def pricing_version():
    """Fingerprint pricing data without copying rates into each saved plan."""
    from services.itinerary.pipeline.config import PRICING_DIR, DEFAULT_MARKUP_PCT, DEFAULT_MARGIN_PCT
    from services.itinerary.pipeline.group_revenue import GROUP_PRICING_POLICY_VERSION
    global _pricing_cache
    paths = sorted(Path(PRICING_DIR).glob("*.json"))
    stamps = (DEFAULT_MARKUP_PCT, DEFAULT_MARGIN_PCT, GROUP_PRICING_POLICY_VERSION,
              tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths))
    if _pricing_cache and _pricing_cache[0] == stamps:
        return _pricing_cache[1]
    version = content_hash({"office_markup_percent": DEFAULT_MARKUP_PCT, "margin_markup_percent": DEFAULT_MARGIN_PCT,
                           "group_pricing_policy": GROUP_PRICING_POLICY_VERSION,
                           "files": {p.name: json.loads(p.read_text(encoding="utf-8")) for p in paths}})
    _pricing_cache = (stamps, version)
    return version


def content_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()


def template_data(row):
    return asdict(row) if is_dataclass(row) else dict(row) if isinstance(row, dict) else vars(row).copy()


def catalogue_version(templates):
    from services.itinerary.propose_sequence import field_of
    return content_hash({code: template_data(row) for code, row in sorted(templates.items())
                         if field_of(row, "active", True)})


def request_version(request):
    data = asdict(request)
    data.pop("key", None)
    return content_hash(data)


@dataclass
class ResolvedPlan:
    days: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    references: list = field(default_factory=list)
    request_version: str = ""
    catalogue_version: str = ""
    corpus_version: str = ""
    pricing_version: str = ""
    templates: dict = field(default_factory=dict, repr=False)

    @property
    def day_codes(self):
        return [day["code"] for day in self.days]

    def to_dict(self):
        data = {"version": PLAN_VERSION, "days": deepcopy(self.days), "issues": list(self.issues),
                "references": deepcopy(self.references), "request_version": self.request_version,
                "catalogue_version": self.catalogue_version, "corpus_version": self.corpus_version,
                "pricing_version": self.pricing_version}
        data["fingerprint"] = content_hash(data)
        return data


def resolve_plan(codes, templates, request=None, route=None) -> ResolvedPlan:
    """Freeze catalogue facts. Never infer hotel inclusion from the end city.

    A catalogue conflict is owned by the catalogue and blocks this plan only.
    Historical evidence can reject a binding but cannot silently rewrite a row.
    """
    from services.itinerary.day_shape import shape_of, OWNER_SETTLED_SHAPES
    from services.itinerary.propose_sequence import field_of
    from services.itinerary.day_facts import source_day_facts
    snapshot = deepcopy(templates)
    plan = ResolvedPlan(templates=snapshot, catalogue_version=catalogue_version(snapshot),
                        request_version=request_version(request) if request else "",
                        references=deepcopy(getattr(route, "references", [])),
                        corpus_version=getattr(route, "corpus_version", ""), pricing_version=pricing_version())
    if route and route.status != "usable":
        plan.issues.extend(route.review_reasons or ["The historical reference needs review."])
    previous_source = ""
    for number, code in enumerate(codes, 1):
        row = snapshot.get(code)
        if row is None:
            plan.issues.append(f"Day {number}: unknown template {code}.")
            continue
        shape = shape_of(code, row)
        raw_overnight = field_of(row, "overnight_city", "")
        overnight = normalize_place(raw_overnight)
        status = "present" if overnight else "none" if shape.role in {"departure", "day_trip"} else "unknown"
        tags = row.get("pricing_tags", []) if isinstance(row, dict) else getattr(row, "pricing_tags", [])
        known_tags = isinstance(tags, (list, tuple, set)) and all(isinstance(tag, str) for tag in tags)
        accommodation = ("included" if "hotel_night" in tags else "excluded") if known_tags else "unknown"
        start, end = normalize_place(shape.start_city), normalize_place(shape.end_city)
        if raw_overnight and not overnight:
            plan.issues.append(f"Day {number} ({code}): the overnight place is ambiguous.")
        if status == "unknown":
            plan.issues.append(f"Day {number} ({code}): overnight status is unknown. Resolve the catalogue conflict.")
        if overnight and end and overnight != end:
            plan.issues.append(f"Day {number} ({code}): the overnight city disagrees with the day destination.")
        if status == "none" and accommodation == "included":
            plan.issues.append(f"Day {number} ({code}): accommodation is included without an overnight stay.")
        if accommodation == "unknown":
            plan.issues.append(f"Day {number} ({code}): accommodation inclusion is unknown.")
        # Routing, checking, and the builder consume the same canonical city.
        if isinstance(row, dict):
            row["overnight_city"] = overnight
        else:
            row.overnight_city = overnight
        evidence = {"template_code": code, "template_version": content_hash(template_data(templates[code])),
                    "role_source": shape.source, "place_source": "owner" if code in OWNER_SETTLED_SHAPES else "catalogue",
                    "overnight_source": "catalogue", "accommodation_source": "catalogue pricing tags"}
        if route and number <= len(route.days):
            source = route.days[number - 1]
            facts = source_day_facts(source, previous_source)
            previous_source = facts["overnight_city"] or facts["end_city"]
            evidence.update(route_id=route.id, source_day=source.day, source_facts=facts)
            if facts["overnight_status"] == "unknown":
                plan.issues.append(f"Day {number}: the historical overnight status needs review.")
            elif facts["overnight_status"] != status or facts["overnight_city"] != overnight:
                plan.issues.append(f"Day {number} ({code}): the binding changes the historical overnight stay.")
            if facts["role"] == "departure" and not facts["end_city"]:
                plan.issues.append(f"Day {number}: the source does not establish the departure destination.")
        plan.days.append({"number": number, "code": code, "role": shape.role,
                          "start_city": start, "end_city": end, "overnight_status": status,
                          "overnight_city": overnight, "accommodation": accommodation,
                          "evidence": evidence})
    return plan


def stale_plan_errors(stored, request, templates, codes):
    """Require recalculation for legacy, modified, or obsolete saved plans."""
    if not stored or stored.get("version") != PLAN_VERSION:
        return ["This saved result needs recalculation to establish its day plan."]
    errors = []
    unsigned = {key: value for key, value in stored.items() if key != "fingerprint"}
    if content_hash(unsigned) != stored.get("fingerprint"):
        errors.append("The saved plan is inconsistent. Recalculate it.")
    if stored.get("request_version") != request_version(request):
        errors.append("The request changed. Recalculate the itinerary.")
    if stored.get("catalogue_version") != catalogue_version(templates):
        errors.append("The catalogue changed. Recalculate the itinerary.")
    if stored.get("pricing_version") != pricing_version():
        errors.append("Pricing changed. Recalculate the itinerary.")
    if [d.get("code") for d in stored.get("days", [])] != list(codes):
        errors.append("The selected codes differ from the saved plan. Recalculate it.")
    if stored.get("corpus_version"):
        from services.offers.offer_store import corpus_fingerprint
        if corpus_fingerprint()["fingerprint"] != stored["corpus_version"]:
            errors.append("The historical corpus changed. Recalculate the itinerary.")
    return errors
