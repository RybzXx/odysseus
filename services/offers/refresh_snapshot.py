"""
services/offers/refresh_snapshot.py

Rewrites the vendored template snapshot from the `templates` sheet tab.

The sheet is the catalogue's master copy. `services/offers/data/templates/*.json`
is a snapshot of it, and both the generation pipeline and the itinerary desk read
that snapshot rather than the sheet. A stale snapshot is therefore invisible: the
desk proposes over a vocabulary the owner has already grown, and the extra rows
simply never appear.

This is the only writer of that directory. It goes one way, sheet to disk. A day
that exists only on disk is reported and left alone, because deleting a row on
the strength of one failed read would lose it.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from services.offers.apply_to_sheet import (
    TEMPLATES_TAB,
    SheetApplyError,
    _sheets_service,
)
from services.offers.catalogue import TEMPLATES_DIR

# The sheet holds these two as JSON text in one cell. On disk they are real
# lists, because that is the shape the pipeline's DayTemplate expects.
_JSON_COLUMNS = {"included_sites_json": "included_sites",
                 "pricing_tags_json": "pricing_tags"}

_BOOL_COLUMNS = ("active", "needs_review")

_TRUE_WORDS = {"true", "yes", "1", "y", "t"}


def _as_bool(raw: str, default: bool = False) -> bool:
    text = (raw or "").strip().lower()
    if not text:
        return default
    return text in _TRUE_WORDS


# A site or pricing code as the sheet writes it: capitals, digits, underscore.
_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def _as_list(raw: str) -> tuple:
    """
    Post: (list, complaint). The complaint is "" when the cell read cleanly.

    Pre:  `raw` is one cell of `included_sites_json` or `pricing_tags_json`.

    Several rows were typed by hand and hold `[TRF_FEE]` rather than
    `["TRF_FEE"]`. That is not JSON, but the site code in it is not in doubt, so
    it is recovered. Returning an empty list instead would drop a transfer fee
    from a priced day and say nothing.

    Blame: a cell that parses to nothing while holding text is reported, never
    blanked in silence. `[]` is an empty list on purpose and draws no complaint.
    """
    text = (raw or "").strip()
    if not text:
        return [], ""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        codes = _CODE_RE.findall(text)
        if not codes:
            return [], "holds no readable code"
        return codes, (f"is not JSON. Read {len(codes)} code(s) from it: "
                       f"{', '.join(codes)}")
    if isinstance(value, list):
        kept = [str(item).strip() for item in value if str(item).strip()]
        if len(kept) != len(value):
            return kept, f"holds {len(value) - len(kept)} empty entry(s)"
        return kept, ""
    if isinstance(value, str):
        return ([value], "") if value else ([], "")
    return [], f"is a {type(value).__name__}, not a list"


def read_sheet_rows(sheet_id: str, service=None) -> tuple:
    """
    Post: ({code: row dict}, [notes]) read from the `templates` tab.

    Pre:  the tab carries a header row. A row with no code is skipped, because
          the code is the file name and the identity.
    """
    service = service or _sheets_service()
    values = service.values().get(
        spreadsheetId=sheet_id, range=f"{TEMPLATES_TAB}!A1:ZZ"
    ).execute().get("values", [])
    if not values:
        raise SheetApplyError(f"{TEMPLATES_TAB} is empty")

    header = [name.strip() for name in values[0]]
    if "code" not in header:
        raise SheetApplyError(f"{TEMPLATES_TAB} has no 'code' column")

    rows, notes = {}, []
    for number, raw_row in enumerate(values[1:], start=2):
        cells = {name: (raw_row[index] if index < len(raw_row) else "")
                 for index, name in enumerate(header)}
        code = (cells.get("code") or "").strip()
        if not code:
            continue
        if code in rows:
            notes.append(f"row {number}: {code} appears more than once, "
                         f"the later row wins")

        row = {"code": code}
        for name in ("title", "city", "region", "overnight_city",
                     "full_text", "internal_notes"):
            row[name] = (cells.get(name) or "").strip()
        for column, field in _JSON_COLUMNS.items():
            row[field], complaint = _as_list(cells.get(column, ""))
            if complaint:
                notes.append(f"row {number}: {code} {column} {complaint}")
        row["active"] = _as_bool(cells.get("active", ""), default=True)
        row["needs_review"] = _as_bool(cells.get("needs_review", ""))
        rows[code] = row
    return rows, notes


def refresh(sheet_id: str, write: bool = False,
            templates_dir: Optional[str] = None) -> dict:
    """
    Bring the snapshot in line with the sheet.

    Pre:  `write` is False by default, so a caller sees the plan before the
          directory changes.
    Post: {"added", "changed", "unchanged", "only_on_disk", "notes", "written"}.
          Every code the sheet holds gets a file that matches the sheet.

    Blame: a code that exists only on disk is named and kept. The sheet is the
    master copy, but one failed read is not evidence that a row was deleted, and
    a wrongly deleted day is not recoverable from here.
    """
    directory = templates_dir or TEMPLATES_DIR
    rows, notes = read_sheet_rows(sheet_id)

    on_disk = set()
    if os.path.isdir(directory):
        on_disk = {name[:-5] for name in os.listdir(directory)
                   if name.endswith(".json")}

    added, changed, unchanged = [], [], []
    for code, row in sorted(rows.items()):
        path = os.path.join(directory, f"{code}.json")
        existing = None
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    existing = json.load(handle)
            except (json.JSONDecodeError, OSError):
                existing = None
        if existing is None:
            added.append(code)
        elif existing != row:
            changed.append(code)
        else:
            unchanged.append(code)

    written = 0
    if write:
        os.makedirs(directory, exist_ok=True)
        for code in added + changed:
            path = os.path.join(directory, f"{code}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(rows[code], handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            written += 1

    return {
        "added": added,
        "changed": changed,
        "unchanged": unchanged,
        "only_on_disk": sorted(on_disk - set(rows)),
        "notes": notes,
        "written": written,
        "sheet_rows": len(rows),
    }


def format_plan(plan: dict) -> str:
    lines = [
        f"sheet rows      {plan['sheet_rows']}",
        f"new on disk     {len(plan['added'])}",
        f"changed         {len(plan['changed'])}",
        f"unchanged       {len(plan['unchanged'])}",
        f"only on disk    {len(plan['only_on_disk'])}",
    ]
    if plan["added"]:
        lines.append("  add:     " + ", ".join(plan["added"]))
    if plan["changed"]:
        lines.append("  change:  " + ", ".join(plan["changed"]))
    if plan["only_on_disk"]:
        lines.append("  kept:    " + ", ".join(plan["only_on_disk"]))
    for note in plan["notes"]:
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    from services.itinerary.pipeline import config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="write the files. Without it, only the plan prints.")
    args = parser.parse_args(argv)

    sheet_id = config.JSON_DB_SHEET_ID
    plan = refresh(sheet_id, write=False)
    print(format_plan(plan))

    if not args.write:
        print("\nplan only. Pass --write to apply.")
        return 0

    done = refresh(sheet_id, write=True)
    print(f"\nwrote {done['written']} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
