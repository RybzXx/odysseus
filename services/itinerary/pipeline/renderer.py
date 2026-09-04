"""
BilWeekend — Google Docs Renderer
Takes an ordered list of DocumentSection objects and writes them to a new Google Doc.

Key design decisions:
- All content is appended using endOfSegmentLocation (forward order, no reversing).
- Formatting ranges are calculated from running character offset.
- Overnight line is plain/italic, not bulleted.
- HEADING_1 for document title, HEADING_2 for day headers and section headers.
- Bullets use BULLET_DISC preset.
- All section requests are accumulated and issued in a single batchUpdate.
"""
import os
from services.itinerary.pipeline import config
from services.itinerary.pipeline import google_clients


def render(sections: list) -> str:
    """
    Creates a Google Doc in the configured folder, writes all sections, and returns the doc_id.

    All section content is accumulated into a single batchUpdate call (Docs API
    applies requests within one call in order, so this is equivalent to issuing
    them one batchUpdate at a time) instead of one HTTP round trip per
    section/day. For a long itinerary that previously meant 25+ sequential
    blocking calls — slow enough on constrained hosting to trip gateway
    timeouts — this cuts it down to a handful.
    """
    # Resource handles come from google_clients, which builds each one once per
    # process. Reconstructing the documents() resource costs ~37 MB a time, and
    # this function used to reach for it six times per document.

    # 1. Create the document
    doc_metadata = {
        "name": _get_title(sections),
        "parents": [config.GOOGLE_DRIVE_FOLDER_ID],
        "mimeType": "application/vnd.google-apps.document",
    }
    doc = google_clients.drive_files().create(
        body=doc_metadata,
    ).execute(http=google_clients.http())
    doc_id = doc["id"]

    # 2. Set default font by inserting a placeholder, then delete it
    _init_document_font(doc_id)

    # 3. Insert BilWeekend logo at top of document (kept as its own fault-isolated
    # call since it depends on a separate Drive upload and is allowed to fail
    # non-fatally without aborting the rest of the document).
    offset = 1
    offset = _insert_logo(doc_id, offset)

    # 4. Build every section's requests locally, then write them all in one call.
    all_requests: list[dict] = []
    for section in sections:
        section_requests, offset = _build_section_requests(section, offset)
        all_requests.extend(section_requests)

    if all_requests:
        google_clients.documents().batchUpdate(
            documentId=doc_id, body={"requests": all_requests}
        ).execute(http=google_clients.http())

    return doc_id


def _get_title(sections: list) -> str:
    for s in sections:
        if s.section_type == "title":
            return s.content.get("text", "Untitled Itinerary")
    return "Untitled Itinerary"


def _init_document_font(doc_id: str):
    """Inserts a single space to establish Arial 12pt as the document base font, then deletes it."""
    google_clients.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": " "}},
        {"updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": 2},
            "textStyle": {
                "fontSize": {"magnitude": 12, "unit": "PT"},
                "weightedFontFamily": {"fontFamily": "Arial"},
            },
            "fields": "fontSize,weightedFontFamily",
        }},
        {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 2}}},
    ]}).execute(http=google_clients.http())


def _get_or_upload_logo() -> str | None:
    """
    Returns a public Google Drive URL for the BilWeekend logo PNG.
    Uploads the file on first call and caches its Drive file ID locally.
    Returns None if the logo PNG is not found.
    """
    logo_path = config.LOGO_PNG_PATH
    cache_path = config.LOGO_DRIVE_CACHE

    if not os.path.exists(logo_path):
        return None

    # Return cached URL if we've already uploaded
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            file_id = f.read().strip()
        if file_id:
            return f"https://drive.google.com/uc?id={file_id}&export=view"

    # Upload logo to Google Drive
    from googleapiclient.http import MediaFileUpload
    file_metadata = {"name": "BilWeekendLogo.png", "mimeType": "image/png"}
    media = MediaFileUpload(logo_path, mimetype="image/png", resumable=False)
    uploaded = google_clients.drive_files().create(
        body=file_metadata, media_body=media, fields="id"
    ).execute(http=google_clients.http())
    file_id = uploaded["id"]

    # Make the file publicly readable (required for Docs API insertInlineImage)
    google_clients.drive_permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"},
    ).execute(http=google_clients.http())

    # Cache the file ID
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(file_id)

    return f"https://drive.google.com/uc?id={file_id}&export=view"


