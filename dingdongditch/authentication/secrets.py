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
import secrets
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


@dataclass(frozen=True)
class SecretBinding:
    """Provider-issued opaque binding for one immutable secret generation.

    ``generation_id`` is deliberately opaque.  It must not be a digest of a
    secret value (in particular not a password), and is retained only by the
    live host/session while a prepared transaction exists.  A provider must
    bind all semantics that affect resolution, including scope/tenant and
    implementation generation, into this value.
    """

    reference_id: str
    provider_id: str
    generation_id: str

    def validate(self) -> None:
        SecretReference(self.reference_id).validate()
        for name, value in (("provider_id", self.provider_id), ("generation_id", self.generation_id)):
            if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
                raise AuthenticationError(
                    "secret provider returned an invalid opaque binding",
                    kind=AuthenticationFailureKind.SECRET_BINDING_UNAVAILABLE,
                )


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

    def bind(self, reference: SecretReference) -> SecretBinding:
        """Bind a reference to a resolvable immutable provider generation.

        Generic ``get``/``resolve`` providers cannot safely implement this:
        they have no way to prove the value used later is the one reviewed at
        prepare time.  They therefore fail closed for prepared secret actions.
        Implementations must return an opaque, non-secret generation ID and
        make :meth:`resolve_bound` reject rotation, scope, or provider changes.
        """
        raise AuthenticationError(
            "secret provider does not support immutable generation binding",
            kind=AuthenticationFailureKind.SECRET_BINDING_UNAVAILABLE,
            recovery="Implement SecretProvider.bind and resolve_bound for prepared secret actions.",
        )

    def resolve_bound(self, reference: SecretReference, binding: SecretBinding) -> SecretValue:
        raise AuthenticationError(
            "secret provider does not support immutable generation binding",
            kind=AuthenticationFailureKind.SECRET_BINDING_UNAVAILABLE,
            recovery="Implement SecretProvider.bind and resolve_bound for prepared secret actions.",
        )

    def assert_bound(self, reference: SecretReference, binding: SecretBinding) -> None:
        """Check that a prepared binding remains resolvable without exposing text."""
        raise AuthenticationError(
            "secret provider does not support immutable generation binding",
            kind=AuthenticationFailureKind.SECRET_BINDING_UNAVAILABLE,
        )


