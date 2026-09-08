"""
services/itinerary/record_paths.py

One record id, one file, inside one directory and nowhere else.

Three stores on this desk name a file after an id a caller supplies: drafts,
runs and the conversation cache. Each one joined the id straight on, and each
one therefore wrote wherever the id pointed.

Measured against the running desk on 2026-09-07. `PUT /api/itinerary/
conversations/..%5C..%5Cpwn` answered 200 and wrote into the repository root,
and `C:%5CWindows%5CTemp%5Cpwn` wrote outside the repository altogether.
Starlette matches a path parameter against everything except a forward slash,
so a backslash arrives whole, and Windows reads it as a separator.

The check belongs here rather than at each route. A route that forgot it would
be the one route that writes anywhere, and a reader of the route could not tell
which routes remembered.

An id this module accepts holds letters, digits, and the three characters the
real ids use. It never holds a separator, a colon, or a run of dots.
"""
from __future__ import annotations

import os
import re

# What every id on this desk looks like. `dr-92ae465d864d`, `run-3bb999b5e74e`
# and the Drive id `1CKw3Udgg1xYpTsE_TZNzV4SdJbnW5QVK` all match.
#
# A dot is absent on purpose. No id here holds one, and allowing it would make
# `..` a question about run length rather than about characters.
_RECORD_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class RecordIdError(ValueError):
    """The id names something other than one record in one directory."""


def is_record_id(text: str) -> bool:
    """
    Post: whether `text` names one record and cannot name anything else.

    A caller that wants to answer 404 rather than 422 asks this first.
    """
    return bool(_RECORD_ID.match(text or ""))


def record_path(directory: str, record_id: str, suffix: str = ".json") -> str:
    """
    The file one record id names inside one directory.

    Pre:  `directory` is the store's own directory. `record_id` came from a
          caller, and this function assumes it is hostile.
    Post: a path inside `directory`, one level deep, ending in `suffix`.
    Inv:  the result never leaves `directory`. A separator, a drive letter, a
          dot run and an empty id are all refused before any path is built.

    Blame: an id that fails the pattern is a caller error and raises
    RecordIdError. Returning a safe default would write one record under
    another record's name, which is worse than a refusal.
    """
    if not is_record_id(record_id):
        raise RecordIdError(
            f"{record_id!r} is not a record id. An id holds letters, digits, "
            f"'-' and '_', and it never holds a path separator")
    return os.path.join(directory, f"{record_id}{suffix}")