def _insert_logo(doc_id: str, offset: int) -> int:
    """
    Inserts the BilWeekend logo as a centered inline image at the top of the document.
    Size: 2.38 × 2.38 inches (aspect ratio locked). Returns the new offset after the logo paragraph.
    """
    try:
        logo_url = _get_or_upload_logo()
    except Exception as e:
        print(f"[LOGO] Upload/fetch failed: {e}")
        return offset  # Non-fatal — skip logo if Drive upload fails

    if not logo_url:
        print("[LOGO] No URL — skipping logo.")
        return offset

    print(f"[LOGO] Inserting image from: {logo_url}")

    # 2.38 inches expressed in PT (1 inch = 72 pt)
    SIZE_PT = 2.38 * 72  # 171.36

    try:
        # Insert image at end of (currently empty) document
        google_clients.documents().batchUpdate(documentId=doc_id, body={"requests": [
            {"insertInlineImage": {
                "endOfSegmentLocation": {"segmentId": ""},
                "uri": logo_url,
                "objectSize": {
                    "height": {"magnitude": SIZE_PT, "unit": "PT"},
                    "width":  {"magnitude": SIZE_PT, "unit": "PT"},
                },
            }},
        ]}).execute(http=google_clients.http())
        # Image is now at `offset` (1 char). Body terminator shifted to offset+1.

        # Insert newline after image to close the logo paragraph
        # then center that paragraph
        google_clients.documents().batchUpdate(documentId=doc_id, body={"requests": [
            {"insertText": {
                "endOfSegmentLocation": {"segmentId": ""},
                "text": "\n",
            }},
            {"updateParagraphStyle": {
                "range": {"startIndex": offset, "endIndex": offset + 2},
                "paragraphStyle": {"alignment": "CENTER"},
                "fields": "alignment",
            }},
        ]}).execute(http=google_clients.http())
        # Now: [offset: image][offset+1: \n][offset+2: body-terminator]
        print("[LOGO] Inserted successfully.")
        return offset + 2
    except Exception as e:
        print(f"[LOGO] insertInlineImage failed: {e}")
        return offset  # Non-fatal


def _build_section_requests(section, offset: int) -> tuple[list[dict], int]:
    """Builds one section's requests (without executing) and returns (requests, new_offset)."""
    st = section.section_type
    c = section.content

    if st == "title":
        return _render_title(c["text"], offset)
    elif st == "day":
        return _render_day(c, offset)
    elif st == "end_of_tour":
        return _render_bold_heading(c["text"], offset)
    elif st == "pricing":
        return _render_pricing(c, offset)
    elif st == "hotel_options":
        return _render_hotel_options(c, offset)
    elif st == "includes":
        return _render_includes(c, offset)
    elif st == "payment_notes":
        return _render_payment_notes(c, offset)
    elif st == "general_info_section":
        return _render_general_info_section(c, offset)
    elif st == "trip_section_title":
        return _render_trip_section_title(c["text"], offset)
    return [], offset


def _render_title(title: str, offset: int) -> tuple[list[dict], int]:
    text = title + "\n"
    end = offset + len(text)
    requests = [
        {"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": text}},
        {"updateParagraphStyle": {
            "range": {"startIndex": offset, "endIndex": end},
            "paragraphStyle": {"namedStyleType": "HEADING_1", "alignment": "CENTER"},
            "fields": "namedStyleType,alignment",
        }},
        {"updateTextStyle": {
            "range": {"startIndex": offset, "endIndex": end - 1},
            "textStyle": {
                "bold": True,
                "fontSize": {"magnitude": 20, "unit": "PT"},
            },
            "fields": "bold,fontSize",
        }},
    ]
    return requests, end


