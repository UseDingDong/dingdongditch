from __future__ import annotations

from enum import Enum


class Verdict(str, Enum):
    """Top-level verdicts: action success is not verified outcome."""

    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INDETERMINATE = "INDETERMINATE"
