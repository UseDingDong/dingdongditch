from __future__ import annotations

from dingdongditch import (
    Action,
    ActionType,
    AuthenticationCapability,
    CallbackWebAuthnTransport,
    Expectation,
    ExpectationType,
    Locator,
    LocatorStrategy,
    Operation,
    Verdict,
    WebAuthnParticipationRequest,
    WebAuthnParticipationStatus,
    WebAuthnTransportResult,
    execute_operation,
)


def _operation(url, *, request_id="auth-transport", expectations=True):
    return Operation(
        operation_id=request_id,
        url=url,
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
        ),
        expectations=(
            [Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="state-indicator"),
                attribute_name="data-state",
                attribute_value="active",
            )]
            if expectations else []
        ),
        webauthn=WebAuthnParticipationRequest(request_id),
    )


def test_host_webauthn_completion_requires_independent_browser_verification(fixture_url):
    auth = AuthenticationCapability(
        webauthn_transport=CallbackWebAuthnTransport(
            lambda event: WebAuthnTransportResult(WebAuthnParticipationStatus.COMPLETED)
        )
    )
    receipt = execute_operation(_operation(fixture_url), authentication=auth)
    assert receipt.verdict is Verdict.VERIFIED
    assert receipt.to_core_dict()["webauthn_participation"]["status"] == "completed"

    no_proof = execute_operation(
        _operation(fixture_url, request_id="auth-no-proof", expectations=False),
        authentication=AuthenticationCapability(
            webauthn_transport=CallbackWebAuthnTransport(
                lambda event: WebAuthnTransportResult(WebAuthnParticipationStatus.COMPLETED)
            )
        ),
    )
    assert no_proof.verdict is Verdict.INDETERMINATE


def test_webauthn_host_rejection_and_absent_transport_do_not_fake_success(fixture_url):
    rejected = execute_operation(
        _operation(fixture_url, request_id="auth-reject"),
        authentication=AuthenticationCapability(
            webauthn_transport=CallbackWebAuthnTransport(
                lambda event: WebAuthnTransportResult(WebAuthnParticipationStatus.REJECTED)
            )
        ),
    )
    assert rejected.verdict is Verdict.NOT_VERIFIED
    assert rejected.failure_kind == "webauthn_host_rejected"

    unsupported = execute_operation(_operation(fixture_url, request_id="auth-none"))
    assert unsupported.verdict is Verdict.INDETERMINATE
    assert unsupported.failure_kind == "webauthn_unsupported"
