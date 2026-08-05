from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any

from .errors import AuthenticationError, AuthenticationFailureKind


class SecretProvider(ABC):
    @abstractmethod
    def get(self, name: str) -> "SecretValue": ...


class SecretValue:
    """Short-lived mutable secret buffer; repr/str never reveal its contents."""
    def __init__(self, value: str) -> None:
        self._buffer = bytearray(value.encode("utf-8"))

    def reveal(self) -> str:
        return self._buffer.decode("utf-8")

    def clear(self) -> None:
        for index in range(len(self._buffer)):
            self._buffer[index] = 0

    def __enter__(self) -> "SecretValue": return self
    def __exit__(self, *_: object) -> None: self.clear()
    def __repr__(self) -> str: return "SecretValue(<redacted>)"
    __str__ = __repr__


class MappingSecretProvider(SecretProvider):
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self._lock = RLock()

    def get(self, name: str) -> SecretValue:
        with self._lock:
            try:
                value = self._values[name]
            except KeyError as exc:
                raise AuthenticationError(f"secret '{name}' was not provided", kind=AuthenticationFailureKind.SECRET_NOT_FOUND, recovery="Provide it through the application SecretProvider.") from exc
        return SecretValue(value)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


def redact(value: Any, secrets: Mapping[str, str] | None = None) -> Any:
    """Recursively redact sensitive keys and registered literal values."""
    literals = tuple(v for v in (secrets or {}).values() if v)
    sensitive = ("secret", "password", "token", "otp", "totp", "authorization")
    if isinstance(value, str):
        result = value
        for literal in literals:
            result = result.replace(literal, "<redacted>")
        return result
    if isinstance(value, Mapping):
        return {k: "<redacted>" if any(term in str(k).lower() for term in sensitive) else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list): return [redact(v, secrets) for v in value]
    if isinstance(value, tuple): return tuple(redact(v, secrets) for v in value)
    return value
