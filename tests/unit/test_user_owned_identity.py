from __future__ import annotations

from dataclasses import replace
import time
from unittest.mock import MagicMock, patch

import pytest

from dingdongditch import (
    Action,
    ActionType,
    AgentIdentity,
    AuthorityEnvelope,
    ExecutionPlan,
    IdentityError,
    IdentityRegistry,
    IdentitySigner,
    IdentityStatus,
    Operation,
    ProvenanceClass,
    StatefulSessionError,
    StatefulSessionRuntime,
    TrustedPlanSigner,
    TrustedPlanVerifier,
    identity_reference,
    parse_identity_assertion,
)
from dingdongditch.machine_contract import PlanDocument


def _policy(*, actions: tuple[str, ...] = ("navigate",)) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        policy_id="identity-policy", allowed_origins=("https://example.test",),
        allowed_action_types=actions,
        granted_authorities=(ProvenanceClass.HOST_POLICY, ProvenanceClass.AGENT_REASONING),
    )


def _operation() -> Operation:
    return Operation("op", "https://example.test/", Action(ActionType.NAVIGATE), provenance=(ProvenanceClass.AGENT_REASONING,))


def _identity(*, controller_scope: str | None = None):
    signer = IdentitySigner.generate(identity_id="user-owned-agent-x", owner_id="user-1", issuer_id="host-1")
    registry = IdentityRegistry()
    registry.register(signer.identity)
    now = int(time.time() * 1000)
    return signer, registry, signer.assert_identity(issued_at_ms=now - 10, expires_at_ms=now + 60_000, controller_scope=controller_scope)


def _backend() -> MagicMock:
    backend = MagicMock()
    backend.is_started = True
    backend.page.url = "https://example.test/"
    backend.page_id = "page-1"
    backend.backend_identity = "test"
    backend.browser_identity = "test"
    backend.browser_environment.return_value = {"page_id": "page-1"}
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True}]
    backend.list_dialog_history.return_value = []
    return backend


def test_identity_is_vendor_neutral_public_and_private_key_never_serializes():
    signer, registry, assertion = _identity()
    identity = signer.identity
    assert "model" not in str(identity.to_dict()).lower()
    assert registry.verify(assertion).identity_id == "user-owned-agent-x"
    assert parse_identity_assertion(assertion.to_dict()) == assertion
    assert "private" not in str(identity.to_dict()).lower()
    assert "private" not in str(assertion.to_dict()).lower()
    with pytest.raises(Exception):
        parse_identity_assertion({**assertion.to_dict(), "unexpected": True})


def test_identity_revocation_rotation_and_stale_assertion_fail_closed():
    signer, registry, assertion = _identity()
    registry.revoke(signer.identity.identity_id)
    with pytest.raises(IdentityError, match="revoked"):
        registry.verify(assertion)

    signer, registry, assertion = _identity()
    rotated = replace(signer.identity, version=2)
    registry.register(rotated)
    with pytest.raises(IdentityError, match="stale"):
        registry.verify(assertion)
    rotated_signer = IdentitySigner(rotated, signer.key_id, signer._private_key)
    now = int(time.time() * 1000)
    assert registry.verify(rotated_signer.assert_identity(issued_at_ms=now - 1, expires_at_ms=now + 60_000)).version == 2


def test_identity_survives_model_controller_handoff_but_scoped_identity_does_not():
    signer, registry, assertion = _identity()
    backend = _backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=_policy(), agent_id="model-a")
        runtime.bind_identity(opened.session_id, assertion, registry)
        checkpoint = runtime.prepare_agent_handoff(
            opened.session_id, agent_id="model-a", control_token=opened.control["control_token"], recipient_agent_id="model-b",
        )
        handoff = runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "model-b", authenticated_agent_id="model-b")
    assert handoff.identity["identity_id"] == signer.identity.identity_id

    signer, registry, assertion = _identity(controller_scope="model-a")
    backend = _backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=_policy(), agent_id="model-a")
        runtime.bind_identity(opened.session_id, assertion, registry)
        checkpoint = runtime.prepare_agent_handoff(
            opened.session_id, agent_id="model-a", control_token=opened.control["control_token"], recipient_agent_id="model-b",
        )
        with pytest.raises(StatefulSessionError) as rejected:
            runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "model-b", authenticated_agent_id="model-b")
    assert rejected.value.failure_kind.value == "handoff_recipient_rejected"


def test_identity_does_not_expand_authority_and_receipts_are_attributed():
    signer, registry, assertion = _identity()
    backend = _backend()
    denied = _policy(actions=("click",))
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=denied, agent_id="local-non-llm")
        runtime.bind_identity(opened.session_id, assertion, registry)
        result = runtime.execute_operation(opened.session_id, _operation(), agent_id="local-non-llm", control_token=opened.control["control_token"])
    assert result.receipt.execution_status == "authority_rejected"
    assert result.receipt.identity["identity_id"] == signer.identity.identity_id
    assert result.receipt.identity == identity_reference(signer.identity, assertion)


def test_signed_plan_identity_scope_is_cumulative_and_mismatch_rejected():
    signer, registry, assertion = _identity()
    plan = ExecutionPlan("p", [_operation()], authority_envelope=_policy())
    document = PlanDocument("1.0.0", plan.browser_config, plan)
    plan_signer = TrustedPlanSigner.generate("plan-signer")
    now = int(time.time() * 1000)
    signed = plan_signer.sign(document, authority_envelope_hash=_policy().digest, issued_at_ms=now - 1, expires_at_ms=now + 60_000, nonce="identity-mismatch", agent_identity_id="other-identity")
    verifier = TrustedPlanVerifier({"plan-signer": plan_signer.public_key_bytes()})
    backend = _backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=_policy(), agent_id="local")
        runtime.bind_identity(opened.session_id, assertion, registry)
        with pytest.raises(StatefulSessionError) as rejected:
            runtime.bind_signed_plan_authority(opened.session_id, document, signed, verifier)
    assert rejected.value.failure_kind.value == "signed_plan_rejected"


def test_revoked_identity_blocks_existing_governed_session():
    signer, registry, assertion = _identity()
    backend = _backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=_policy(), agent_id="agent")
        runtime.bind_identity(opened.session_id, assertion, registry)
        registry.revoke(signer.identity.identity_id)
        with pytest.raises(StatefulSessionError) as rejected:
            runtime.execute_operation(opened.session_id, _operation(), agent_id="agent", control_token=opened.control["control_token"])
    assert rejected.value.failure_kind.value == "operation_rejected"
