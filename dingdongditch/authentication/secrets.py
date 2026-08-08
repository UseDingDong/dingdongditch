"""Host-owned, execution-time secret-provider boundary.

The runtime deliberately has no secret store, configuration file, or vendor
integration.  It receives an opaque reference, asks a host-provided adapter
for an ephemeral value, uses it once, and clears its mutable buffer.
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import re
from threading import RLock
from typing import Any

from .errors import AuthenticationError, AuthenticationFailureKind

_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")


@dataclass(frozen=True)
class SecretReference:
    """An opaque host lookup key, not a secret value or a storage location."""

    reference_id: str

    def validate(self) -> None:
        if not isinstance(self.reference_id, str) or not _REFERENCE.fullmatch(self.reference_id):
            raise AuthenticationError(
                "secret reference is invalid",
                kind=AuthenticationFailureKind.SECRET_REFERENCE_INVALID,
            )

    def describe(self) -> dict[str, str]:
        return {"reference_id": self.reference_id}


class SecretValue:
    """Short-lived mutable secret buffer; repr/str never reveal contents."""

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("SecretValue requires a text value")
        self._buffer = bytearray(value.encode("utf-8"))

    def reveal(self) -> str:
        return self._buffer.decode("utf-8")

    def clear(self) -> None:
        for index in range(len(self._buffer)):
            self._buffer[index] = 0

    def __enter__(self) -> "SecretValue":
        return self

    def __exit__(self, *_: object) -> None:
        self.clear()

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True)
class SecretResolutionReceipt:
    reference: SecretReference
    status: str
    elapsed_ms: int
    failure_kind: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "reference": self.reference.describe(),
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "failure_kind": self.failure_kind,
        }


class SecretProvider:
    """Generic host adapter.

    New providers override :meth:`resolve`.  The legacy :meth:`get` hook is
    retained so existing host providers remain compatible.  Providers must
    return ``SecretValue``; raw strings are rejected rather than copied into
    runtime state without an explicit ephemeral wrapper.
    """

    def resolve(self, reference: SecretReference) -> SecretValue:
        return self.get(reference.reference_id)

    def get(self, name: str) -> SecretValue:
        raise NotImplementedError


class MappingSecretProvider(SecretProvider):
    """In-memory test/development provider; it never persists values."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self._lock = RLock()

    def get(self, name: str) -> SecretValue:
        with self._lock:
            try:
                value = self._values[name]
            except KeyError as exc:
                raise AuthenticationError(
                    "requested secret was not provided",
                    kind=AuthenticationFailureKind.SECRET_NOT_FOUND,
                    recovery="Provide it through the application SecretProvider.",
                ) from exc
        return SecretValue(value)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


def coerce_secret_reference(value: SecretReference | str) -> SecretReference:
    reference = value if isinstance(value, SecretReference) else SecretReference(value)
    reference.validate()
    return reference


def resolve_secret(
    provider: SecretProvider | None,
    reference: SecretReference | str,
    *,
    timeout_ms: int = 5_000,
) -> tuple[SecretValue, SecretResolutionReceipt]:
    """Resolve one secret under a hard wait bound without exposing its value."""
    ref = coerce_secret_reference(reference)
    if provider is None:
        raise AuthenticationError(
            "no application SecretProvider is configured",
            kind=AuthenticationFailureKind.SECRET_NOT_FOUND,
        )
    if (
        not isinstance(timeout_ms, int)
        or isinstance(timeout_ms, bool)
        or not 10 <= timeout_ms <= 60_000
    ):
        raise AuthenticationError(
            "secret provider timeout is outside the supported bound",
            kind=AuthenticationFailureKind.SECRET_REFERENCE_INVALID,
        )

    # Do not use the executor context manager: it waits for a provider that
    # ignored the deadline.  The current execution remains bounded while the
    # host owns the lifecycle of any still-running provider work.
    import time

    started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ddd-secret")
    future = executor.submit(provider.resolve, ref)
    try:
        resolved = future.result(timeout=timeout_ms / 1000)
    except FutureTimeout as exc:
        future.cancel()
        raise AuthenticationError(
            "secret provider did not resolve before its deadline",
            kind=AuthenticationFailureKind.SECRET_PROVIDER_TIMEOUT,
            recovery="Check the host provider and use a bounded response path.",
        ) from exc
    except AuthenticationError as exc:
        # A host adapter's message is untrusted text and may accidentally
        # include a resolved value.  Preserve only the structured category.
        if exc.kind is AuthenticationFailureKind.SECRET_NOT_FOUND:
            raise AuthenticationError(
                "requested secret was not provided",
                kind=AuthenticationFailureKind.SECRET_NOT_FOUND,
                recovery=exc.recovery,
            ) from exc
        raise AuthenticationError(
            "secret provider failed",
            kind=(
                exc.kind
                if exc.kind in {
                    AuthenticationFailureKind.SECRET_PROVIDER_TIMEOUT,
                    AuthenticationFailureKind.SECRET_REFERENCE_INVALID,
                    AuthenticationFailureKind.SECRET_VALUE_INVALID,
                }
                else AuthenticationFailureKind.SECRET_PROVIDER_FAILED
            ),
            recovery="Check the host SecretProvider implementation.",
        ) from exc
    except Exception as exc:
        raise AuthenticationError(
            "secret provider failed",
            kind=AuthenticationFailureKind.SECRET_PROVIDER_FAILED,
            recovery="Check the host SecretProvider implementation.",
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if not isinstance(resolved, SecretValue):
        raise AuthenticationError(
            "secret provider returned an invalid value wrapper",
            kind=AuthenticationFailureKind.SECRET_VALUE_INVALID,
        )
    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    return resolved, SecretResolutionReceipt(ref, "resolved", elapsed_ms)


def redact(value: Any, secrets: Mapping[str, str] | None = None) -> Any:
    """Recursively redact sensitive keys and explicitly registered literals."""
    literals = tuple(v for v in (secrets or {}).values() if v)
    sensitive = (
        "secret", "password", "token", "otp", "totp", "authorization",
        "credential", "cookie", "session", "api_key", "apikey", "private",
    )
    if isinstance(value, str):
        result = value
        for literal in literals:
            result = result.replace(literal, "<redacted>")
        return result
    if isinstance(value, Mapping):
        return {
            key: "<redacted>"
            if any(term in str(key).lower() for term in sensitive)
            else redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, secrets) for item in value)
    return value
