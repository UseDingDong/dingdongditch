"""Second-order adversarial regressions for execution governance.

These probe the hardened paths rather than replaying Audit #1 cases.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from unittest.mock import MagicMock, patch

import pytest

from dingdongditch import (
    Action, ActionType, AuthorityEnvelope, AuthorityFirewall, CommitRejectedReason,
    EvidenceSourceClass, Expectation, ExpectationType, GovernedAgentService,
    MappingSecretProvider, ObservationReference, Operation, ProvenanceClass,
    ReceiptChainCheckpoint, StatefulSessionRuntime, TrustedHostRuntime,
    VerificationCheck, VerificationPolicy, VerificationQuorum, chain_receipt,
    hash_receipt, make_receipt_chain_checkpoint, parse_execution_receipt,
    parse_plan_document, verify_receipt_chain_against_checkpoint,
)
from dingdongditch.authentication import AuthenticationCapability, SecretValue
from dingdongditch.contract.authority import canonical_json_bytes
from dingdongditch.contract.quorum import evaluate_quorum
from dingdongditch.contract.transaction import TwoPhaseCommitError
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.models import ExpectationResult
from dingdongditch.runtime.executor import _failed_receipt


def _backend() -> MagicMock:
    backend = MagicMock()
    backend.is_started = True
    backend.page_id = "page-1"
    backend.page.url = "https://allowed.example.test/form"
    backend.page.evaluate.return_value = {
        "url": backend.page.url, "readyState": "complete", "title": "form", "root": "<form></form>",
    }
    backend.read_element_state.return_value = {"exists": True, "ambiguous": False, "text": "Send"}
    backend.transaction_target_identity.return_value = "node-1"
    backend.transaction_scope_state.return_value = {
        "url": backend.page.url, "readyState": "complete", "title": "form", "root": "<form></form>",
        "history_length": 1, "history_state": "null", "controls": [], "document_token": "doc-1", "mutation_count": 0,
    }
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True, "current_url": backend.page.url, "lifecycle_state": "open"}]
    backend.list_dialog_history.return_value = []
    backend.browser_environment.return_value = {"browser_session_id": "browser", "context_id": "context", "page_id": "page-1"}
    backend.backend_identity = "fake"; backend.browser_identity = "fake"; backend.cleanup_errors = []
    return backend


def _policy(**changes: object) -> AuthorityEnvelope:
    values: dict[str, object] = {
        "policy_id": "second-round",
        "granted_authorities": (ProvenanceClass.HOST_POLICY,),
        "allowed_origins": ("https://allowed.example.test",),
        "allowed_action_types": ("navigate", "click", "fill"),
    }
    values.update(changes)
    return AuthorityEnvelope(**values)


def _operation(action: Action | None = None) -> Operation:
    return Operation("op", "https://allowed.example.test/form", action or Action(ActionType.NAVIGATE))


def _runtime(backend: MagicMock, policy: AuthorityEnvelope, *, agent_id: str | None = None):
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=policy, agent_id=agent_id)
    return runtime, opened


def _receipt(identifier: str, *, session: str = "browser") -> dict[str, object]:
    return {
        "schema_version": "1.8.0", "operation_id": identifier, "verdict": "VERIFIED", "action_type": "click",
        "target_locator": None, "target_resolution": None, "target_url": "https://allowed.example.test/form",
        "execution_status": "completed", "execution_error": None, "failure_kind": None,
        "action_executed_successfully": True, "action_evidence": {"dispatch": "ok"}, "page_precondition": None,
        "page_transition": None, "navigation_occurred": False, "dispatch_document_url": None,
        "authority_decision": {"policy_hash": "policy"}, "transaction": None, "quorum_verification": None,
        "control_epoch": 0, "expectation_results": [], "freshness": {}, "expectation_evidence": [], "evidence": [],
        "artifacts": [], "runtime_version": "0.4.1",
        "browser": {"browser_session_id": session, "context_id": "context", "page_id": "page"},
    }


def test_secret_rotation_or_legacy_provider_cannot_substitute_prepared_fill():
    backend = _backend()
    provider = MappingSecretProvider({"host/password": "first"})
    backend.authentication = AuthenticationCapability(secrets=provider)
    policy = _policy(
        allowed_secret_references=("host/password",), require_preparation_for=("fill",),
    )
    runtime, opened = _runtime(backend, policy)
    secret_fill = _operation(Action(ActionType.FILL, locator=MagicMock(), secret_reference="host/password"))
    # A real locator is irrelevant to the prepare binding; it must only satisfy
    # typed action validation before the fake browser boundary.
    from dingdongditch import Locator, LocatorStrategy
    secret_fill = _operation(Action(ActionType.FILL, locator=Locator(LocatorStrategy.TEST_ID, "password"), secret_reference="host/password"))
    prepared = runtime.prepare_operation(opened.session_id, secret_fill)
    provider.replace("host/password", "rotated")
    with patch("dingdongditch.runtime.stateful_session._execute_operation") as dispatch:
        result = runtime.commit_operation(opened.session_id, prepared.token)
    assert result.rejection_reason is CommitRejectedReason.SECRET_BINDING_CHANGED
    dispatch.assert_not_called()

    class LegacyProvider:
        def resolve(self, _reference):
            return SecretValue("not-bound")

    backend = _backend(); backend.authentication = AuthenticationCapability(secrets=LegacyProvider())
    runtime, opened = _runtime(backend, policy)
    with pytest.raises(TwoPhaseCommitError) as raised:
        runtime.prepare_operation(opened.session_id, secret_fill)
    assert raised.value.reason is CommitRejectedReason.SECRET_BINDING_UNAVAILABLE


def test_prepared_public_operation_hash_is_not_a_plaintext_credential_digest():
    from dingdongditch import Locator, LocatorStrategy
    backend = _backend()
    policy = _policy(require_preparation_for=("fill",))
    runtime, opened = _runtime(backend, policy)
    operation = _operation(Action(ActionType.FILL, locator=Locator(LocatorStrategy.TEST_ID, "password"), text="1234"))
    prepared = runtime.prepare_operation(opened.session_id, operation)
    assert prepared.operation_hash != hashlib.sha256(canonical_json_bytes(operation.to_public_dict())).hexdigest()


def test_checkpoint_detects_truncation_rewrite_reordering_and_cross_session():
    first = chain_receipt(_receipt("one"), session_id="runtime-a")
    second = chain_receipt(_receipt("two"), previous_receipt_hash=first["receipt_chain"]["receipt_hash"], session_id="runtime-a")
    checkpoint = make_receipt_chain_checkpoint([first, second], session_id="runtime-a", timestamp_ms=1)
    third = chain_receipt(_receipt("three"), previous_receipt_hash=second["receipt_chain"]["receipt_hash"], session_id="runtime-a")
    assert verify_receipt_chain_against_checkpoint([first, second, third], checkpoint).valid
    assert not verify_receipt_chain_against_checkpoint([first], checkpoint).valid  # tail truncation
    assert not verify_receipt_chain_against_checkpoint([second], checkpoint).valid  # prefix truncation
    rewritten_one = chain_receipt(_receipt("one-rewritten"), session_id="runtime-a")
    rewritten_two = chain_receipt(_receipt("two-rewritten"), previous_receipt_hash=rewritten_one["receipt_chain"]["receipt_hash"], session_id="runtime-a")
    assert not verify_receipt_chain_against_checkpoint([rewritten_one, rewritten_two], checkpoint).valid
    assert not verify_receipt_chain_against_checkpoint([second, first], checkpoint).valid
    assert not verify_receipt_chain_against_checkpoint([first, second], replace(checkpoint, session_id="runtime-b")).valid
    assert not verify_receipt_chain_against_checkpoint([first, second], replace(checkpoint, chain_head_hash="0" * 64)).valid
    assert not verify_receipt_chain_against_checkpoint([first, second], replace(checkpoint, chain_length=3)).valid


def test_observation_taint_is_monotonic_for_irreversible_governed_action():
    backend = _backend()
    policy = _policy(irreversible_action_types=("navigate",), deny_untrusted_for_irreversible=True)
    runtime, opened = _runtime(backend, policy)
    with patch("dingdongditch.runtime.stateful_session._execute_operation") as dispatch:
        result = runtime.execute_operation(
            opened.session_id, _operation(),
            observation_reference=ObservationReference("observation", "target"),
        )
    assert result.receipt.authority_decision["outcome"] == "PROVENANCE_POLICY_REJECTED"
    assert "web_untrusted" in result.receipt.authority_decision["input_provenance"]
    dispatch.assert_not_called()


def test_firewall_uses_normalized_origin_semantics_and_denies_opaque_navigation():
    policy = _policy(allowed_origins=("https://xn--bcher-kva.example",))
    unicode_op = Operation("unicode", "https://bücher.example/path", Action(ActionType.NAVIGATE))
    assert AuthorityFirewall().decide(unicode_op, policy, now_ms=1).authorized
    exact = _policy(allowed_origins=("https://allowed.example.test",))
    default_port = Operation("port", "https://allowed.example.test:443/path", Action(ActionType.NAVIGATE))
    assert AuthorityFirewall().decide(default_port, exact, now_ms=1).authorized
    opaque = Operation("opaque", "data:text/html,hello", Action(ActionType.NAVIGATE))
    assert not AuthorityFirewall().decide(opaque, _policy(allowed_origins=()), now_ms=1).authorized


def test_allowed_click_that_reaches_denied_final_origin_is_flagged_after_dispatch():
    from dingdongditch import Locator, LocatorStrategy
    backend = _backend()
    backend.scoped_action_url.side_effect = [backend.page.url, "https://denied.example.test/final"]
    runtime, opened = _runtime(backend, _policy(allowed_action_types=("click",)))
    operation = _operation(Action(ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "send")))
    raw = _failed_receipt(
        operation=operation, started_at=1,
        collector=EvidenceCollector(scope_id="post-dispatch", window_started_at_ms=1),
        locator_desc=None, execution_status="completed", execution_error=None, failure_kind=None,
        browser=backend.browser_environment(), backend_identity="fake", browser_identity="fake", verdict=Verdict.VERIFIED,
    )
    receipt = replace(raw, _sealed=False, action_started_at_ms=2, action_completed_at_ms=3, action_executed_successfully=True).seal()
    with patch("dingdongditch.runtime.stateful_session._execute_operation", return_value=receipt):
        result = runtime.execute_operation(opened.session_id, operation)
    assert result.receipt.execution_status == "post_dispatch_authority_rejected"
    assert result.receipt.authority_decision["origin"] == "https://denied.example.test"


def test_preparation_fingerprint_binds_mutation_epoch_controls_and_page_registry():
    backend = _backend()
    state = {
        "url": backend.page.url, "readyState": "complete", "title": "form", "root": "<form></form>",
        "history_length": 2, "history_state": "{}", "document_token": "document-1", "mutation_count": 0,
        "controls": [{"name": "csrf", "value": "one"}],
    }
    backend.transaction_scope_state.side_effect = [dict(state), {**state, "mutation_count": 2}]
    action = Action(ActionType.CLICK, locator=__import__("dingdongditch").Locator(__import__("dingdongditch").LocatorStrategy.TEST_ID, "send"))
    runtime, opened = _runtime(backend, _policy(require_preparation_for=("click",)))
    prepared = runtime.prepare_operation(opened.session_id, _operation(action))
    assert runtime.commit_operation(opened.session_id, prepared.token).rejection_reason is CommitRejectedReason.PREPARED_STATE_CHANGED

    backend = _backend(); backend.transaction_scope_state.side_effect = [dict(state), {**state, "controls": [{"name": "csrf", "value": "two"}]}]
    runtime, opened = _runtime(backend, _policy(require_preparation_for=("click",)))
    prepared = runtime.prepare_operation(opened.session_id, _operation(action))
    assert runtime.commit_operation(opened.session_id, prepared.token).rejection_reason is CommitRejectedReason.PREPARED_STATE_CHANGED


def test_quorum_rejects_stale_or_duplicate_result_laundering():
    quorum = VerificationQuorum(
        VerificationPolicy.N_OF_M,
        (VerificationCheck("dom", "dom", EvidenceSourceClass.DOM_STATE), VerificationCheck("page", "page", EvidenceSourceClass.PAGE_STATE)),
        2,
    )
    stale = ExpectationResult("dom", "text", {}, {}, "pass", [], 1, "", False, None)
    fresh = ExpectationResult("page", "url", {}, {}, "pass", [], 2, "", True, None)
    assert evaluate_quorum(quorum, [stale, fresh]).verdict is Verdict.INDETERMINATE
    duplicate = ExpectationResult("dom", "text", {}, {}, "pass", [], 2, "", True, None)
    assert evaluate_quorum(quorum, [duplicate, duplicate, fresh]).verdict is Verdict.INDETERMINATE


def test_canonicalization_rejects_ambiguous_values_and_binds_unchecksummed_artifacts():
    assert hash_receipt({**_receipt("unicode"), "action_evidence": {"text": "é"}}) == hash_receipt({**_receipt("unicode"), "action_evidence": {"text": "e\u0301"}})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json_bytes({"n": float("nan")})
    with pytest.raises(TypeError, match="bytes-like"):
        canonical_json_bytes({"n": b"x"})
    receipt = chain_receipt(_receipt("artifact"), session_id="runtime-a")
    altered = {**receipt, "artifacts": [{"artifact_id": "late"}]}
    from dingdongditch import verify_receipt_hash
    assert not verify_receipt_hash(altered)


def test_handoff_recipient_and_authenticated_transport_are_required_on_governed_path():
    backend = _backend()
    runtime, opened = _runtime(backend, _policy(), agent_id="agent-a")
    token = opened.control["control_token"]
    checkpoint = runtime.prepare_agent_handoff(
        opened.session_id, agent_id="agent-a", control_token=token, recipient_agent_id="agent-b",
    )
    with pytest.raises(Exception, match="recipient"):
        runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "agent-c")
    service = GovernedAgentService(runtime)
    with pytest.raises(PermissionError):
        service.execute(
            session_id=opened.session_id, agent_id="agent-a", control_token=token,
            authenticated_agent_id="agent-c", operation=_operation(),
        )


def test_documented_governed_agent_handle_cannot_bypass_preparation_or_install_policy():
    backend = _backend()
    policy = _policy(require_preparation_for=("navigate",))
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        host = TrustedHostRuntime()
        agent = host.open_governed_agent_session(authority_envelope=policy, agent_id="agent-a")
    # The agent handle accepts only proposals plus its host-issued lease; it
    # has no policy-install or raw-browser execution method.
    assert not hasattr(agent, "install_authority") and not hasattr(agent, "execute_plan")
    rejected = agent.execute(_operation())
    assert rejected.receipt.execution_status == "preparation_required"


def test_machine_parser_rejects_duplicate_json_and_unknown_receipt_fields():
    duplicate = '{"schema_version":"1.0.0","browser":{},"plan":{"plan_id":"a","plan_id":"b","operations":[]}}'
    with pytest.raises(Exception, match="valid JSON"):
        parse_plan_document(duplicate)
    raw = _receipt("receipt")
    raw.update({
        "started_at_ms": 1, "finished_at_ms": 2, "action_started_at_ms": None,
        "action_completed_at_ms": None, "verification_completed_at_ms": None,
        "telemetry": [], "operation_timing": None, "cleanup": None, "expectations_declared": 0,
        "pre_action_observation": None, "post_action_observation": None, "recovery_attempts": [],
        "limitations": [], "backend_identity": "fake", "browser_identity": "fake", "unexpected": "ignored-before",
    })
    with pytest.raises(Exception, match="unknown fields"):
        parse_execution_receipt(raw)
