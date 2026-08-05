from __future__ import annotations

from enum import Enum


class AuthenticationFailureKind(str, Enum):
    INVALID_PROFILE_NAME = "invalid_profile_name"
    PROFILE_NOT_FOUND = "profile_not_found"
    PROFILE_EXISTS = "profile_exists"
    PROFILE_IN_USE = "profile_in_use"
    PROFILE_CORRUPT = "profile_corrupt"
    SESSION_INVALID = "session_invalid"
    SESSION_IO_ERROR = "session_io_error"
    SECRET_NOT_FOUND = "secret_not_found"
    CALLBACK_FAILED = "authentication_callback_failed"
    NOT_READY = "browser_not_ready"


class AuthenticationError(RuntimeError):
    """Safe structured failure; messages must never contain secret values."""

    def __init__(self, message: str, *, kind: AuthenticationFailureKind, recovery: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.recovery = recovery

    def to_dict(self) -> dict[str, str]:
        result = {"error": self.kind.value, "message": str(self)}
        if self.recovery:
            result["recovery"] = self.recovery
        return result
