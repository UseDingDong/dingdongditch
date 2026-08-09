from __future__ import annotations

from dataclasses import replace
import time
from unittest.mock import MagicMock, patch

import pytest

from dingdongditch import (
    Action,
    ActionType,
    AuthorityEnvelope,
    ExecutionPlan,
    Operation,
    ProvenanceClass,
    SignedPlanAuthority,
    StatefulSessionError,
    StatefulSessionRuntime,
    TrustedPlanSigner,
    TrustedPlanVerifier,
    Expectation,
    ExpectationType,
    SpeculativeBranch,
    SpeculativePlan,
    canonical_plan_hash,
    parse_signed_plan_authority,
    serialize_plan_document,
)
from dingdongditch.machine_contract import PlanDocument


def _policy() -> AuthorityEnvelope:
    return AuthorityEnvelope(
        policy_id="signed-plan-policy",
        allowed_origins=("https://example.test",),
        allowed_action_types=("navigate",),
        granted_authorities=(ProvenanceClass.HOST_POLICY, ProvenanceClass.AGENT_REASONING),
    )


def _document(*, text: str = "", policy: AuthorityEnvelope | None = None) -> PlanDocument:
    operation = Operation(
        "navigate", "https://example.test/", Action(ActionType.NAVIGATE),
        provenance=(ProvenanceClass.AGENT_REASONING,),
    )
    # ``text`` changes a meaningful field without changing the helper shape.
    if text:
        operation = Operation("navigate", f"https://example.test/{text}", Action(ActionType.NAVIGATE), provenance=(ProvenanceClass.AGENT_REASONING,))
    plan = ExecutionPlan("signed-plan", [operation], authority_envelope=policy or _policy())
    return PlanDocument("1.0.0", plan.browser_config, plan)


def _signed(document: PlanDocument, *, now: int = 10_000, **kwargs):
    signer = TrustedPlanSigner.generate("host-signer")
    authority = signer.sign(
        document,
        authority_envelope_hash=_policy().digest,
        issued_at_ms=now - 10,
        expires_at_ms=now + 10_000,
        nonce="nonce-1",
        **kwargs,
    )
    verifier = TrustedPlanVerifier({"host-signer": signer.public_key_bytes()})
    return authority, verifier


def test_valid_signed_plan_canonical_machine_round_trip_and_unicode_normalization():
    document = _document()
    authority, verifier = _signed(document)
    parsed = parse_signed_plan_authority(authority.to_dict())
    assert parsed == authority
    assert verifier.verify(parsed, document, authority_envelope_hash=_policy().digest, now_ms=10_000).valid
    assert canonical_plan_hash(document) == canonical_plan_hash(
        PlanDocument("1.0.0", document.browser, document.plan)
    )
    assert serialize_plan_document(document)["schema_version"] == "1.0.0"


@pytest.mark.parametrize("mutation", ["operation", "locator_payload", "authority"])
def test_signed_plan_rejects_modified_execution_material(mutation: str):
    document = _document()
    authority, verifier = _signed(document)
    if mutation == "authority":
        result = verifier.verify(authority, document, authority_envelope_hash="0" * 64, now_ms=10_000)
    else:
        result = verifier.verify(authority, _document(text="changed"), authority_envelope_hash=_policy().digest, now_ms=10_000)
    assert not result.valid
    assert result.reason in {"plan_hash_mismatch", "authority_hash_mismatch"}


def test_signed_plan_rejects_expiry_future_untrusted_malformed_and_replay():
    document = _document()
    authority, verifier = _signed(document)
    assert verifier.verify(authority, document, authority_envelope_hash=_policy().digest, now_ms=9_989).reason == "not_yet_valid"
    assert verifier.verify(authority, document, authority_envelope_hash=_policy().digest, now_ms=20_000).reason == "expired"
    untrusted = TrustedPlanVerifier({})
    assert untrusted.verify(authority, document, authority_envelope_hash=_policy().digest, now_ms=10_000).reason == "untrusted_signer"
    malformed = replace(authority, signature="not-base64")
    assert verifier.verify(malformed, document, authority_envelope_hash=_policy().digest, now_ms=10_000).reason == "malformed_signed_plan"
    assert verifier.verify(authority, document, authority_envelope_hash=_policy().digest, now_ms=10_000, consume=True).valid
    assert verifier.verify(authority, document, authority_envelope_hash=_policy().digest, now_ms=10_000).reason == "replay_limit_exhausted"


def test_signed_plan_scope_and_next_operation_constraint_fail_closed():
    backend = MagicMock()
    backend.is_started = True
    backend.page.url = "https://example.test/"
    backend.page_id = "page-1"
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True}]
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=_policy(), agent_id="agent-a")
        document = _document()
        signer = TrustedPlanSigner.generate("host-signer")
        now = int(time.time() * 1000)
        bound = signer.sign(
            document, authority_envelope_hash=_policy().digest, issued_at_ms=now - 10,
            expires_at_ms=now + 10_000, nonce="scope", session_scope=opened.session_id,
        )
        verifier = TrustedPlanVerifier({"host-signer": signer.public_key_bytes()})
        runtime.bind_signed_plan_authority(opened.session_id, document, bound, verifier)
        with pytest.raises(StatefulSessionError) as rejected:
            runtime.execute_operation(
                opened.session_id, _document(text="substitution").plan.operations[0],
                agent_id="agent-a", control_token=opened.control["control_token"],
            )
        assert rejected.value.failure_kind.value == "signed_plan_rejected"


