"""Versioned, deliberately narrow portable browser-state contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import time
from typing import Any
from urllib.parse import urlsplit

from .errors import AuthenticationError, AuthenticationFailureKind

PORTABLE_STATE_SCHEMA_VERSION = 2
PORTABLE_STATE_KIND = "dingdongditch_portable_browser_state"
MAX_PORTABLE_STATE_BYTES = 10 * 1024 * 1024
DEFAULT_PORTABLE_STATE_MAX_AGE_MS = 24 * 60 * 60 * 1000

_SENSITIVE_STORAGE_KEY = re.compile(
    r"(?:secret|password|passwd|token|authorization|credential|api[_-]?key|"
    r"session|private|otp|totp)", re.I
)
_TOKENISH_VALUE = re.compile(
    r"(?:^bearer\s+|^eyJ[A-Za-z0-9_-]{12,}|^sk-[A-Za-z0-9_-]{12,})", re.I
)


class PortableStateFeature(str, Enum):
    COOKIES = "cookies"
    LOCAL_STORAGE = "local_storage"
    INDEXED_DB = "indexed_db"


@dataclass(frozen=True)
class PortableStatePolicy:
    """Explicit selection of browser state; no profile internals are included."""

    include_cookies: bool = True
    include_local_storage: bool = True
    include_indexed_db: bool = False

    def validate(self) -> None:
        for name, value in (
            ("include_cookies", self.include_cookies),
            ("include_local_storage", self.include_local_storage),
            ("include_indexed_db", self.include_indexed_db),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a bool")
        if not (self.include_cookies or self.include_local_storage or self.include_indexed_db):
            raise ValueError("portable state policy must include at least one feature")


@dataclass(frozen=True)
class PortableStateReceipt:
    schema_version: int
    direction: str
    status: str
    included_features: tuple[str, ...]
    excluded_features: tuple[str, ...]
    cookie_count: int
    origin_count: int
    sensitive_local_storage_entries_excluded: int = 0
    state_age_ms: int | None = None
    failure_kind: str | None = None
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "direction": self.direction,
            "status": self.status,
            "included_features": list(self.included_features),
            "excluded_features": list(self.excluded_features),
            "cookie_count": self.cookie_count,
            "origin_count": self.origin_count,
            "sensitive_local_storage_entries_excluded": (
                self.sensitive_local_storage_entries_excluded
            ),
            "state_age_ms": self.state_age_ms,
            "failure_kind": self.failure_kind,
            "limitations": list(self.limitations),
        }


def _safe_origin(value: object) -> str:
    if not isinstance(value, str):
        raise AuthenticationError("session file contains a non-string origin", kind=AuthenticationFailureKind.SESSION_INVALID)
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise AuthenticationError("session file contains a malformed origin", kind=AuthenticationFailureKind.SESSION_INVALID) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise AuthenticationError("session file contains an unsafe storage origin", kind=AuthenticationFailureKind.SESSION_INVALID)
    return f"{parsed.scheme}://{parsed.netloc}"


def _validate_storage_state(
    state: object,
    *,
    allow_indexed_db: bool,
    reject_sensitive_local_storage: bool = False,
) -> dict[str, Any]:
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
        raise AuthenticationError("session file must contain cookies and origins arrays", kind=AuthenticationFailureKind.SESSION_INVALID)
    if len(state["cookies"]) > 1024 or len(state["origins"]) > 256:
        raise AuthenticationError("session file exceeds portable state entry limits", kind=AuthenticationFailureKind.SESSION_INVALID)
    cookies: list[dict[str, Any]] = []
    for cookie in state["cookies"]:
        if not isinstance(cookie, dict) or not all(isinstance(cookie.get(key), str) for key in ("name", "value", "domain", "path")):
            raise AuthenticationError("session file contains an invalid cookie", kind=AuthenticationFailureKind.SESSION_INVALID)
        if len(cookie["name"]) > 512 or len(cookie["value"]) > 16_384 or not cookie["domain"] or not cookie["path"].startswith("/"):
            raise AuthenticationError("session file contains an unsafe cookie", kind=AuthenticationFailureKind.SESSION_INVALID)
        cookies.append(dict(cookie))
    origins: list[dict[str, Any]] = []
    seen_origins: set[str] = set()
    for origin in state["origins"]:
        if not isinstance(origin, dict) or not isinstance(origin.get("localStorage"), list):
            raise AuthenticationError("session file contains invalid origin storage", kind=AuthenticationFailureKind.SESSION_INVALID)
        canonical_origin = _safe_origin(origin.get("origin"))
        if canonical_origin in seen_origins:
            raise AuthenticationError("session file contains duplicate storage origins", kind=AuthenticationFailureKind.SESSION_INVALID)
        seen_origins.add(canonical_origin)
        entries: list[dict[str, str]] = []
        if len(origin["localStorage"]) > 1024:
            raise AuthenticationError("session file local storage exceeds entry limits", kind=AuthenticationFailureKind.SESSION_INVALID)
        for item in origin["localStorage"]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("value"), str):
                raise AuthenticationError("session file contains invalid local storage entries", kind=AuthenticationFailureKind.SESSION_INVALID)
            if len(item["name"]) > 2048 or len(item["value"]) > 65_536:
                raise AuthenticationError("session file contains oversized local storage", kind=AuthenticationFailureKind.SESSION_INVALID)
            if reject_sensitive_local_storage and (
                _SENSITIVE_STORAGE_KEY.search(item["name"])
                or _TOKENISH_VALUE.search(item["value"])
            ):
                raise AuthenticationError(
                    "session file contains excluded sensitive local storage",
                    kind=AuthenticationFailureKind.SESSION_INVALID,
                )
            entries.append({"name": item["name"], "value": item["value"]})
        portable_origin: dict[str, Any] = {"origin": canonical_origin, "localStorage": entries}
        indexed_db = origin.get("indexedDB")
        if indexed_db is not None:
            if not allow_indexed_db:
                raise AuthenticationError(
                    "session state requests unsupported IndexedDB import",
                    kind=AuthenticationFailureKind.SESSION_UNSUPPORTED,
                )
            if not isinstance(indexed_db, list) or len(indexed_db) > 64 or any(
                not isinstance(item, dict) or not isinstance(item.get("name"), str)
                for item in indexed_db
            ):
                raise AuthenticationError("session file contains invalid IndexedDB state", kind=AuthenticationFailureKind.SESSION_INVALID)
            # Playwright's documented storage-state representation is passed
            # through only during new-context construction, never evaluated as
            # arbitrary browser JavaScript by DingDongDitch.
            portable_origin["indexedDB"] = indexed_db
        origins.append(portable_origin)
    return {"cookies": cookies, "origins": origins}


def _features_for_policy(policy: PortableStatePolicy) -> tuple[str, ...]:
    values: list[str] = []
    if policy.include_cookies:
        values.append(PortableStateFeature.COOKIES.value)
    if policy.include_local_storage:
        values.append(PortableStateFeature.LOCAL_STORAGE.value)
    if policy.include_indexed_db:
        values.append(PortableStateFeature.INDEXED_DB.value)
    return tuple(values)


def build_portable_state(
    raw_state: object,
    *,
    policy: PortableStatePolicy,
    created_at_epoch_ms: int | None = None,
) -> tuple[dict[str, Any], PortableStateReceipt]:
    policy.validate()
    # Validate raw browser output before filtering so malformed backend output
    # is never serialized as a seemingly valid portable-state file.
    raw = _validate_storage_state(raw_state, allow_indexed_db=policy.include_indexed_db)
    excluded: list[str] = []
    if not policy.include_cookies:
        excluded.append(PortableStateFeature.COOKIES.value)
    if not policy.include_local_storage:
        excluded.append(PortableStateFeature.LOCAL_STORAGE.value)
    if not policy.include_indexed_db:
        excluded.append(PortableStateFeature.INDEXED_DB.value)

    sensitive_excluded = 0
    origins: list[dict[str, Any]] = []
    for origin in raw["origins"]:
        output: dict[str, Any] = {"origin": origin["origin"], "localStorage": []}
        if policy.include_local_storage:
            for item in origin["localStorage"]:
                if _SENSITIVE_STORAGE_KEY.search(item["name"]) or _TOKENISH_VALUE.search(item["value"]):
                    sensitive_excluded += 1
                    continue
                output["localStorage"].append(item)
        if policy.include_indexed_db and "indexedDB" in origin:
            output["indexedDB"] = origin["indexedDB"]
        origins.append(output)

    state = {
        "cookies": raw["cookies"] if policy.include_cookies else [],
        "origins": origins,
    }
    created = int(time.time() * 1000) if created_at_epoch_ms is None else created_at_epoch_ms
    document = {
        "schema_version": PORTABLE_STATE_SCHEMA_VERSION,
        "kind": PORTABLE_STATE_KIND,
        "created_at_epoch_ms": created,
        "portable_features": list(_features_for_policy(policy)),
        "storage_state": state,
    }
    receipt = PortableStateReceipt(
        schema_version=PORTABLE_STATE_SCHEMA_VERSION,
        direction="export",
        status="completed",
        included_features=tuple(document["portable_features"]),
        excluded_features=tuple(excluded),
        cookie_count=len(state["cookies"]),
        origin_count=len(state["origins"]),
        sensitive_local_storage_entries_excluded=sensitive_excluded,
        limitations=(
            "no_session_storage",
            "no_password_manager_or_credential_vault",
            "no_browser_profile_internals",
            "no_service_worker_cache_or_extension_state",
        ),
    )
    return document, receipt


def validate_portable_document(
    raw: object,
    *,
    max_age_ms: int = DEFAULT_PORTABLE_STATE_MAX_AGE_MS,
    allow_indexed_db: bool = False,
) -> tuple[dict[str, Any], PortableStateReceipt]:
    """Validate fully before any context mutation and return import state."""
    if not isinstance(max_age_ms, int) or isinstance(max_age_ms, bool) or not 1 <= max_age_ms <= 30 * 24 * 60 * 60 * 1000:
        raise AuthenticationError("portable state max age is invalid", kind=AuthenticationFailureKind.SESSION_INVALID)
    if not isinstance(raw, dict):
        raise AuthenticationError("session file must be an object", kind=AuthenticationFailureKind.SESSION_INVALID)
    if raw.get("schema_version") != PORTABLE_STATE_SCHEMA_VERSION or raw.get("kind") != PORTABLE_STATE_KIND:
        raise AuthenticationError("session file has an unsupported schema", kind=AuthenticationFailureKind.SESSION_INVALID)
    created = raw.get("created_at_epoch_ms")
    if not isinstance(created, int) or isinstance(created, bool):
        raise AuthenticationError("session file is missing a creation timestamp", kind=AuthenticationFailureKind.SESSION_INVALID)
    age = int(time.time() * 1000) - created
    if age < 0 or age > max_age_ms:
        raise AuthenticationError("portable session state is stale or clock-ambiguous", kind=AuthenticationFailureKind.SESSION_STALE)
    features_raw = raw.get("portable_features")
    if not isinstance(features_raw, list) or any(item not in {feature.value for feature in PortableStateFeature} for item in features_raw) or len(features_raw) != len(set(features_raw)):
        raise AuthenticationError("session file has ambiguous portable features", kind=AuthenticationFailureKind.SESSION_INVALID)
    state = _validate_storage_state(
        raw.get("storage_state"),
        allow_indexed_db=allow_indexed_db,
        reject_sensitive_local_storage=True,
    )
    has_indexed_db = any("indexedDB" in origin for origin in state["origins"])
    if has_indexed_db and PortableStateFeature.INDEXED_DB.value not in features_raw:
        raise AuthenticationError("session file IndexedDB feature declaration is ambiguous", kind=AuthenticationFailureKind.SESSION_INVALID)
    if has_indexed_db and not allow_indexed_db:
        raise AuthenticationError("IndexedDB import requires a new browser context", kind=AuthenticationFailureKind.SESSION_UNSUPPORTED)
    included = tuple(features_raw)
    receipt = PortableStateReceipt(
        schema_version=PORTABLE_STATE_SCHEMA_VERSION,
        direction="import",
        status="completed",
        included_features=included,
        excluded_features=tuple(
            feature.value for feature in PortableStateFeature if feature.value not in included
        ),
        cookie_count=len(state["cookies"]),
        origin_count=len(state["origins"]),
        state_age_ms=max(0, age),
        limitations=(
            "no_session_storage",
            "no_password_manager_or_credential_vault",
            "no_browser_profile_internals",
            "no_service_worker_cache_or_extension_state",
        ),
    )
    return state, receipt
