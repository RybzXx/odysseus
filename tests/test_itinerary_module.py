"""
tests/test_itinerary_module.py

Comprehensive test suite for the Odysseus Itinerary Prediction, Document Generation,
and Automated Replies module.
"""
import unittest
import sys
import os
from pathlib import Path
from datetime import date

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary.models import (
    NormalizedRequest,
    RouteDay,
    RouteRecord,
    ItineraryPreviewResult,
)
from services.itinerary.normalizer import (
    normalize_curated_record,
    normalize_queue_record,
    normalize_from_dict,
)
from services.itinerary.matcher import (
    load_routes,
    score_route,
    find_best_route,
    region_coverage,
)
from services.itinerary.binder import (
    bind_route_to_templates,
    _city_region,
)
from services.itinerary.reply_builder import (
    compose_email_reply,
    compose_whatsapp_reply,
)


class MockDayTemplate:
    def __init__(self, code, city, overnight_city, region, full_text="", active=True):
        self.code = code
        self.city = city
        self.overnight_city = overnight_city
        self.region = region
        self.full_text = full_text
        self.active = active


class TestItineraryModule(unittest.TestCase):

    def test_normalizer_curated(self):
        curated_data = {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "7701234567",
            "countryCode": "+964",
            "numberOfPeople": 4,
            "tripDays": "7-9",
            "travelDateMode": "exact",
            "exactDate": "2026-10-15",
            "regions": ["Central Iraq", "Kurdistan"],
            "accommodation": "4 star",
            "comments": "Interested in ancient history and local food",
        }
        req = normalize_curated_record("curated:123", curated_data)
        self.assertEqual(req.key, "curated:123")
        self.assertEqual(req.customer_name, "Jane Doe")
        self.assertEqual(req.customer_email, "jane@example.com")
        self.assertEqual(req.pax, 4)
        self.assertEqual(req.vehicle_type, "VAN")
        self.assertEqual(req.day_count, 8)
        self.assertEqual(req.hotel_tier, "4star")
        self.assertIn("Central Iraq", req.requested_regions)
        self.assertIn("Northern Iraq", req.requested_regions)
        self.assertEqual(req.start_date, date(2026, 10, 15))
        self.assertTrue(any("ancient history" in n for n in req.special_notes))

    def test_normalizer_queue(self):
        queue_row = {
            "row_id": 42,
            "full_name": "John Smith",
            "customer_email": "john@example.com",
            "phone": "+1 555 0199",
            "trip_days": "10",
            "travel_date": "November 2026",
            "regions": "Southern Iraq, Central Iraq",
            "service_type": "Guided Tour",
        }
        req = normalize_queue_record("queue:42", queue_row)
        self.assertEqual(req.key, "queue:42")
        self.assertEqual(req.customer_name, "John Smith")
        self.assertEqual(req.day_count, 10)
        self.assertIn("Southern Iraq", req.requested_regions)
        self.assertIn("Central Iraq", req.requested_regions)
        self.assertEqual(req.travel_month, "November 2026")

    def test_matcher_loading_and_scoring(self):
        routes = load_routes()
        self.assertGreater(len(routes), 0, "Route corpus must contain routes")

        req = NormalizedRequest(
            key="test:1",
            source="curated",
            customer_name="Test Traveler",
            pax=2,
            day_count=8,
            tour_type="individual",
            hotel_tier="3star",
            vehicle_type="SMALL_CAR",
            requested_regions=["Central Iraq", "Southern Iraq"],
        )
        best_route, score = find_best_route(req, routes)
        self.assertIsNotNone(best_route)
        self.assertGreater(score, 0.4)
        self.assertGreaterEqual(region_coverage(req, best_route), 0.5)

    def test_binder_b18_city_region_resolution(self):
        reg = _city_region("Baghdad", template_region="Northern Iraq")
        self.assertEqual(reg, "Central Iraq")

        reg_erbil = _city_region("Erbil", template_region="Central Iraq")
        self.assertEqual(reg_erbil, "Northern Iraq")

    def test_binder_b19_transit_connector_retention(self):
        templates = {
            "BGW01": MockDayTemplate("BGW01", "Baghdad", "Baghdad", "Central Iraq", "Baghdad historical tour"),
            "EBL01": MockDayTemplate("EBL01", "Erbil", "Erbil", "Northern Iraq", "Erbil Citadel"),
            "BSR01": MockDayTemplate("BSR01", "Basra", "Basra", "Southern Iraq", "Basra corniche"),
        }
        route = RouteRecord(
            id="test_route",
            source_file="north_south_tour.docx",
            day_count=3,
            tour_type="individual",
            city_sequence=["Erbil", "Baghdad", "Basra"],
            themes=[],
            days=[
                RouteDay(day=1, overnight_city="Erbil", text="Arrive in Erbil"),
                RouteDay(day=2, overnight_city="Baghdad", text="Transit stay in Baghdad"),
                RouteDay(day=3, overnight_city="Basra", text="Tour in Basra"),
            ],
            region_set={"Northern Iraq", "Central Iraq", "Southern Iraq"},
        )
        bound_codes, gap_notes = bind_route_to_templates(
            route, templates, requested_regions=["Northern Iraq", "Southern Iraq"]
        )
        self.assertIn("BGW01", bound_codes, "Central Iraq transit connector BGW01 must be retained")
        self.assertIn("EBL01", bound_codes)
        self.assertIn("BSR01", bound_codes)
        self.assertTrue(any("transit connector" in g.lower() for g in gap_notes))

    def test_reply_builder(self):
        req = NormalizedRequest(
            key="curated:test",
            source="curated",
            customer_name="Dr. Smith",
            pax=2,
            day_count=7,
            hotel_tier="4star",
            requested_regions=["Central Iraq", "Southern Iraq"],
            start_date=date(2026, 11, 10),
        )
        preview = ItineraryPreviewResult(
            key="curated:test",
            matched_route_id="route_1",
            matched_route_name="Mesopotamia Classic Tour",
            confidence_score=0.88,
            confidence_level="high",
            requested_day_count=7,
            delivered_day_count=7,
            bound_day_codes=["BGW01", "BAB01", "NAS01"],
            coverage_gaps=[],
            calendar_warnings=[],
            estimated_quote={"total_usd": 3200.0, "per_person_usd": 1600.0},
            can_generate_document=True,
        )
        email = compose_email_reply(
            req,
            preview,
            doc_url="https://docs.google.com/document/d/test1234/edit",
            quote={"total_usd": 3200.0, "per_person_usd": 1600.0},
        )
        self.assertIn("Dr. Smith", email["subject"])
        self.assertIn("$3,200.00 USD", email["body_text"])
        self.assertIn("https://docs.google.com/document/d/test1234/edit", email["body_text"])
        self.assertIn("4star", email["body_text"].lower())

        wa = compose_whatsapp_reply(
            req,
            preview,
            doc_url="https://docs.google.com/document/d/test1234/edit",
            quote={"total_usd": 3200.0},
        )
        self.assertIn("Dr. Smith", wa)
        self.assertIn("$3,200.00 USD", wa)

    def test_preview_with_live_pipeline(self):
        from services.itinerary.generator import preview_itinerary, load_templates
        templates = load_templates()
        if not templates:
            self.skipTest("Live templates not loaded")

        req = NormalizedRequest(
            key="curated:real_sample",
            source="curated",
            customer_name="Alice Explorer",
            pax=2,
            day_count=8,
            tour_type="individual",
            hotel_tier="4star",
            vehicle_type="SMALL_CAR",
            requested_regions=["Central Iraq", "Southern Iraq"],
            start_date=date(2026, 11, 1),
        )
        preview = preview_itinerary(req)
        self.assertIsNotNone(preview)
        self.assertGreater(len(preview.bound_day_codes), 0)
        self.assertIn(preview.confidence_level, ["high", "moderate", "low"])
        if preview.estimated_quote:
            self.assertGreater(preview.estimated_quote.get("total_usd", 0), 0)


if __name__ == "__main__":
    unittest.main()
