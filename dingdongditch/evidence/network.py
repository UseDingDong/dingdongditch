"""Network evidence shaping shared by verification and Layer-3 trace capture."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dingdongditch.evidence.bounded import sanitize_evidence_value


def safe_network_url(value: object) -> str:
    """Retain only origin/path; query and fragments may carry credentials."""
    if not isinstance(value, str):
        return "<unavailable>"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<malformed-url>"
    if parsed.scheme and parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))
    # Browser URL values should be absolute.  Keep a bounded opaque fallback
    # rather than accidentally publishing a query string from a malformed URL.
    return value.split("?", 1)[0].split("#", 1)[0]


def safe_network_record(record: dict[str, Any]) -> dict[str, Any]:
    """Produce the only representation allowed in receipts/artifacts.

    Bodies and headers are intentionally absent.  This also means authorization
    and cookie values can never be emitted from the network collector.
    """
    request_at = record.get("request_observed_at_ms", record.get("recorded_at_ms"))
    response_at = record.get("response_observed_at_ms")
    elapsed = (
        max(0, response_at - request_at)
        if isinstance(request_at, int) and isinstance(response_at, int)
        else None
    )
    return sanitize_evidence_value(
        {
            "method": record.get("method"),
            "url": safe_network_url(record.get("url")),
            "request_observed_at_ms": request_at,
            "response_observed_at_ms": response_at,
            "status": record.get("status"),
            "elapsed_ms": elapsed,
            "request_failed": bool(record.get("request_failed", False)),
        }
    )


def network_record_fingerprint(record: dict[str, Any]) -> str:
    safe = safe_network_record(record)
    encoded = repr(sorted(safe.items())).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
