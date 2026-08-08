"""Bounded, machine-first public evidence helpers.

Runtime code may need a full transient browser observation to decide a verdict.
Published receipts never need a page dump.  These helpers produce the compact,
sanitized form that is safe to retain and serialize.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dingdongditch.authentication.secrets import redact
from dingdongditch.evidence.models import EvidenceSignal

MAX_EVIDENCE_STRING_CHARS = 512
MAX_DOM_TEXT_CHARS = 256
MAX_EVIDENCE_MAPPING_ITEMS = 24
MAX_EVIDENCE_LIST_ITEMS = 24
MAX_EVIDENCE_DEPTH = 5
MAX_SAFE_ATTRIBUTES = 12
MAX_RECEIPT_SIGNALS = 128

_SENSITIVE_KEY_PARTS = (
    "secret", "password", "token", "authorization", "credential", "cookie",
    "session", "api_key", "apikey", "otp", "totp", "private",
)
_LOCAL_PATH = re.compile(r"(?:^[A-Za-z]:[\\/]|^/(?:home|users|private|var)/)", re.I)
_TOKENISH = re.compile(r"(?:bearer\s+|\beyJ[a-zA-Z0-9_-]{12,}|\bsk-[a-zA-Z0-9_-]{12,})", re.I)


def _sensitive_key(key: str | None) -> bool:
    return bool(key and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS))


def _safe_string(value: str, *, key: str | None = None, limit: int = MAX_EVIDENCE_STRING_CHARS) -> str:
    if key is not None and (key.lower() == "url" or key.lower().endswith("_url")):
        try:
            parsed = urlsplit(value)
            # Query parameter values routinely hold bearer/session values.  The
            # receipt never needs them to justify a network verdict.
            value = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        except ValueError:
            value = value.split("?", 1)[0].split("#", 1)[0]
    if _sensitive_key(key) or _LOCAL_PATH.search(value) or _TOKENISH.search(value):
        return "<redacted>"
    if len(value) <= limit:
        return value
    return f"{value[:limit]}…<truncated:{len(value) - limit}>"


def sanitize_evidence_value(
    value: Any,
    *,
    key: str | None = None,
    depth: int = 0,
    string_limit: int = MAX_EVIDENCE_STRING_CHARS,
) -> Any:
    """Redact secret/path-like values and enforce deterministic shape limits."""
    if _sensitive_key(key):
        return "<redacted>"
    if depth >= MAX_EVIDENCE_DEPTH:
        return "<truncated:depth>"
    if isinstance(value, str):
        return _safe_string(value, key=key, limit=string_limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        sanitized = redact(value)
        items = list(sanitized.items())[:MAX_EVIDENCE_MAPPING_ITEMS]
        result = {
            str(item_key): sanitize_evidence_value(
                item_value, key=str(item_key), depth=depth + 1, string_limit=string_limit
            )
            for item_key, item_value in items
        }
        if len(sanitized) > len(items):
            result["_truncated_mapping_items"] = len(sanitized) - len(items)
        return result
    if isinstance(value, (list, tuple)):
        values = list(value)
        result = [
            sanitize_evidence_value(item, depth=depth + 1, string_limit=string_limit)
            for item in values[:MAX_EVIDENCE_LIST_ITEMS]
        ]
        if len(values) > len(result):
            result.append(f"<truncated:list_items:{len(values) - len(result)}>")
        return result
    return _safe_string(repr(value), key=key, limit=string_limit)


def bounded_signals(signals: list[EvidenceSignal]) -> list[EvidenceSignal]:
    """Copy signals for a receipt, sanitizing payloads without affecting runtime use."""
    return [
        EvidenceSignal(
            signal_id=signal.signal_id,
            kind=signal.kind,
            availability=signal.availability,
            collected_at_ms=signal.collected_at_ms,
            payload=sanitize_evidence_value(signal.payload),
            notes=_safe_string(signal.notes, limit=MAX_DOM_TEXT_CHARS),
        )
        for signal in signals[-MAX_RECEIPT_SIGNALS:]
    ]


def _safe_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    items = list(attributes.items())[:MAX_SAFE_ATTRIBUTES]
    result = {
        str(name): sanitize_evidence_value(value, key=str(name), string_limit=128)
        for name, value in items
    }
    if len(attributes) > len(items):
        result["_truncated_attribute_count"] = len(attributes) - len(items)
    return result


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def failed_expectation_evidence(
    *,
    expectation_type: str,
    expected: dict[str, Any],
    observed: dict[str, Any],
    freshness_ok: bool | None,
) -> dict[str, Any]:
    """Build bounded semantic evidence for one failed or indeterminate check."""
    safe_expected = sanitize_evidence_value(expected)
    safe_observed = sanitize_evidence_value(observed, string_limit=MAX_DOM_TEXT_CHARS)
    resolution = safe_observed.get("target_resolution") if isinstance(safe_observed, dict) else None
    attrs = safe_observed.get("attributes") if isinstance(safe_observed, dict) else {}
    attrs = attrs if isinstance(attrs, dict) else {}
    uniquely_resolved = bool(
        isinstance(safe_observed, dict)
        and safe_observed.get("exists") is True
        and safe_observed.get("ambiguous") is not True
        and safe_observed.get("match_count") == 1
    )
    structural = {
        "tag": safe_observed.get("tag") if isinstance(safe_observed, dict) else None,
        "role": safe_observed.get("role") if isinstance(safe_observed, dict) else None,
        "ancestor_tags": (
            safe_observed.get("ancestor_tags", []) if isinstance(safe_observed, dict) else []
        ),
        "child_element_count": (
            safe_observed.get("child_element_count") if isinstance(safe_observed, dict) else None
        ),
    }
    target = {
        "resolved_uniquely": uniquely_resolved,
        "role": structural["role"],
        "safe_attributes": _safe_attributes(attrs),
        "structural_fingerprint": _fingerprint(
            {
                "tag": structural["tag"],
                "role": structural["role"],
                "attributes": _safe_attributes(attrs),
                "resolution": {
                    "count": safe_observed.get("match_count") if isinstance(safe_observed, dict) else None,
                    "failure_kind": resolution.get("failure_kind") if isinstance(resolution, dict) else None,
                },
            }
        ),
    }
    evidence: dict[str, Any] = {
        "expectation_type": expectation_type,
        "expected": safe_expected,
        "observed": safe_observed,
        "target": target,
        "structural_evidence": structural if uniquely_resolved else None,
        "target_resolution": sanitize_evidence_value(resolution),
        "evidence_fresh": freshness_ok,
    }
    if isinstance(safe_observed, dict):
        evidence["state_difference"] = {
            key: safe_observed.get(key)
            for key in ("exists", "visible", "enabled", "in_viewport", "checked", "text")
            if key in safe_observed
        }
    return evidence
