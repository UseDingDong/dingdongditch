"""Host-owned authority contracts for deterministic execution governance.

These contracts describe an execution envelope; they do not infer intent or
attempt to classify prompt injection.  A planner may propose an operation and
describe provenance, but only a host-installed envelope grants authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit


class ProvenanceClass(str, Enum):
    USER_AUTHORITY = "user_authority"
    HOST_POLICY = "host_policy"
    AGENT_REASONING = "agent_reasoning"
    WEB_UNTRUSTED = "web_untrusted"
    THIRD_PARTY_CONTENT = "third_party_content"
    SECRET_PROVIDER = "secret_provider"
    SYSTEM_RUNTIME = "system_runtime"


def merge_provenance(*sources: tuple[ProvenanceClass, ...] | list[ProvenanceClass]) -> tuple[ProvenanceClass, ...]:
    """Monotonically combine deterministic provenance labels.

    This helper never removes or upgrades a source label.  It is intentionally
    metadata plumbing, not a semantic prompt-injection detector.
    """
    merged: list[ProvenanceClass] = []
    for group in sources:
        for value in group:
            if not isinstance(value, ProvenanceClass):
                raise ValueError("provenance must contain ProvenanceClass values")
            if value not in merged:
                merged.append(value)
    return tuple(merged)


class FirewallOutcome(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    POLICY_REJECTED = "POLICY_REJECTED"
    AUTHORITY_INSUFFICIENT = "AUTHORITY_INSUFFICIENT"
    ORIGIN_NOT_ALLOWED = "ORIGIN_NOT_ALLOWED"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    AUTHORITY_EXPIRED = "AUTHORITY_EXPIRED"
    SIDE_EFFECT_BUDGET_EXCEEDED = "SIDE_EFFECT_BUDGET_EXCEEDED"
    PROVENANCE_POLICY_REJECTED = "PROVENANCE_POLICY_REJECTED"


_KNOWN_ACTION_TYPES = frozenset({
    "navigate", "click", "hover", "fill", "press_key", "select_option",
    "set_checked", "scroll_to_target", "wait_for", "switch_to_page",
    "close_page", "switch_to_opener", "download", "upload_file",
    "pointer_move", "select_combobox_option",
})


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        # ``asdict`` deep-copies every field and therefore fails for immutable
        # MappingProxyType policy maps.  Walk fields without mutating/copying
        # host-owned values instead.
        return {
            item.name: _canonical(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON mappings require string keys")
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        )
    if isinstance(value, str):
        # Canonical receipt/policy hashing uses Unicode NFC.  This removes the
        # composed/decomposed duplicate representation without changing the
        # caller-visible text or making a Unicode security assertion.
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON rejects non-finite floats")
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("canonical JSON does not accept bytes-like values")
    if value is None or isinstance(value, (bool, int)):
        return value
    raise TypeError(f"canonical JSON does not support {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Stable JSON bytes used for public governance fingerprints."""
    return json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def policy_hash(policy: "AuthorityEnvelope") -> str:
    return hashlib.sha256(canonical_json_bytes(policy.to_dict())).hexdigest()


def _origin(value: str) -> str:
    """Return browser-origin semantics for supported network schemes.

    Authorities are deliberately scoped to http(s).  Opaque/special schemes
    (``data:``, ``blob:``, ``javascript:``, ``about:``, ``file:``) cannot be
    safely represented by an origin allow-list and are rejected by governed
    navigation/frame authorization instead of falling through string checks.
    """
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return ""
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port
    except (TypeError, ValueError, UnicodeError):
        return ""
    default = 80 if scheme == "http" else 443
    suffix = "" if port is None or port == default else f":{port}"
    # IPv6 literal origins retain browser-style brackets.
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{scheme}://{host}{suffix}"


def _policy_origin_pattern(value: str) -> str:
    """Validate and canonicalize an exact or leftmost-label wildcard origin."""
    if not isinstance(value, str) or not value or value != value.strip():
        return ""
    if "*." not in value:
        return _origin(value) if value.rstrip("/") == value else ""
    if value.count("*.") != 1:
        return ""
    prefix, suffix = value.split("*.", 1)
    if prefix not in {"http://", "https://"} or not suffix or any(mark in suffix for mark in "/?#@"):
        return ""
    normalized = _origin(prefix + "host." + suffix)
    if not normalized:
        return ""
    scheme, host_port = normalized.split("://", 1)
    if host_port.startswith("["):
        return ""  # wildcard IP literals are meaningless and unsafe.
    return f"{scheme}://*.{host_port}"


