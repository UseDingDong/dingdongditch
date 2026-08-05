from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .errors import AuthenticationError, AuthenticationFailureKind


class AuthEventType(str, Enum):
    AUTHENTICATION_REQUIRED = "authentication_required"
    OTP_REQUESTED = "otp_requested"
    TOTP_REQUESTED = "totp_requested"
    PASSKEY_REQUESTED = "passkey_requested"
    WEBAUTHN_REQUESTED = "webauthn_requested"


@dataclass(frozen=True)
class AuthEvent:
    event_type: AuthEventType
    details: dict[str, Any] = field(default_factory=dict)


AuthCallback = Callable[[AuthEvent], object]


class AuthenticationCallbacks:
    def __init__(self) -> None:
        self._callbacks: dict[AuthEventType, list[AuthCallback]] = {}

    def register(self, event_type: AuthEventType, callback: AuthCallback) -> None:
        self._callbacks.setdefault(event_type, []).append(callback)

    def emit(self, event: AuthEvent) -> list[object]:
        results = []
        for callback in tuple(self._callbacks.get(event.event_type, ())):
            try:
                results.append(callback(event))
            except Exception as exc:
                raise AuthenticationError(f"callback for {event.event_type.value} failed ({type(exc).__name__})", kind=AuthenticationFailureKind.CALLBACK_FAILED, recovery="Fix or unregister the application callback.") from exc
        return results
