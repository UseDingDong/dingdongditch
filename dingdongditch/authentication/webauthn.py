"""Safe host-participation boundary for passkey/WebAuthn workflows.

This module does not implement a virtual authenticator, extract credentials,
or send challenges/assertions.  Browser/native authenticator behavior remains
outside DingDongDitch.  A host may only report bounded participation through a
typed callback after an operation explicitly requests it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from enum import Enum
import re
import time
from typing import Any, Callable


_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


class WebAuthnParticipationStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    COMPLETED = "completed"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"
    TIMED_OUT = "timed_out"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class WebAuthnParticipationRequest:
    """Explicit, metadata-only host participation request."""

    request_id: str
    timeout_ms: int = 30_000

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not _REQUEST_ID.fullmatch(self.request_id):
            raise ValueError("webauthn request_id must be an opaque 1-128 character ID")
        if (
            not isinstance(self.timeout_ms, int)
            or isinstance(self.timeout_ms, bool)
            or not 100 <= self.timeout_ms <= 60_000
        ):
            raise ValueError("webauthn timeout_ms must be between 100 and 60000")

    def describe(self) -> dict[str, object]:
        return {"request_id": self.request_id, "timeout_ms": self.timeout_ms}


@dataclass(frozen=True)
class WebAuthnTransportEvent:
    request: WebAuthnParticipationRequest
    browser_engine: str
    page_origin: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "request": self.request.describe(),
            "browser_engine": self.browser_engine,
            "page_origin": self.page_origin,
        }


@dataclass(frozen=True)
class WebAuthnTransportResult:
    status: WebAuthnParticipationStatus
    reason: str | None = None

    def validate(self) -> None:
        if self.status in {
            WebAuthnParticipationStatus.NOT_REQUESTED,
            WebAuthnParticipationStatus.TIMED_OUT,
        }:
            raise ValueError("transport cannot return not_requested or timed_out")
        if self.reason is not None and (
            not isinstance(self.reason, str) or len(self.reason) > 160
        ):
            raise ValueError("webauthn transport reason must be bounded text")


@dataclass(frozen=True)
class WebAuthnParticipationReceipt:
    request_id: str
    status: WebAuthnParticipationStatus
    elapsed_ms: int
    browser_engine: str
    reason: str | None = None
    runtime_native_authenticator_control: str = "unsupported"

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "elapsed_ms": self.elapsed_ms,
            "browser_engine": self.browser_engine,
            "reason": self.reason,
            "runtime_native_authenticator_control": self.runtime_native_authenticator_control,
        }


class WebAuthnTransport:
    """Host-controlled participation contract; no keys or credentials cross it."""

    def participate(self, event: WebAuthnTransportEvent) -> WebAuthnTransportResult:
        raise NotImplementedError


class CallbackWebAuthnTransport(WebAuthnTransport):
    """Thin convenience adapter for host applications."""

    def __init__(self, callback: Callable[[WebAuthnTransportEvent], WebAuthnTransportResult]) -> None:
        self._callback = callback

    def participate(self, event: WebAuthnTransportEvent) -> WebAuthnTransportResult:
        return self._callback(event)


def execute_webauthn_transport(
    transport: WebAuthnTransport | None,
    request: WebAuthnParticipationRequest,
    *,
    browser_engine: str,
    page_origin: str | None,
) -> WebAuthnParticipationReceipt:
    """Run a host callback under a bounded wait without claiming auth success."""
    request.validate()
    if transport is None:
        return WebAuthnParticipationReceipt(
            request_id=request.request_id,
            status=WebAuthnParticipationStatus.UNSUPPORTED,
            elapsed_ms=0,
            browser_engine=browser_engine,
            reason="host_transport_not_configured",
        )
    started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ddd-webauthn")
    future = executor.submit(
        transport.participate,
        WebAuthnTransportEvent(
            request=request, browser_engine=browser_engine, page_origin=page_origin
        ),
    )
    try:
        result = future.result(timeout=request.timeout_ms / 1000)
        if not isinstance(result, WebAuthnTransportResult):
            raise TypeError("transport returned an invalid result")
        result.validate()
        status = result.status
        reason = result.reason
    except FutureTimeout:
        future.cancel()
        status = WebAuthnParticipationStatus.TIMED_OUT
        reason = "host_transport_timeout"
    except Exception:
        status = WebAuthnParticipationStatus.INDETERMINATE
        reason = "host_transport_failure"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return WebAuthnParticipationReceipt(
        request_id=request.request_id,
        status=status,
        elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
        browser_engine=browser_engine,
        reason=reason,
    )