def _render_trip_section_title(title: str, offset: int) -> tuple[list[dict], int]:
    """Renders a day-trip section title (HEADING_1, 18pt bold, centered) with a blank line before it."""
    text = "\n" + title + "\n"
    t_start = offset + 1
    t_end = t_start + len(title)
    end = offset + len(text)
    requests = [
        {"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": text}},
        {"updateParagraphStyle": {
            "range": {"startIndex": t_start, "endIndex": t_end + 1},
            "paragraphStyle": {"namedStyleType": "HEADING_1", "alignment": "CENTER"},
            "fields": "namedStyleType,alignment",
        }},
        {"updateTextStyle": {
            "range": {"startIndex": t_start, "endIndex": t_end},
            "textStyle": {
                "bold": True,
                "fontSize": {"magnitude": 18, "unit": "PT"},
            },
            "fields": "bold,fontSize",
        }},
    ]
    return requests, end


def _render_day(content: dict, offset: int) -> tuple[list[dict], int]:
    """Renders a day: header (bold), bullet lines, overnight (italic plain text)."""
    requests = []
    current = offset

    # Day header line
    header_text = content["header"] + "\n"
    requests.append({"insertText": {
        "endOfSegmentLocation": {"segmentId": ""},
        "text": header_text,
    }})
    header_end = current + len(header_text)
    requests.append({"updateTextStyle": {
        "range": {"startIndex": current, "endIndex": header_end - 1},
        "textStyle": {"bold": True, "fontSize": {"magnitude": 13, "unit": "PT"}},
        "fields": "bold,fontSize",
    }})
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": current, "endIndex": header_end},
        "paragraphStyle": {"namedStyleType": "HEADING_2"},
        "fields": "namedStyleType",
    }})
    current = header_end

    # Bullet lines
    bullet_lines = content.get("bullet_lines", [])
    if bullet_lines:
        bullets_text = "\n".join(bullet_lines) + "\n"
        requests.append({"insertText": {
            "endOfSegmentLocation": {"segmentId": ""},
            "text": bullets_text,
        }})
        bullets_end = current + len(bullets_text)
        requests.append({"createParagraphBullets": {
            "range": {"startIndex": current, "endIndex": bullets_end},
            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
        }})
        requests.append({"updateTextStyle": {
            "range": {"startIndex": current, "endIndex": bullets_end},
            "textStyle": {
                "fontSize": {"magnitude": 11, "unit": "PT"},
                "weightedFontFamily": {"fontFamily": "Arial"},
            },
            "fields": "fontSize,weightedFontFamily",
        }})
        current = bullets_end

    # Overnight line (plain italic)
    overnight = content.get("overnight")
    if overnight:
        overnight_text = "\n" + overnight + "\n\n"
        requests.append({"insertText": {
            "endOfSegmentLocation": {"segmentId": ""},
            "text": overnight_text,
        }})
        ov_start = current + 1
        ov_end = current + 1 + len(overnight)
        requests.append({"updateTextStyle": {
            "range": {"startIndex": ov_start, "endIndex": ov_end},
            "textStyle": {
                "italic": True,
                "fontSize": {"magnitude": 11, "unit": "PT"},
                "weightedFontFamily": {"fontFamily": "Arial"},
            },
            "fields": "italic,fontSize,weightedFontFamily",
        }})
        current += len(overnight_text)

    return requests, current


def _render_bold_heading(text: str, offset: int) -> tuple[list[dict], int]:
    full = "\n" + text + "\n\n"
    text_start = offset + 1
    text_end = text_start + len(text)
    requests = [
        {"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": full}},
        {"updateParagraphStyle": {
            "range": {"startIndex": text_start, "endIndex": text_end + 1},
            "paragraphStyle": {"namedStyleType": "HEADING_2", "alignment": "CENTER"},
            "fields": "namedStyleType,alignment",
        }},
        {"updateTextStyle": {
            "range": {"startIndex": text_start, "endIndex": text_end},
            "textStyle": {"bold": True, "fontSize": {"magnitude": 13, "unit": "PT"}},
            "fields": "bold,fontSize",
        }},
    ]
    return requests, offset + len(full)