class MappingSecretProvider(SecretProvider):
    """In-memory test/development provider; it never persists values."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self._provider_id = "mapping-" + secrets.token_urlsafe(18)
        self._generation = {name: 1 for name in self._values}
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

    def bind(self, reference: SecretReference) -> SecretBinding:
        reference.validate()
        with self._lock:
            if reference.reference_id not in self._values:
                raise AuthenticationError(
                    "requested secret was not provided",
                    kind=AuthenticationFailureKind.SECRET_NOT_FOUND,
                )
            generation = self._generation[reference.reference_id]
            # This is an opaque host-local generation label, not a hash of the
            # value.  ``MappingSecretProvider`` is only a test/development
            # implementation, but it exercises the same contract as an HSM or
            # vault provider.
            return SecretBinding(reference.reference_id, self._provider_id, f"g-{generation}")

    def resolve_bound(self, reference: SecretReference, binding: SecretBinding) -> SecretValue:
        self.assert_bound(reference, binding)
        with self._lock:
            return SecretValue(self._values[reference.reference_id])

    def assert_bound(self, reference: SecretReference, binding: SecretBinding) -> None:
        reference.validate()
        binding.validate()
        with self._lock:
            expected = self.bind(reference)
            if (
                binding.reference_id != reference.reference_id
                or binding.provider_id != expected.provider_id
                or binding.generation_id != expected.generation_id
            ):
                raise AuthenticationError(
                    "prepared secret generation is no longer available",
                    kind=AuthenticationFailureKind.SECRET_BINDING_CHANGED,
                    recovery="Prepare a new operation after the host secret rotation is complete.",
                )

    def replace(self, name: str, value: str) -> None:
        """Rotate a development/test value, invalidating existing bindings."""
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError("mapping secret rotations require string name and value")
        with self._lock:
            self._values[name] = value
            self._generation[name] = self._generation.get(name, 0) + 1

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


def bind_secret(
    provider: SecretProvider | None,
    reference: SecretReference | str,
) -> SecretBinding:
    """Ask a provider to bind a reference without resolving/persisting text."""
    ref = coerce_secret_reference(reference)
    if provider is None:
        raise AuthenticationError("no application SecretProvider is configured", kind=AuthenticationFailureKind.SECRET_NOT_FOUND)
    try:
        binding = provider.bind(ref)
    except AuthenticationError:
        raise
    except Exception as exc:
        raise AuthenticationError(
            "secret provider failed to bind a generation",
            kind=AuthenticationFailureKind.SECRET_PROVIDER_FAILED,
            recovery="Check the host SecretProvider implementation.",
        ) from exc
    if not isinstance(binding, SecretBinding):
        raise AuthenticationError("secret provider returned an invalid binding", kind=AuthenticationFailureKind.SECRET_BINDING_UNAVAILABLE)
    binding.validate()
    if binding.reference_id != ref.reference_id:
        raise AuthenticationError("secret provider binding does not match the requested reference", kind=AuthenticationFailureKind.SECRET_BINDING_CHANGED)
    return binding


def resolve_bound_secret(
    provider: SecretProvider | None,
    reference: SecretReference | str,
    binding: SecretBinding,
    *,
    timeout_ms: int = 5_000,
) -> tuple[SecretValue, SecretResolutionReceipt]:
    """Resolve exactly the provider generation previously bound at prepare."""
    ref = coerce_secret_reference(reference)
    if not isinstance(binding, SecretBinding):
        raise AuthenticationError("prepared secret binding is invalid", kind=AuthenticationFailureKind.SECRET_BINDING_CHANGED)
    binding.validate()
    if binding.reference_id != ref.reference_id:
        raise AuthenticationError("prepared secret binding does not match the reference", kind=AuthenticationFailureKind.SECRET_BINDING_CHANGED)
    if provider is None:
        raise AuthenticationError("no application SecretProvider is configured", kind=AuthenticationFailureKind.SECRET_NOT_FOUND)
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 10 <= timeout_ms <= 60_000:
        raise AuthenticationError("secret provider timeout is outside the supported bound", kind=AuthenticationFailureKind.SECRET_REFERENCE_INVALID)

    import time

    started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ddd-secret")
    future = executor.submit(provider.resolve_bound, ref, binding)
    try:
        resolved = future.result(timeout=timeout_ms / 1000)
    except FutureTimeout as exc:
        future.cancel()
        raise AuthenticationError("secret provider did not resolve before its deadline", kind=AuthenticationFailureKind.SECRET_PROVIDER_TIMEOUT) from exc
    except AuthenticationError as exc:
        # Preserve only stable, non-secret categories; adapter messages are
        # untrusted and must never enter browser receipts.
        kind = exc.kind if exc.kind in {
            AuthenticationFailureKind.SECRET_BINDING_CHANGED,
            AuthenticationFailureKind.SECRET_BINDING_UNAVAILABLE,
            AuthenticationFailureKind.SECRET_NOT_FOUND,
            AuthenticationFailureKind.SECRET_PROVIDER_TIMEOUT,
            AuthenticationFailureKind.SECRET_VALUE_INVALID,
        } else AuthenticationFailureKind.SECRET_PROVIDER_FAILED
        raise AuthenticationError("prepared secret resolution failed", kind=kind, recovery="Prepare a new operation or check the host SecretProvider.") from exc
    except Exception as exc:
        raise AuthenticationError("prepared secret resolution failed", kind=AuthenticationFailureKind.SECRET_PROVIDER_FAILED) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if not isinstance(resolved, SecretValue):
        raise AuthenticationError("secret provider returned an invalid value wrapper", kind=AuthenticationFailureKind.SECRET_VALUE_INVALID)
    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    return resolved, SecretResolutionReceipt(ref, "resolved_bound", elapsed_ms)


def assert_secret_binding(
    provider: SecretProvider | None,
    reference: SecretReference | str,
    binding: SecretBinding,
) -> None:
    """Fail closed before commit if a provider generation has changed."""
    ref = coerce_secret_reference(reference)
    if provider is None:
        raise AuthenticationError("no application SecretProvider is configured", kind=AuthenticationFailureKind.SECRET_NOT_FOUND)
    if not isinstance(binding, SecretBinding):
        raise AuthenticationError("prepared secret binding is invalid", kind=AuthenticationFailureKind.SECRET_BINDING_CHANGED)
    binding.validate()
    try:
        provider.assert_bound(ref, binding)
    except AuthenticationError:
        raise
    except Exception as exc:
        raise AuthenticationError("prepared secret binding check failed", kind=AuthenticationFailureKind.SECRET_PROVIDER_FAILED) from exc


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