def test_signed_plan_cross_session_replay_and_unsupported_algorithm_rejected():
    document = _document()
    authority, verifier = _signed(document)
    assert verifier.verify(authority, document, authority_envelope_hash=_policy().digest, session_scope="other", now_ms=10_000).valid
    unsupported = replace(authority, algorithm="rsa-raw")
    assert verifier.verify(unsupported, document, authority_envelope_hash=_policy().digest, now_ms=10_000).reason == "malformed_signed_plan"


def test_signed_plan_never_expands_firewall_authority():
    denied = AuthorityEnvelope(
        policy_id="denied-by-firewall",
        allowed_origins=("https://example.test",),
        allowed_action_types=("click",),
        granted_authorities=(ProvenanceClass.HOST_POLICY, ProvenanceClass.AGENT_REASONING),
    )
    document = _document(policy=denied)
    signer = TrustedPlanSigner.generate("host-signer")
    verifier = TrustedPlanVerifier({"host-signer": signer.public_key_bytes()})
    backend = MagicMock()
    backend.is_started = True
    backend.page.url = "https://example.test/"
    backend.page_id = "page-1"
    backend.backend_identity = "test"
    backend.browser_identity = "test"
    backend.browser_environment.return_value = {"page_id": "page-1"}
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True}]
    backend.list_dialog_history.return_value = []
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=denied, agent_id="agent-a")
        now = int(time.time() * 1000)
        authority = signer.sign(
            document, authority_envelope_hash=denied.digest, issued_at_ms=now - 10,
            expires_at_ms=now + 10_000, nonce="firewall",
        )
        runtime.bind_signed_plan_authority(opened.session_id, document, authority, verifier)
        result = runtime.execute_operation(
            opened.session_id, document.plan.operations[0], agent_id="agent-a",
            control_token=opened.control["control_token"],
        )
    assert result.receipt.execution_status == "authority_rejected"
    assert result.receipt.signed_plan["status"] == "verified"


def test_signed_plan_binds_exact_speculative_topology_and_rejects_unsigned_sidecars():
    policy = _policy()
    parent = Operation("parent", "https://example.test/", Action(ActionType.NAVIGATE), provenance=(ProvenanceClass.AGENT_REASONING,))
    branch = SpeculativeBranch(
        "continue",
        (Expectation(ExpectationType.URL, url_value="https://example.test/"),),
        Operation("branch", "https://example.test/", Action(ActionType.NAVIGATE), provenance=(ProvenanceClass.AGENT_REASONING,)),
    )
    topology = SpeculativePlan("signed-topology", "parent", (branch,), parent_operation=parent)
    plan = ExecutionPlan("signed-speculation", [parent], authority_envelope=policy, speculative_plans=(topology,))
    document = PlanDocument("1.0.0", plan.browser_config, plan)
    backend = MagicMock()
    backend.is_started = True; backend.page.url = "https://example.test/"; backend.page_id = "page-1"
    backend.scoped_action_url.return_value = "https://example.test/"
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True}]
    signer = TrustedPlanSigner.generate("host-signer")
    verifier = TrustedPlanVerifier({"host-signer": signer.public_key_bytes()})
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=policy, agent_id="agent")
        now = int(time.time() * 1000)
        authority = signer.sign(document, authority_envelope_hash=policy.digest, issued_at_ms=now - 1, expires_at_ms=now + 10_000, nonce="topology", session_scope=opened.session_id)
        runtime.bind_signed_plan_authority(opened.session_id, document, authority, verifier)
        prepared = runtime.prepare_speculation(opened.session_id, topology, agent_id="agent", control_token=opened.control["control_token"])
        assert prepared.speculation_id == "signed-topology"
        widened = SpeculativePlan(
            "signed-topology", "parent",
            topology.branches + (SpeculativeBranch("extra", branch.preconditions, Operation("extra", "https://example.test/", Action(ActionType.NAVIGATE))),),
            parent_operation=parent,
        )
        with pytest.raises(StatefulSessionError):
            runtime.prepare_speculation(opened.session_id, widened, agent_id="agent", control_token=opened.control["control_token"])
        altered_parent = SpeculativePlan("signed-topology", "parent", topology.branches, parent_operation=Operation("parent", "https://example.test/other", Action(ActionType.NAVIGATE)))
        with pytest.raises(StatefulSessionError):
            runtime.prepare_speculation(opened.session_id, altered_parent, agent_id="agent", control_token=opened.control["control_token"])


def test_signed_plan_verifier_rejects_revoked_signer_and_bounds_replay_cache():
    document = _document()
    authority, verifier = _signed(document)
    verifier.revoke_signer("host-signer")
    assert verifier.verify(authority, document, authority_envelope_hash=_policy().digest, now_ms=10_000).reason == "revoked_signer"


def test_bound_signed_plan_cannot_execute_after_authority_expiry():
    backend = MagicMock()
    backend.is_started = True; backend.page.url = "https://example.test/"; backend.page_id = "page-1"
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True}]
    document = _document()
    signer = TrustedPlanSigner.generate("host-signer")
    verifier = TrustedPlanVerifier({"host-signer": signer.public_key_bytes()})
    now = int(time.time() * 1000)
    authority = signer.sign(document, authority_envelope_hash=_policy().digest, issued_at_ms=now - 10, expires_at_ms=now + 100, nonce="short")
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=_policy(), agent_id="agent")
        runtime.bind_signed_plan_authority(opened.session_id, document, authority, verifier)
        with patch("dingdongditch.runtime.stateful_session._now_ms", return_value=authority.expires_at_ms):
            with pytest.raises(StatefulSessionError) as rejected:
                runtime.execute_operation(opened.session_id, document.plan.operations[0], agent_id="agent", control_token=opened.control["control_token"])
    assert rejected.value.failure_kind.value == "signed_plan_rejected"