def _render_pricing(content: dict, offset: int) -> tuple[list[dict], int]:
    requests = []
    current = offset

    # Header
    header_text = "\n" + content.get("header", "Pricing") + "\n"
    requests.append({"insertText": {
        "endOfSegmentLocation": {"segmentId": ""},
        "text": header_text,
    }})
    h_start = current + 1
    h_end = h_start + len(content.get("header", "Pricing"))
    requests.append({"updateTextStyle": {
        "range": {"startIndex": h_start, "endIndex": h_end},
        "textStyle": {"bold": True, "fontSize": {"magnitude": 13, "unit": "PT"}},
        "fields": "bold,fontSize",
    }})
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": h_start, "endIndex": h_end + 1},
        "paragraphStyle": {"namedStyleType": "HEADING_2"},
        "fields": "namedStyleType",
    }})
    current += len(header_text)

    table_type = content.get("table_type", "individual")

    if table_type == "group":
        rows = content.get("rows", [])
        if rows:
            table_requests, current = _render_pricing_text_table(rows, current)
            requests.extend(table_requests)
        validity = content.get("validity_note", "")
        if validity:
            note_text = "\n" + validity + "\n"
            requests.append({"insertText": {
                "endOfSegmentLocation": {"segmentId": ""}, "text": note_text,
            }})
            n_start = current + 1
            n_end = n_start + len(validity)
            requests.append({"updateTextStyle": {
                "range": {"startIndex": n_start, "endIndex": n_end},
                "textStyle": {"bold": True, "italic": True,
                              "fontSize": {"magnitude": 10, "unit": "PT"}},
                "fields": "bold,italic,fontSize",
            }})
            current += len(note_text)
    else:
        # Individual breakdown
        lines = content.get("breakdown_lines", [])
        breakdown = "\n".join(lines)
        summary_parts = [
            breakdown,
            content.get("accommodation_cost", ""),
            content.get("subtotal", ""),
            content.get("markup", ""),
            content.get("final_total", ""),
            content.get("custom_total", ""),
            content.get("suv_note", ""),
            content.get("per_person", ""),
        ]
        full_text = "\n".join(p for p in summary_parts if p) + "\n\n"
        requests.append({"insertText": {
            "endOfSegmentLocation": {"segmentId": ""}, "text": full_text,
        }})
        current += len(full_text)

        validity = content.get("validity_note", "")
        if validity:
            note_text = validity + "\n"
            requests.append({"insertText": {
                "endOfSegmentLocation": {"segmentId": ""}, "text": note_text,
            }})
            current += len(note_text)

    return requests, current


