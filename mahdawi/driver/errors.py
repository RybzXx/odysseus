"""mahdawi.driver.errors — the one failure the driver raises."""
from __future__ import annotations


class DriverError(RuntimeError):
    """
    A step could not be completed, so the run must abort.

    Raised when a required control does not resolve, an adb call fails, or a
    package is malformed. The caller marks the post failed and posts nothing
    further (fail closed, spec 0.3).
    """
