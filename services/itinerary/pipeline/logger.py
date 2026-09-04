"""
BilWeekend — Quote Logger
Appends a snapshot of each generated quote to a JSONL log file.
Each line is a self-contained JSON record (easy to read, grep, and parse).
"""
import json
import os
from datetime import datetime
from services.itinerary.pipeline.models import TourRequest, Quote
from services.itinerary.pipeline import config


def log_quote(request: TourRequest, quote: Quote, doc_id: str):
    """Appends a quote snapshot to logs/quote_log.jsonl."""
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    record = {
        "logged_at":      datetime.now().isoformat(timespec="seconds"),
        "doc_id":         doc_id,
        "doc_link":       f"https://docs.google.com/document/d/{doc_id}/edit",
        "doc_name":       request.doc_name,
        "tour_type":      request.tour_type,
        "day_codes":      request.day_codes,
        "start_date":     request.start_date.isoformat() if request.start_date else None,
        "num_days":       quote.num_days,
        "num_nights":     quote.num_nights,
        "exchange_rate":  request.exchange_rate,
        "markup_percent": request.markup_percent,
    }

    if request.tour_type == "individual":
        record.update({
            "num_people":   request.num_people,
            "single_rooms": request.single_rooms,
            "double_rooms": request.double_rooms,
            "hotel_tier":   request.hotel_tier,
            "vehicle":      request.selected_vehicle,
            "include_transfers":  request.include_transfers,
            "include_shrine_help": request.include_shrine_help,
            "include_food": request.include_food,
            "food_tier":    request.food_tier,
            "final_3star":  quote.final_total_3star,
            "final_4star":  quote.final_total_4star,
            "final_5star":  quote.final_total_5star,
            "per_person_3star": quote.per_person_3star,
            "per_person_4star": quote.per_person_4star,
            "per_person_5star": quote.per_person_5star,
            "line_items": [
                {
                    "category": li.category,
                    "description": li.description,
                    "total": li.total,
                }
                for li in quote.line_items
            ],
        })
    else:
        record.update({
            "hotel_tier":    request.hotel_tier,
            "group_vehicle": request.group_vehicle,
            "foc_per_group": request.foc_per_group,
            "sgl_supplement": request.sgl_supplement,
            "group_pricing": [
                {
                    "pax_range": f"{r.min_pax}-{r.max_pax}",
                    "foc": r.foc_count,
                    "price_per_person": r.price_per_person,
                    "sgl_supplement": r.sgl_supplement,
                }
                for r in quote.group_rows
            ],
        })

    record["prices_snapshot"] = quote.prices_snapshot

    with open(config.QUOTE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\n  [LOG] Quote saved to {config.QUOTE_LOG_FILE}")


def find_record(doc_id: str):
    """
    The logged snapshot for one generated document, or None.

    Pre:  doc_id is a Docs document ID.
    Post: returns the most recent matching record, or None when the log is
          absent, unreadable, or holds no entry. Never raises: the log lives on
          an ephemeral filesystem and is expected to be missing.

    Callers must treat the result as a hint only. Itineraries are routinely
    hand-edited after generation, so a record can disagree with its own document.
    """
    if not os.path.exists(config.QUOTE_LOG_FILE):
        return None
    found = None
    try:
        with open(config.QUOTE_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or doc_id not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("doc_id") == doc_id:
                    found = record
    except OSError:
        return None
    return found


def staging_hints(doc_id: str) -> dict:
    """
    The fields a document cannot state: party size and room counts.

    Post: returns {} when no record exists, so a missing log degrades to blanks.
    """
    record = find_record(doc_id)
    if not record:
        return {}
    return {
        "num_people":   record.get("num_people"),
        "single_rooms": record.get("single_rooms"),
        "double_rooms": record.get("double_rooms"),
        "day_codes":    record.get("day_codes"),
    }