def _render_hotel_options(content: dict, offset: int) -> tuple[list[dict], int]:
    requests = []
    current = offset

    header_text = "\n" + content.get("header", "Hotel Options by Star Tier") + "\n"
    requests.append({"insertText": {
        "endOfSegmentLocation": {"segmentId": ""},
        "text": header_text,
    }})
    h_start = current + 1
    h_end = h_start + len(content.get("header", "Hotel Options by Star Tier"))
    requests.append({"updateTextStyle": {
        "range": {"startIndex": h_start, "endIndex": h_end},
        "textStyle": {"bold": True, "fontSize": {"magnitude": 13, "unit": "PT"}},
        "fields": "bold,fontSize",
    }})
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": h_start, "endIndex": h_end + 1},
        "paragraphStyle": {"namedStyleType": "HEADING_2"},
        "fields": "namedStyleType",
    }})
    current += len(header_text)

    summary_lines = [l for l in content.get("summary_lines", []) if l]
    if summary_lines:
        summary_text = "\n".join(summary_lines) + "\n"
        requests.append({"insertText": {
            "endOfSegmentLocation": {"segmentId": ""},
            "text": summary_text,
        }})
        s_end = current + len(summary_text)
        requests.append({"createParagraphBullets": {
            "range": {"startIndex": current, "endIndex": s_end},
            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
        }})
        current = s_end

    tier_blocks = content.get("tier_blocks", [])
    for block in tier_blocks:
        title = block.get("title", "")
        if title:
            title_text = title + "\n"
            requests.append({"insertText": {
                "endOfSegmentLocation": {"segmentId": ""},
                "text": title_text,
            }})
            t_start = current
            t_end = current + len(title)
            requests.append({"updateTextStyle": {
                "range": {"startIndex": t_start, "endIndex": t_end},
                "textStyle": {"bold": True},
                "fields": "bold",
            }})
            current += len(title_text)

        lines = [l for l in block.get("lines", []) if l]
        if lines:
            city_text = "\n".join(lines) + "\n"
            requests.append({"insertText": {
                "endOfSegmentLocation": {"segmentId": ""},
                "text": city_text,
            }})
            c_end = current + len(city_text)
            requests.append({"createParagraphBullets": {
                "range": {"startIndex": current, "endIndex": c_end},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            }})
            current = c_end

    # Custom hotels block (if overrides were applied)
    custom_block = content.get("custom_block")
    if custom_block:
        cb_title = custom_block.get("title", "")
        if cb_title:
            cb_title_text = cb_title + "\n"
            requests.append({"insertText": {
                "endOfSegmentLocation": {"segmentId": ""},
                "text": cb_title_text,
            }})
            cb_start = current
            cb_end = current + len(cb_title)
            requests.append({"updateTextStyle": {
                "range": {"startIndex": cb_start, "endIndex": cb_end},
                "textStyle": {"bold": True},
                "fields": "bold",
            }})
            current += len(cb_title_text)
        cb_lines = [l for l in custom_block.get("lines", []) if l]
        if cb_lines:
            cb_text = "\n".join(cb_lines) + "\n"
            requests.append({"insertText": {
                "endOfSegmentLocation": {"segmentId": ""},
                "text": cb_text,
            }})
            cb_text_end = current + len(cb_text)
            requests.append({"createParagraphBullets": {
                "range": {"startIndex": current, "endIndex": cb_text_end},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            }})
            current = cb_text_end

    requests.append({"insertText": {
        "endOfSegmentLocation": {"segmentId": ""},
        "text": "\n",
    }})
    current += 1

    # Remove bullet inheritance from the trailing separator paragraph
    # so the next section does not inherit bullet formatting.
    requests.append({"deleteParagraphBullets": {
        "range": {"startIndex": current - 1, "endIndex": current},
    }})

    return requests, current


def _render_pricing_text_table(rows: list, offset: int) -> tuple[list[dict], int]:
    """Renders group pricing as a clean aligned plain-text table with a bold header row."""
    col_pax = 24
    col_price = 20
    header_row = f"{'PAX':<{col_pax}}{'Price / Person':<{col_price}}SGL Supplement\n"
    data_rows = [
        f"{row['pax_range']:<{col_pax}}{row['price_per_person']:<{col_price}}{row.get('sgl_supplement', '-')}\n"
        for row in rows
    ]
    full_text = "\n" + header_row + "".join(data_rows) + "\n"
    h_start = offset + 1
    h_end = h_start + len(header_row) - 1
    requests = [
        {"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": full_text}},
        {"updateTextStyle": {
            "range": {"startIndex": h_start, "endIndex": h_end},
            "textStyle": {"bold": True, "fontSize": {"magnitude": 11, "unit": "PT"}},
            "fields": "bold,fontSize",
        }},
    ]
    return requests, offset + len(full_text)


