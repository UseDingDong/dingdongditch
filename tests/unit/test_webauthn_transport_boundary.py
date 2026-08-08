from __future__ import annotations

import time

from dingdongditch.authentication import (
    CallbackWebAuthnTransport,
    WebAuthnParticipationRequest,
    WebAuthnParticipationStatus,
    WebAuthnTransportResult,
)
from dingdongditch.authentication.webauthn import execute_webauthn_transport


def _request():
    return WebAuthnParticipationRequest("host-auth-1", timeout_ms=100)


def test_host_transport_completion_is_bounded_metadata_only():
    receipt = execute_webauthn_transport(
        CallbackWebAuthnTransport(
            lambda event: WebAuthnTransportResult(WebAuthnParticipationStatus.COMPLETED)
        ),
        _request(),
        browser_engine="chromium",
        page_origin="https://fixture.test",
    )
    assert receipt.status is WebAuthnParticipationStatus.COMPLETED
    serialized = receipt.to_dict()
    assert serialized["runtime_native_authenticator_control"] == "unsupported"
    assert "private" not in str(serialized).lower()


def test_host_rejection_timeout_and_missing_transport_are_explicit():
    rejected = execute_webauthn_transport(
        CallbackWebAuthnTransport(
            lambda event: WebAuthnTransportResult(
                WebAuthnParticipationStatus.REJECTED, "user_declined"
            )
        ),
        _request(), browser_engine="firefox", page_origin=None,
    )
    assert rejected.status is WebAuthnParticipationStatus.REJECTED

    timed_out = execute_webauthn_transport(
        CallbackWebAuthnTransport(
            lambda event: (time.sleep(0.2), WebAuthnTransportResult(WebAuthnParticipationStatus.COMPLETED))[1]
        ),
        _request(), browser_engine="webkit", page_origin=None,
    )
    assert timed_out.status is WebAuthnParticipationStatus.TIMED_OUT

    unsupported = execute_webauthn_transport(
        None, _request(), browser_engine="webkit", page_origin=None
    )
    assert unsupported.status is WebAuthnParticipationStatus.UNSUPPORTED