def _matches_origin(origin: str, patterns: tuple[str, ...]) -> bool:
    """Exact origins, or a host-declared ``https://*.example.test`` suffix."""
    for pattern in patterns:
        candidate = _policy_origin_pattern(pattern)
        if not candidate:
            continue
        if candidate == origin:
            return True
        if candidate.startswith("http://*.") or candidate.startswith("https://*."):
            scheme, suffix = candidate.split("*.", 1)
            origin_host = origin[len(scheme):] if origin.startswith(scheme) else ""
            if origin_host.endswith("." + suffix) and origin_host != suffix:
                return True
    return False


@dataclass(frozen=True)
class AuthorityEnvelope:
    """Immutable, host-installed limits for one execution session.

    Empty allow-lists mean the corresponding dimension is not restricted.  A
    non-empty allow-list is exact and fail-closed.  ``granted_authorities`` is
    deliberately part of this host object rather than of an operation.
    """

    policy_id: str
    granted_authorities: tuple[ProvenanceClass, ...] = (
        ProvenanceClass.HOST_POLICY,
        ProvenanceClass.AGENT_REASONING,
    )
    allowed_origins: tuple[str, ...] = ()
    denied_origins: tuple[str, ...] = ()
    allowed_action_types: tuple[str, ...] = ()
    denied_action_types: tuple[str, ...] = ()
    allowed_file_names: tuple[str, ...] = ()
    allowed_secret_references: tuple[str, ...] = ()
    max_upload_bytes: int | None = None
    irreversible_action_types: tuple[str, ...] = ()
    require_preparation_for: tuple[str, ...] = ()
    required_authority_by_action: Mapping[str, ProvenanceClass] = field(default_factory=dict)
    expires_at_ms: int | None = None
    max_action_count: int | None = None
    max_side_effect_count: int | None = None
    deny_untrusted_for_irreversible: bool = False
    transfer_prepared_operations: bool = False
    # Frames are a distinct origin boundary.  They remain deny-by-default for
    # governed sessions until a host consciously opts in.
    allow_frame_actions: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "granted_authorities", tuple(self.granted_authorities))
        for name in (
            "allowed_origins", "denied_origins", "allowed_action_types",
            "denied_action_types", "allowed_file_names", "allowed_secret_references",
            "irreversible_action_types", "require_preparation_for",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        for name in ("allowed_origins", "denied_origins"):
            values = tuple(_policy_origin_pattern(value.rstrip("/")) for value in getattr(self, name))
            object.__setattr__(self, name, values)
        object.__setattr__(self, "required_authority_by_action", MappingProxyType(dict(self.required_authority_by_action)))
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("authority policy_id is required")
        if not self.granted_authorities:
            raise ValueError("authority envelope requires at least one granted authority")
        if any(not isinstance(value, ProvenanceClass) for value in self.granted_authorities):
            raise ValueError("granted_authorities must contain ProvenanceClass values")
        if len(self.granted_authorities) != len(set(self.granted_authorities)):
            raise ValueError("granted_authorities must not contain duplicates")
        for values_name in ("allowed_origins", "denied_origins"):
            if len(getattr(self, values_name)) != len(set(getattr(self, values_name))):
                raise ValueError(f"{values_name} must not contain duplicates")
            for value in getattr(self, values_name):
                if not _policy_origin_pattern(value):
                    raise ValueError(f"{values_name} contains an invalid origin")
        for values_name in (
            "allowed_action_types", "denied_action_types", "allowed_file_names",
            "allowed_secret_references", "irreversible_action_types", "require_preparation_for",
        ):
            if any(not isinstance(value, str) or not value for value in getattr(self, values_name)):
                raise ValueError(f"{values_name} must contain non-empty strings")
            if len(getattr(self, values_name)) != len(set(getattr(self, values_name))):
                raise ValueError(f"{values_name} must not contain duplicates")
        for values_name in (
            "allowed_action_types", "denied_action_types", "irreversible_action_types", "require_preparation_for",
        ):
            if any(value not in _KNOWN_ACTION_TYPES for value in getattr(self, values_name)):
                raise ValueError(f"{values_name} contains an unsupported action type")
        for action, authority in self.required_authority_by_action.items():
            if not isinstance(action, str) or action not in _KNOWN_ACTION_TYPES or not isinstance(authority, ProvenanceClass):
                raise ValueError("required_authority_by_action is invalid")
        for name in ("expires_at_ms", "max_action_count", "max_side_effect_count", "max_upload_bytes"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer when present")
        if (
            not isinstance(self.deny_untrusted_for_irreversible, bool)
            or not isinstance(self.transfer_prepared_operations, bool)
            or not isinstance(self.allow_frame_actions, bool)
        ):
            raise ValueError("authority boolean policy fields must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "granted_authorities": [value.value for value in self.granted_authorities],
            "allowed_origins": list(self.allowed_origins),
            "denied_origins": list(self.denied_origins),
            "allowed_action_types": list(self.allowed_action_types),
            "denied_action_types": list(self.denied_action_types),
            "allowed_file_names": list(self.allowed_file_names),
            "allowed_secret_references": list(self.allowed_secret_references),
            "max_upload_bytes": self.max_upload_bytes,
            "irreversible_action_types": list(self.irreversible_action_types),
            "require_preparation_for": list(self.require_preparation_for),
            "required_authority_by_action": {
                key: value.value for key, value in sorted(self.required_authority_by_action.items())
            },
            "expires_at_ms": self.expires_at_ms,
            "max_action_count": self.max_action_count,
            "max_side_effect_count": self.max_side_effect_count,
            "deny_untrusted_for_irreversible": self.deny_untrusted_for_irreversible,
            "transfer_prepared_operations": self.transfer_prepared_operations,
            "allow_frame_actions": self.allow_frame_actions,
        }

    @property
    def digest(self) -> str:
        return policy_hash(self)


@dataclass(frozen=True)
class FirewallDecision:
    outcome: FirewallOutcome
    policy_id: str
    policy_hash: str
    required_authority: ProvenanceClass | None
    available_authorities: tuple[ProvenanceClass, ...]
    rule_matched: str
    origin: str
    action_type: str
    reason: str | None = None
    input_provenance: tuple[ProvenanceClass, ...] = ()
    action_count: int = 0
    side_effect_count: int = 0

    @property
    def authorized(self) -> bool:
        return self.outcome is FirewallOutcome.AUTHORIZED

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "policy_id": self.policy_id,
            "policy_hash": self.policy_hash,
            "required_authority": self.required_authority.value if self.required_authority else None,
            "available_authorities": [value.value for value in self.available_authorities],
            "rule_matched": self.rule_matched,
            "origin": self.origin,
            "action_type": self.action_type,
            "reason": self.reason,
            "input_provenance": [value.value for value in self.input_provenance],
            "action_count": self.action_count,
            "side_effect_count": self.side_effect_count,
        }


class AuthorityFirewall:
    """Pure policy evaluator.  It never asks a planner to judge authorization."""

    def decide(
        self,
        operation: Any,
        envelope: AuthorityEnvelope,
        *,
        current_url: str | None = None,
        effective_url: str | None = None,
        now_ms: int,
        action_count: int = 0,
        side_effect_count: int = 0,
    ) -> FirewallDecision:
        action = operation.action
        action_type = action.type.value if isinstance(action.type, Enum) else str(action.type)
        # ``effective_url`` is only supplied after a navigation dispatch.  It
        # keeps an allowed redirect source from silently carrying a session
        # into a denied destination.  Pre-dispatch behavior remains based on
        # the declared navigation target/current page respectively.
        origin = _origin(effective_url or (operation.url if action_type == "navigate" else (current_url or operation.url)))
        provenance = tuple(getattr(operation, "provenance", ()) or ())
        provenance = tuple(value if isinstance(value, ProvenanceClass) else ProvenanceClass(value) for value in provenance)
        required = envelope.required_authority_by_action.get(action_type)
        irreversible = action_type in envelope.irreversible_action_types

        def result(outcome: FirewallOutcome, rule: str, reason: str | None = None) -> FirewallDecision:
            return FirewallDecision(
                outcome=outcome, policy_id=envelope.policy_id, policy_hash=envelope.digest,
                required_authority=required, available_authorities=envelope.granted_authorities,
                rule_matched=rule, origin=origin, action_type=action_type, reason=reason,
                input_provenance=provenance, action_count=action_count, side_effect_count=side_effect_count,
            )

        if envelope.expires_at_ms is not None and now_ms >= envelope.expires_at_ms:
            return result(FirewallOutcome.AUTHORITY_EXPIRED, "expires_at_ms", "authority envelope expired")
        # Operation provenance is planner-supplied context, not a capability.
        # A public proposal may report low-authority reasoning or untrusted
        # content, but cannot label itself as the user, host, secret provider,
        # or runtime in order to influence an authorization record.
        if any(value in {
            ProvenanceClass.USER_AUTHORITY,
            ProvenanceClass.HOST_POLICY,
            ProvenanceClass.SECRET_PROVIDER,
            ProvenanceClass.SYSTEM_RUNTIME,
        } for value in provenance):
            return result(
                FirewallOutcome.PROVENANCE_POLICY_REJECTED,
                "planner_provenance",
                "privileged provenance must be attached by a host execution boundary",
            )
        # A governed session has no safe policy representation for opaque
        # browser origins.  Reject before allow/deny matching so a `data:` or
        # `about:` navigation cannot exploit an empty or deny-only list.
        if not origin:
            return result(FirewallOutcome.ORIGIN_NOT_ALLOWED, "network_origin", "governed actions require an http(s) origin")
        if envelope.max_action_count is not None and action_count >= envelope.max_action_count:
            return result(FirewallOutcome.SIDE_EFFECT_BUDGET_EXCEEDED, "max_action_count", "action budget exhausted")
        if irreversible and envelope.max_side_effect_count is not None and side_effect_count >= envelope.max_side_effect_count:
            return result(FirewallOutcome.SIDE_EFFECT_BUDGET_EXCEEDED, "max_side_effect_count", "side-effect budget exhausted")
        if envelope.denied_origins and _matches_origin(origin, envelope.denied_origins):
            return result(FirewallOutcome.ORIGIN_NOT_ALLOWED, "denied_origins", "origin is denied")
        if envelope.allowed_origins and not _matches_origin(origin, envelope.allowed_origins):
            return result(FirewallOutcome.ORIGIN_NOT_ALLOWED, "allowed_origins", "origin is not allow-listed")
        if action_type in envelope.denied_action_types:
            return result(FirewallOutcome.ACTION_NOT_ALLOWED, "denied_action_types", "action type is denied")
        if envelope.allowed_action_types and action_type not in envelope.allowed_action_types:
            return result(FirewallOutcome.ACTION_NOT_ALLOWED, "allowed_action_types", "action type is not allow-listed")
        frame_targeted = getattr(action, "frame", None) is not None or getattr(action, "frame_path", ())
        if frame_targeted and not envelope.allow_frame_actions:
            return result(FirewallOutcome.POLICY_REJECTED, "frame_actions", "frame-targeted actions require explicit host authorization")
        if frame_targeted and not origin:
            return result(FirewallOutcome.POLICY_REJECTED, "frame_origin", "frame origin could not be resolved for authorization")
        if required is not None and required not in envelope.granted_authorities:
            return result(FirewallOutcome.AUTHORITY_INSUFFICIENT, "required_authority_by_action", "required authority was not granted")
        if envelope.deny_untrusted_for_irreversible and irreversible and any(
            value in {ProvenanceClass.WEB_UNTRUSTED, ProvenanceClass.THIRD_PARTY_CONTENT}
            for value in provenance
        ):
            return result(FirewallOutcome.PROVENANCE_POLICY_REJECTED, "deny_untrusted_for_irreversible", "untrusted provenance cannot authorize an irreversible action")
        secret = getattr(action, "secret_reference", None)
        if secret is not None and envelope.allowed_secret_references:
            reference = getattr(secret, "reference_id", str(secret))
            if reference not in envelope.allowed_secret_references:
                return result(FirewallOutcome.POLICY_REJECTED, "allowed_secret_references", "secret reference is not allow-listed")
        upload = getattr(action, "upload_authorization", None)
        if upload is not None:
            files = tuple(getattr(upload, "file_paths", ()) or ())
            names = tuple(Path(path).name for path in files)
            if envelope.allowed_file_names and any(name not in envelope.allowed_file_names for name in names):
                return result(FirewallOutcome.POLICY_REJECTED, "allowed_file_names", "upload file is not allow-listed")
            if envelope.max_upload_bytes is not None:
                total = 0
                try:
                    total = sum(Path(path).stat().st_size for path in files)
                except OSError:
                    return result(FirewallOutcome.POLICY_REJECTED, "max_upload_bytes", "upload size cannot be established")
                if total > envelope.max_upload_bytes:
                    return result(FirewallOutcome.POLICY_REJECTED, "max_upload_bytes", "upload exceeds declared size limit")
        return result(FirewallOutcome.AUTHORIZED, "envelope_authorized")