def _render_includes(content: dict, offset: int) -> tuple[list[dict], int]:
    requests = []
    current = offset

    header_text = "\nIncludes:\n"
    requests.append({"insertText": {
        "endOfSegmentLocation": {"segmentId": ""},
        "text": header_text,
    }})
    h_start = current + 1
    h_end = h_start + len("Includes:")
    requests.append({"updateTextStyle": {
        "range": {"startIndex": h_start, "endIndex": h_end},
        "textStyle": {"bold": True, "fontSize": {"magnitude": 12, "unit": "PT"}},
        "fields": "bold,fontSize",
    }})
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": h_start, "endIndex": h_end + 1},
        "paragraphStyle": {"namedStyleType": "HEADING_2"},
        "fields": "namedStyleType",
    }})
    current += len(header_text)

    items = [i for i in content.get("items", []) if i]
    if items:
        bullets_text = "\n".join(items) + "\n"
        requests.append({"insertText": {
            "endOfSegmentLocation": {"segmentId": ""},
            "text": bullets_text,
        }})
        b_end = current + len(bullets_text)
        requests.append({"createParagraphBullets": {
            "range": {"startIndex": current, "endIndex": b_end},
            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
        }})
        current = b_end

    # Insert a non-bulleted separator paragraph to prevent bullet inheritance
    # into subsequent sections (payment_notes, general_info_section, etc.)
    if items:
        trailing = current
        requests.append({"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": "\n"}})
        requests.append({"deleteParagraphBullets": {
            "range": {"startIndex": trailing, "endIndex": trailing + 1},
        }})
        current += 1

    optional = content.get("optional")
    if optional:
        opt_text = "\nOptional: " + optional + "\n"
        opt_insert_start = current
        requests.append({"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": opt_text}})
        opt_start = opt_insert_start + 1
        opt_end = opt_start + len("Optional:")
        requests.append({"updateTextStyle": {
            "range": {"startIndex": opt_start, "endIndex": opt_end},
            "textStyle": {"bold": True},
            "fields": "bold",
        }})
        current += len(opt_text)

    return requests, current


def _render_payment_notes(content: dict, offset: int) -> tuple[list[dict], int]:
    requests = []
    current = offset

    for key, note in content.items():
        note_text = "\nNote: " + note + "\n"
        requests.append({"insertText": {
            "endOfSegmentLocation": {"segmentId": ""},
            "text": note_text,
        }})
        # Bold "Note:"
        n_start = current + 1
        n_end = n_start + len("Note:")
        requests.append({"updateTextStyle": {
            "range": {"startIndex": n_start, "endIndex": n_end},
            "textStyle": {"bold": True},
            "fields": "bold",
        }})
        requests.append({"updateParagraphStyle": {
            "range": {"startIndex": n_start, "endIndex": current + len(note_text)},
            "paragraphStyle": {"alignment": "JUSTIFIED"},
            "fields": "alignment",
        }})
        current += len(note_text)

    return requests, current


def _render_general_info_section(content: dict, offset: int) -> tuple[list[dict], int]:
    requests = []
    current = offset

    heading = content.get("heading", "")
    body = content.get("body", "")

    heading_text = "\n" + heading + "\n"
    body_text = body + "\n"

    requests.append({"insertText": {
        "endOfSegmentLocation": {"segmentId": ""},
        "text": heading_text + body_text,
    }})
    h_start = current + 1
    h_end = h_start + len(heading)
    requests.append({"updateTextStyle": {
        "range": {"startIndex": h_start, "endIndex": h_end},
        "textStyle": {"bold": True, "fontSize": {"magnitude": 12, "unit": "PT"}},
        "fields": "bold,fontSize",
    }})
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": h_start, "endIndex": h_end + 1},
        "paragraphStyle": {"namedStyleType": "HEADING_2"},
        "fields": "namedStyleType",
    }})
    body_start = h_end + 1
    body_end = body_start + len(body)
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": body_start, "endIndex": body_end},
        "paragraphStyle": {"alignment": "JUSTIFIED"},
        "fields": "alignment",
    }})
    current += len(heading_text) + len(body_text)

    return requests, current
