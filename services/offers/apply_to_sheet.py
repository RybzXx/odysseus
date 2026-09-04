"""
services/offers/apply_to_sheet.py

Writes approved catalogue changes to the `templates` tab of the
`Pricing_information` Google Sheet.

This is the only code in the repository that changes the catalogue, and it is
deliberately hard to trigger: it writes nothing unless asked explicitly, it
refuses to run at all if the sheet is not in a state where writes are safe, and
it reads back what it wrote.

Every lesson here was paid for once already, in `docs/docaut-staging.md`:

  Merged cells silently destroy data. Sheets keeps only a merged range's
  top-left cell on write and discards the rest without error, so a merge
  anywhere in the target range means refusing rather than writing.

  Header order is read live. An inserted column shifts every row, so the column
  order is taken from the sheet at write time, never from a constant.

  Write access cannot be checked by asking. The credentials carry `drive.file`,
  which only exposes app-created files, and the Sheets API exposes no permission
  field. Clearing an already-empty cell is a no-op that still requires edit
  rights, so that is the probe.
"""
from __future__ import annotations

import logging
from typing import Optional

from services.offers.catalogue import TEMPLATE_FIELDS
from services.offers.proposals import (
    KIND_NEW,
    KIND_REVISION,
    TemplateProposal,
    iter_proposals,
    mark_applied,
)

logger = logging.getLogger(__name__)

TEMPLATES_TAB = "templates"

# A column far to the right of the 11 the catalogue uses. Clearing it changes
# nothing and proves edit rights.
_WRITE_PROBE_RANGE = f"{TEMPLATES_TAB}!Z1"


class SheetApplyError(Exception):
    """The sheet is not in a state where the catalogue can be safely written."""


def _sheets_service():
    from services.itinerary.pipeline.google_clients import credentials
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=credentials()).spreadsheets()


def _column_letter(index: int) -> str:
    """0 -> A. Sheets ranges are letters, and the catalogue may outgrow Z."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def preflight(sheet_id: str, service=None) -> dict:
    """
    Refuse early, and say why, rather than half-writing the catalogue.

    Post: returns the live header order and row count. Raises SheetApplyError if
          the tab is missing, carries a merged range, has headers that do not
          cover the catalogue's fields, or cannot be written to.
    """
    service = service or _sheets_service()
    metadata = service.get(spreadsheetId=sheet_id).execute()

    tab = next((s for s in metadata.get("sheets", [])
                if s["properties"]["title"] == TEMPLATES_TAB), None)
    if tab is None:
        raise SheetApplyError(f"no {TEMPLATES_TAB!r} tab in this spreadsheet")
    merges = tab.get("merges") or []
    if merges:
        raise SheetApplyError(
            f"{TEMPLATES_TAB} has {len(merges)} merged range(s); a write would "
            f"silently discard cells outside each merge's top-left corner"
        )

    values = service.values().get(
        spreadsheetId=sheet_id, range=f"{TEMPLATES_TAB}!A1:ZZ"
    ).execute().get("values", [])
    if not values:
        raise SheetApplyError(f"{TEMPLATES_TAB} is empty — no header row to write against")

    header = [name.strip() for name in values[0]]
    missing = [name for name in TEMPLATE_FIELDS if name not in header]
    if missing:
        raise SheetApplyError(f"{TEMPLATES_TAB} header is missing: {', '.join(missing)}")

    try:
        service.values().clear(spreadsheetId=sheet_id, range=_WRITE_PROBE_RANGE).execute()
    except Exception as exc:
        raise SheetApplyError(f"no write access to {TEMPLATES_TAB}: {exc}") from exc

    codes = {row[header.index("code")].strip(): index + 2       # +2: 1-based, past header
             for index, row in enumerate(values[1:])
             if len(row) > header.index("code") and row[header.index("code")].strip()}
    return {"header": header, "row_count": len(values) - 1, "row_by_code": codes}


def _row_for(proposal: TemplateProposal, header: list) -> list:
    """
    Order a proposal's fields to match the sheet as it is right now.

    Post: one value per header column; a column the catalogue does not know
          about is left empty rather than guessed at.
    """
    row = []
    for column in header:
        value = proposal.fields.get(column, "")
        if isinstance(value, bool):
            value = "TRUE" if value else "FALSE"
        row.append(value)
    return row


def apply_approved(
    sheet_id: str,
    dry_run: bool = True,
    service=None,
    only: Optional[list] = None,
) -> dict:
    """
    Write every approved, named, not-yet-applied proposal to the catalogue.

    Pre:  the sheet passes `preflight`.
    Post: with `dry_run` (the default) nothing is written and the plan is
          returned. Otherwise each new template is appended and each revision
          updates its target row in place, every written row is read back and
          compared, and each applied proposal is marked so a second run cannot
          write it twice.

    Blame: a proposal approved without a code is a review omission, not a bug
    here — it is reported as skipped rather than written under a blank name. A
    revision whose target no longer exists is reported the same way.
    """
    service = service or _sheets_service()
    state = preflight(sheet_id, service)
    header, row_by_code = state["header"], state["row_by_code"]

    plan = {"appends": [], "updates": [], "skipped": [], "dry_run": dry_run,
            "written": 0, "verified": 0}

    for proposal in iter_proposals():
        if only and proposal.proposal_id not in only:
            continue
        code = (proposal.fields.get("code") or "").strip()
        if proposal.status != "approved" or proposal.applied_at:
            continue
        if not code:
            plan["skipped"].append({"proposal_id": proposal.proposal_id,
                                    "reason": "approved without a code"})
            continue
        if proposal.kind == KIND_REVISION and proposal.target_code not in row_by_code:
            plan["skipped"].append({"proposal_id": proposal.proposal_id,
                                    "reason": f"target {proposal.target_code} is not in the sheet"})
            continue
        if proposal.kind == KIND_NEW and code in row_by_code:
            plan["skipped"].append({"proposal_id": proposal.proposal_id,
                                    "reason": f"code {code} already exists"})
            continue

        entry = {"proposal_id": proposal.proposal_id, "code": code,
                 "row": _row_for(proposal, header)}
        if proposal.kind == KIND_REVISION:
            entry["sheet_row"] = row_by_code[proposal.target_code]
            plan["updates"].append(entry)
        else:
            plan["appends"].append(entry)

    if dry_run:
        return plan

    last_column = _column_letter(len(header) - 1)

    for entry in plan["updates"]:
        target = f"{TEMPLATES_TAB}!A{entry['sheet_row']}:{last_column}{entry['sheet_row']}"
        service.values().update(
            spreadsheetId=sheet_id, range=target,
            valueInputOption="RAW", body={"values": [entry["row"]]},
        ).execute()
        plan["written"] += 1
        written = service.values().get(spreadsheetId=sheet_id, range=target).execute()
        if (written.get("values") or [[]])[0] == entry["row"]:
            plan["verified"] += 1
        mark_applied(entry["proposal_id"])

    if plan["appends"]:
        service.values().append(
            spreadsheetId=sheet_id, range=f"{TEMPLATES_TAB}!A1",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [entry["row"] for entry in plan["appends"]]},
        ).execute()
        after = preflight(sheet_id, service)["row_by_code"]
        for entry in plan["appends"]:
            plan["written"] += 1
            if entry["code"] in after:
                plan["verified"] += 1
            mark_applied(entry["proposal_id"])

    if plan["written"] != plan["verified"]:
        logger.error("catalogue write verified %d of %d rows",
                     plan["verified"], plan["written"])
    return plan
