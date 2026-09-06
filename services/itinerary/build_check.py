"""
services/itinerary/build_check.py

Whether a request would build a document, asked without building one.

WP7 is a first run: ten requests, a check, then ten itineraries. This is the
check. It runs the whole generation path short of the render — match a route,
bind the days to templates, price the quote, validate — and reports what each
request is missing.

Nothing here renders. `preview_itinerary` stops before `generate_document`, and
a document reaches a customer's Drive, so a human starts that (ws-03 D15).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BuildCheck:
    """One request, and whether the generator could answer it."""
    key: str
    name: str = ""
    day_count: int = 0
    can_build: bool = False
    matched_route: str = ""
    match_score: float = 0.0
    confidence: str = ""
    bound_codes: list = field(default_factory=list)
    coverage_gaps: list = field(default_factory=list)
    validation_errors: list = field(default_factory=list)
    quote: Optional[float] = None
    error: str = ""

    @property
    def days_bound(self) -> int:
        return len(self.bound_codes)

    @property
    def statement(self) -> str:
        if self.error:
            return f"{self.key}: the check itself failed — {self.error}"
        verdict = "would build" if self.can_build else "would not build"
        return (f"{self.key}: {verdict}, {self.days_bound} of {self.day_count} "
                f"day(s) bound, route {self.matched_route or 'none'} "
                f"at {self.match_score:.2f}")


def check_request(normalized) -> BuildCheck:
    """
    Ask the generation path what it would do with one request.

    Pre:  `normalized` is a NormalizedRequest.
    Post: a BuildCheck naming what bound, what did not, and why. No document is
          rendered and no sheet cell is written.

    Blame: an exception inside the pipeline is recorded on the check rather than
    raised. One request that cannot be read must not stop a run of ten, and a
    run that stops halfway reports a pass rate nobody can trust.
    """
    from services.itinerary.generator import preview_itinerary

    check = BuildCheck(key=normalized.key, name=normalized.customer_name,
                       day_count=normalized.day_count)
    try:
        preview = preview_itinerary(normalized)
    except Exception as exc:
        check.error = str(exc)
        return check

    check.can_build = bool(preview.can_generate_document)
    check.matched_route = preview.matched_route_name or ""
    check.match_score = float(preview.confidence_score or 0.0)
    check.confidence = preview.confidence_level or ""
    check.bound_codes = list(preview.bound_day_codes or [])
    check.coverage_gaps = list(preview.coverage_gaps or [])
    check.validation_errors = list(preview.validation_errors or [])
    check.quote = getattr(preview, "estimated_quote", None)
    return check


def format_run(checks: list) -> str:
    """
    The run as a reader marks it.

    Post: one line per request, then the pass rate with its denominator. A rate
          quoted with no denominator is the fault this workstream already made
          once, when 369 of 409 rejections stayed hidden.
    """
    lines = [check.statement for check in checks]
    buildable = sum(1 for check in checks if check.can_build)
    failed = sum(1 for check in checks if check.error)
    lines.append("")
    lines.append(f"{buildable} of {len(checks)} request(s) would build a document"
                 + (f"; {failed} could not be checked at all" if failed else ""))
    gaps = sum(len(check.coverage_gaps) for check in checks)
    if gaps:
        lines.append(f"{gaps} uncovered day(s) across the run")
    return "\n".join(lines)
