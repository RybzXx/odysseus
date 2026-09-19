"""Replay a local sent-offer snapshot without network or document operations.

Run with --data-dir pointing to a snapshot with offer_corpus/*/offer.json.
The output contains hashed references, dates, cities, and codes, not mail text.
Requests are inferred from delivered days. They are not recovered enquiries.
Historical retrieval excludes the target message and identical itinerary text.
The catalogue and connection checks remain current, so this is retrospective.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import time


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def itinerary_signature(offer):
    """Identify repeated day text without using message IDs or filenames."""
    return digest(json.dumps([
        [day.overnight_city.casefold().strip(), re.sub(r"\s+", " ", day.text).strip().casefold()]
        for day in offer.days], ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--newer-year", type=int, default=2026)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--target-id", action="append", default=[],
                        help="Replay this hashed target ID. Repeat for a fixed comparison set.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.environ["ODYSSEUS_DATA_DIR"] = str(args.data_dir.resolve())
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("The sent itinerary audit must not use the network")

    socket.socket.connect = refuse_network
    socket.create_connection = refuse_network
    from services.offers.offer_store import iter_offers
    from services.itinerary.models import NormalizedRequest, RouteDay, RouteRecord
    from services.itinerary.matcher import activity_regions, load_routes
    from services.itinerary.propose_sequence import active_day_templates
    from services.itinerary.binder import bind_route_to_templates
    from services.itinerary.candidates import build_candidates
    from services.itinerary.sequence_check import check_sequence
    from services.itinerary.sequence_grade import grade_sequence
    from services.itinerary.resolved_plan import resolve_plan
    from services.itinerary.route_corpus import reference_pool_view

    def hashes():
        return {str(p.relative_to(args.data_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(args.data_dir.glob("offer_corpus/*/offer.json"))}

    before = hashes()
    offers = list(iter_offers())
    templates = active_day_templates()
    production_routes = load_routes()
    signatures = {id(o): itinerary_signature(o) for o in offers}
    references = {id(o): digest(o.message_id + "\0" + o.attachment_name) for o in offers}
    routes = {}
    for offer in offers:
        days = [RouteDay(d.day_number, d.overnight_city, d.text) for d in offer.days]
        reference = references[id(offer)]
        routes[id(offer)] = RouteRecord(reference, reference, len(days), offer.tour_type,
                                       offer.city_sequence, [], days, activity_regions(days))

    def request_for(offer):
        return NormalizedRequest(key=references[id(offer)], source="curated",
                                 customer_name="Corpus audit", day_count=offer.day_count,
                                 tour_type=offer.tour_type,
                                 requested_regions=sorted(routes[id(offer)].region_set))

    def measure(offer, codes, gaps, request, route_id="", source_plan=None):
        checked = check_sequence(codes, templates, normalized_request=request)
        grade = grade_sequence(codes, templates, offer)
        weekdays = []
        for offset in range(7):
            start = date(2026, 10, 5) + timedelta(days=offset)
            dated = replace(request, start_date=start)
            result = check_sequence(codes, templates, start_date=start, normalized_request=dated)
            if result.is_clean:
                weekdays.append(start.strftime("%A"))
        return {
            "route_id": route_id, "codes": codes, "bound_days": len(codes),
            "exact_days": len(codes) == offer.day_count,
            "sent_nights": grade.nights_sent, "proposed_nights": grade.nights_proposed,
            "matching_nights": grade.matched,
            "exact_nights": grade.matched == grade.nights_sent == grade.nights_proposed,
            "faults": [{"kind": f.kind, "statement": f.statement} for f in checked.faults],
            "untested": checked.untested, "gaps": gaps,
            "structurally_fault_free": checked.found_no_fault,
            "synthetic_start_weekdays_clean": weekdays,
            "source_plan_issues": source_plan.issues if source_plan else [],
            "source_plan_weekdays_clean": weekdays if source_plan and not source_plan.issues else [],
        }

    report = {"method": {
        "inferred_request": "Delivered day count, tour type, and regions inferred from activities",
        "dates": "Sent dates order references only. Seven synthetic start weekdays test closures.",
        "historical_pool": "Strictly older offers, excluding same message and identical day text",
        "historical_quality": "Older-only retrieval deliberately includes raw records as a stress test. Production uses the verified pool.",
        "plan_gate": "Code-only weekday results retain baseline comparability. Source-plan weekday results also require resolved source facts.",
        "limitation": "Current catalogue and all-corpus connection evidence. Not a historical training evaluation.",
        "network": "Blocked by socket guard", "newer_year": args.newer_year,
    }, "inventory": {"offers": len(offers), "templates": len(templates),
                      "production_routes": len(production_routes),
                      "years": dict(Counter(o.sent_at.year if o.sent_at else "unknown" for o in offers)),
                      "day_counts": dict(Counter(o.day_count for o in offers)),
                      "unique_itinerary_texts": len(set(signatures.values())),
                      "reference_dispositions": reference_pool_view()["counts"]},
              "reconstruction": [], "comparisons": []}
    started = time.monotonic()
    for i, offer in enumerate(offers):
        request = request_for(offer)
        codes, gaps = bind_route_to_templates(routes[id(offer)], templates, request.requested_regions)
        report["reconstruction"].append({
            "id": references[id(offer)], "sent_at": offer.sent_at.isoformat() if offer.sent_at else None,
            "days": offer.day_count, "regions": request.requested_regions,
            "source_nights": offer.city_sequence, "warnings": offer.extraction_warnings,
            "day_numbers_contiguous": [d.day_number for d in offer.days] == list(range(1, offer.day_count + 1)),
            "blank_overnight_before_final": [d.day_number for d in offer.days[:-1] if not d.overnight_city],
            **measure(offer, codes, gaps, request, source_plan=resolve_plan(codes, templates, request, routes[id(offer)])),
        })
        if (i + 1) % 50 == 0:
            print(f"Reconstructed {i + 1}/{len(offers)}", flush=True)

    # All offers in the newest year, plus one older offer per year/length/region.
    selected = [o for o in offers if o.sent_at and o.sent_at.year >= args.newer_year]
    groups = {}
    for offer in offers:
        if offer.sent_at and offer.sent_at.year < args.newer_year:
            key = (offer.sent_at.year, offer.day_count, tuple(sorted(routes[id(offer)].region_set)))
            groups[key] = offer
    selected += list(groups.values())
    if args.target_id:
        requested_ids = set(args.target_id)
        selected = [o for o in offers if references[id(o)] in requested_ids]
        missing = requested_ids - {references[id(o)] for o in selected}
        if missing:
            raise ValueError("Unknown target IDs: " + ", ".join(sorted(missing)))
    selected.sort(key=lambda o: (o.sent_at, references[id(o)]))
    if args.limit:
        selected = selected[:args.limit]
    production_cache = {}
    for i, offer in enumerate(selected):
        request = request_for(offer)
        earlier = [o for o in offers if o.sent_at and o.sent_at < offer.sent_at
                   and o.message_id != offer.message_id and signatures[id(o)] != signatures[id(offer)]]
        key = (request.day_count, request.tour_type, tuple(request.requested_regions))
        if key not in production_cache:
            production_cache[key] = build_candidates(request, templates, routes=production_routes, ceiling=1)
        case = {"id": references[id(offer)], "sent_at": offer.sent_at.isoformat(),
                "days": offer.day_count, "regions": request.requested_regions,
                "older_pool_size": len(earlier)}
        for label, found in (
            ("production", production_cache[key]),
            ("older_only", build_candidates(request, templates, routes=[routes[id(o)] for o in earlier], ceiling=1)),
        ):
            if found.candidates:
                best = found.candidates[0]
                case[label] = measure(offer, best.day_codes, best.gap_notes, request,
                                      best.route_id if label == "older_only" else digest(best.route_id), best.plan)
                if label == "older_only":
                    source = next(o for o in earlier if references[id(o)] == best.route_id)
                    case[label]["reference_sent_at"] = source.sent_at.isoformat()
                    assert source.sent_at < offer.sent_at
                    assert source.message_id != offer.message_id
                    assert signatures[id(source)] != signatures[id(offer)]
            else:
                case[label] = {"empty": True, "untested": found.untested}
        report["comparisons"].append(case)
        if (i + 1) % 5 == 0:
            print(f"Compared {i + 1}/{len(selected)} against older offers", flush=True)
    report["corpus_unchanged"] = before == hashes()
    assert report["corpus_unchanged"]
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"inventory": report["inventory"], "comparisons": len(report["comparisons"]),
                      "elapsed_seconds": report["elapsed_seconds"], "corpus_unchanged": True}))


if __name__ == "__main__":
    main()
