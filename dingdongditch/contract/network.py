"""Bounded network assertion and external-trace contracts.

The runtime observes only metadata exposed by the browser: it never captures
request or response bodies.  A trace request is deliberately separate from a
network assertion so debug capture cannot influence verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NetworkUrlMatchMode(str, Enum):
    """Explicit bounded URL matching modes.

    ``CONTAINS`` is retained as the compatibility interpretation of the
    legacy ``network_url_substring`` field.  Query strings and fragments are
    intentionally not matchable by this contract.
    """

    CONTAINS = "contains"
    EXACT = "exact"
    PATH_EXACT = "path_exact"
    PATH_CONTAINS = "path_contains"


class NetworkArtifactKind(str, Enum):
    """External artifact kinds currently safe for per-operation capture."""

    SANITIZED_TRACE = "sanitized_trace"


@dataclass(frozen=True)
class NetworkArtifactRequest:
    """Explicit request for a bounded Layer-3 network trace.

    This is not HAR capture.  Playwright HAR is context-wide and would include
    unrelated session traffic, so it is intentionally not exposed as an
    operation-level feature.  The exported trace contains no bodies or
    headers, and the receipt receives only a safe filename/ID reference.
    """

    kind: NetworkArtifactKind = NetworkArtifactKind.SANITIZED_TRACE
    max_records: int = 32

    def validate(self) -> None:
        if not isinstance(self.kind, NetworkArtifactKind):
            raise ValueError("network artifact kind is unsupported")
        if (
            not isinstance(self.max_records, int)
            or isinstance(self.max_records, bool)
            or not 1 <= self.max_records <= 128
        ):
            raise ValueError("network artifact max_records must be between 1 and 128")

    def describe(self) -> dict[str, object]:
        return {"kind": self.kind.value, "max_records": self.max_records}
