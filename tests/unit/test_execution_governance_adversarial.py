"""Hostile-planner regression tests for the execution-governance boundary.

These deliberately use the public stateful APIs while controlling only the
deterministic fake browser beneath them.  They are not happy-path feature
tests: each case models a planner attempting to reuse a capability or hide a
material state change.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import Event, Thread
from unittest.mock import MagicMock, patch

import pytest

from dingdongditch import (
    Action, ActionType, AuthorityEnvelope, AuthorityFirewall, CommitRejectedReason,
    EvidenceSourceClass, Expectation, ExpectationType, FirewallOutcome, GuardBranch,
    Locator, LocatorStrategy, Operation, OperationGuard, ProvenanceClass,
    StatefulSessionError, StatefulSessionRuntime, VerificationCheck,
    VerificationPolicy, VerificationQuorum, chain_receipt, evaluate_quorum,
    parse_execution_receipt, verify_receipt_chain, verify_receipt_hash,
)
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.authority import canonical_json_bytes
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.models import ExpectationResult
from dingdongditch.runtime.executor import _failed_receipt


def _backend() -> MagicMock:
    backend = MagicMock()
    backend.is_started = True
    backend.page_id = "page-1"
    backend.page.url = "https://allowed.example.test/form"
    backend.page.evaluate.side_effect = lambda _script: {
        "url": backend.page.url, "readyState": "complete", "title": "form", "root": "<html>same</html>",
    }
    backend.read_element_state.return_value = {"exists": True, "ambiguous": False, "text": "Send"}
    backend.transaction_target_identity.return_value = "node-1"
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True, "current_url": backend.page.url}]
    backend.list_dialog_history.return_value = []
    backend.backend_identity = "fake"
    backend.browser_identity = "fake"
    backend.browser_environment.return_value = {
        "engine": "chromium", "browser_session_id": "browser-session", "context_id": "context", "page_id": "page-1",
    }
    backend.cleanup_errors = []
    return backend


def _policy(**changes: object) -> AuthorityEnvelope:
    values: dict[str, object] = {
        "policy_id": "host-policy",
        "granted_authorities": (ProvenanceClass.HOST_POLICY,),
        "allowed_origins": ("https://allowed.example.test",),
        "allowed_action_types": ("navigate", "click", "fill"),
    }
    values.update(changes)
    return AuthorityEnvelope(**values)


def _navigate() -> Operation:
    return Operation("navigate", "https://allowed.example.test/form", Action(ActionType.NAVIGATE))


def _click() -> Operation:
    return Operation("click", "https://allowed.example.test/form", Action(ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "send")))


def _receipt(operation: Operation, backend: MagicMock, *, successful: bool = True) -> ExecutionReceipt:
    raw = _failed_receipt(
        operation=operation, started_at=1,
        collector=EvidenceCollector(scope_id="security", window_started_at_ms=1),
        locator_desc=None, execution_status="completed", execution_error=None,
        failure_kind=None, browser=backend.browser_environment(), backend_identity="fake",
        browser_identity="fake", verdict=(Verdict.VERIFIED if successful else Verdict.NOT_VERIFIED),
    )
    return replace(raw, _sealed=False, action_started_at_ms=2, action_completed_at_ms=3,
                   action_executed_successfully=successful).seal()


def _runtime(backend: MagicMock, policy: AuthorityEnvelope, *, agent_id: str | None = None):
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        info = runtime.open_session(authority_envelope=policy, agent_id=agent_id)
    return runtime, info


def test_public_session_inspection_cannot_leak_or_reuse_control_lease():
    runtime, opened = _runtime(_backend(), _policy(), agent_id="agent-a")
    assert opened.control is not None and "control_token" in opened.control
    public = runtime.get_session(opened.session_id)
    assert public.control == {"agent_id": "agent-a", "control_epoch": 0}
    with pytest.raises(StatefulSessionError):
        runtime.execute_operation(opened.session_id, _navigate(), agent_id="agent-a", control_token="guessed")


def test_policy_mapping_is_immutable_and_frames_are_default_denied():
    policy = _policy(required_authority_by_action={"click": ProvenanceClass.USER_AUTHORITY})
    with pytest.raises(TypeError):
        policy.required_authority_by_action["click"] = ProvenanceClass.HOST_POLICY
    frame_action = Action(
        ActionType.CLICK,
        locator=Locator(LocatorStrategy.TEST_ID, "send"),
        frame=Locator(LocatorStrategy.TEST_ID, "embedded"),
    )
    assert AuthorityFirewall().decide(_click().__class__("frame", "https://allowed.example.test/form", frame_action), _policy(), now_ms=1).outcome is FirewallOutcome.POLICY_REJECTED
    # Immutable policy internals and unordered Python containers must not make
    # a public policy/receipt fingerprint non-deterministic.
    assert canonical_json_bytes(policy) == canonical_json_bytes(policy)
    assert canonical_json_bytes({"set": {"b", "a"}}) == canonical_json_bytes({"set": {"a", "b"}})
    with pytest.raises(TypeError, match="string keys"):
        canonical_json_bytes({1: "ambiguous"})
    forged = Operation(
        "forged", "https://allowed.example.test/form", Action(ActionType.NAVIGATE),
        provenance=(ProvenanceClass.HOST_POLICY,),
    )
    assert AuthorityFirewall().decide(forged, _policy(), now_ms=1).outcome is FirewallOutcome.PROVENANCE_POLICY_REJECTED


def test_explicit_frame_opt_in_still_authorizes_the_resolved_frame_origin():
    backend = _backend()
    backend.scoped_action_url.return_value = "https://evil.example.test/embedded"
    operation = Operation(
        "frame", "https://allowed.example.test/form",
        Action(ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "send"), frame=Locator(LocatorStrategy.TEST_ID, "embedded")),
    )
    runtime, session = _runtime(backend, _policy(allow_frame_actions=True))
    with patch("dingdongditch.runtime.stateful_session._execute_operation") as execute:
        result = runtime.execute_operation(session.session_id, operation)
    assert result.receipt.authority_decision["outcome"] == FirewallOutcome.ORIGIN_NOT_ALLOWED.value
    execute.assert_not_called()


def test_guarded_subaction_cannot_smuggle_denied_action_or_budget_slots():
    backend = _backend()
    guarded = Operation(
        "guarded", "https://allowed.example.test/form",
        Action(ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "send")),
        guard=OperationGuard(branches=(GuardBranch(
            "matched",
            (Expectation(type=ExpectationType.ELEMENT_EXISTS, locator=Locator(LocatorStrategy.TEST_ID, "send"), exists=True),),
            (Action(ActionType.FILL, locator=Locator(LocatorStrategy.TEST_ID, "secret"), text="smuggled"),),
        ),)),
    )
    runtime, session = _runtime(backend, _policy(allowed_action_types=("click",)))
    with patch("dingdongditch.runtime.stateful_session._execute_operation") as execute:
        rejected = runtime.execute_operation(session.session_id, guarded)
    assert rejected.receipt.authority_decision["outcome"] == FirewallOutcome.ACTION_NOT_ALLOWED.value
    execute.assert_not_called()


def test_dispatched_verification_failure_charges_budget_and_redirect_is_rejected():
    backend = _backend()
    runtime, session = _runtime(backend, _policy(max_action_count=1))
    with patch("dingdongditch.runtime.stateful_session._execute_operation", return_value=_receipt(_navigate(), backend, successful=False)) as execute:
        runtime.execute_operation(session.session_id, _navigate())
        rejected = runtime.execute_operation(session.session_id, _navigate())
    assert rejected.receipt.authority_decision["outcome"] == FirewallOutcome.SIDE_EFFECT_BUDGET_EXCEEDED.value
    assert execute.call_count == 1

    backend = _backend()
    runtime, session = _runtime(backend, _policy())
    def redirected(*_args, **_kwargs):
        backend.page.url = "https://denied.example.test/final"
        return _receipt(_navigate(), backend)
    with patch("dingdongditch.runtime.stateful_session._execute_operation", side_effect=redirected):
        result = runtime.execute_operation(session.session_id, _navigate())
    assert result.receipt.execution_status == "post_navigation_authority_rejected"
    assert result.receipt.action_evidence["post_navigation_authority"]["outcome"] == FirewallOutcome.ORIGIN_NOT_ALLOWED.value


def test_prepare_detects_same_markup_node_replacement_and_consumes_before_dispatch_failure():
    backend = _backend()
    runtime, session = _runtime(backend, _policy(require_preparation_for=("click",)))
    backend.transaction_target_identity.side_effect = ["node-1", "node-2"]
    prepared = runtime.prepare_operation(session.session_id, _click())
    changed = runtime.commit_operation(session.session_id, prepared.token)
    assert changed.rejection_reason is CommitRejectedReason.TARGET_CHANGED

    backend = _backend()
    runtime, session = _runtime(backend, _policy(require_preparation_for=("click",)))
    prepared = runtime.prepare_operation(session.session_id, _click())
    with patch.object(runtime, "execute_operation", side_effect=RuntimeError("post-dispatch runtime crash")):
        with pytest.raises(RuntimeError):
            runtime.commit_operation(session.session_id, prepared.token)
    assert runtime.commit_operation(session.session_id, prepared.token).rejection_reason is CommitRejectedReason.ALREADY_COMMITTED


def test_commit_passes_private_node_binding_to_the_dispatch_boundary():
    backend = _backend()
    runtime, session = _runtime(backend, _policy(require_preparation_for=("click",)))
    prepared = runtime.prepare_operation(session.session_id, _click())
    def dispatch(bound_operation, **_kwargs):
        key, value = getattr(bound_operation, "_transaction_target_identity")
        assert key.startswith("__dingdongditch_prepared_") and value == "node-1"
        return _receipt(bound_operation, backend)
    with patch("dingdongditch.runtime.stateful_session._execute_operation", side_effect=dispatch):
        assert runtime.commit_operation(session.session_id, prepared.token).committed


def test_concurrent_commits_have_one_dispatch_and_cross_session_tokens_do_not_confuse():
    backend = _backend()
    runtime, first_session = _runtime(backend, _policy(require_preparation_for=("click",)))
    prepared = runtime.prepare_operation(first_session.session_id, _click())
    second_backend = _backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=second_backend):
        second_session = runtime.open_session(authority_envelope=_policy(require_preparation_for=("click",)))
    assert runtime.commit_operation(second_session.session_id, prepared.token).rejection_reason is CommitRejectedReason.PREPARATION_NOT_FOUND

    entered, release = Event(), Event()
    def slow(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        return _receipt(_click(), backend)
    results: list[object] = []
    errors: list[BaseException] = []
    with patch("dingdongditch.runtime.stateful_session._execute_operation", side_effect=slow) as execute:
        one = Thread(target=lambda: results.append(runtime.commit_operation(first_session.session_id, prepared.token)))
        def second_commit() -> None:
            try:
                results.append(runtime.commit_operation(first_session.session_id, prepared.token))
            except BaseException as exc:  # the public API may fail closed busy
                errors.append(exc)
        two = Thread(target=second_commit)
        one.start(); assert entered.wait(2); two.start(); release.set(); one.join(3); two.join(3)
    assert not one.is_alive() and not two.is_alive()
    assert execute.call_count == 1
    assert [result.committed for result in results] == [True]
    assert len(errors) == 1 and isinstance(errors[0], StatefulSessionError)
    assert runtime.commit_operation(first_session.session_id, prepared.token).rejection_reason is CommitRejectedReason.ALREADY_COMMITTED


def test_handoff_preserves_exhausted_budget_and_invalidates_old_control():
    backend = _backend()
    runtime, opened = _runtime(backend, _policy(max_action_count=1), agent_id="agent-a")
    token = opened.control["control_token"]
    with patch("dingdongditch.runtime.stateful_session._execute_operation", return_value=_receipt(_navigate(), backend)):
        runtime.execute_operation(opened.session_id, _navigate(), agent_id="agent-a", control_token=token)
        checkpoint = runtime.prepare_agent_handoff(opened.session_id, agent_id="agent-a", control_token=token)
        handoff = runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "agent-b")
        rejected = runtime.execute_operation(opened.session_id, _navigate(), agent_id="agent-b", control_token=handoff.control_token)
    assert rejected.receipt.authority_decision["outcome"] == FirewallOutcome.SIDE_EFFECT_BUDGET_EXCEEDED.value
    with pytest.raises(StatefulSessionError):
        runtime.execute_operation(opened.session_id, _navigate(), agent_id="agent-a", control_token=token)


def _chain_receipt(identifier: str, *, session: str = "s") -> dict[str, object]:
    return {
        "schema_version": "1.8.0", "operation_id": identifier, "verdict": "VERIFIED", "action_type": "click",
        "target_locator": None, "target_resolution": None, "target_url": "https://allowed.example.test",
        "execution_status": "completed", "execution_error": None, "failure_kind": None,
        "action_executed_successfully": True, "action_evidence": {"dispatch": "ok"},
        "page_precondition": None, "page_transition": None, "navigation_occurred": False,
        "dispatch_document_url": "https://allowed.example.test", "authority_decision": {"policy_hash": "p"},
        "transaction": {"status": "COMMITTED"}, "quorum_verification": {"verdict": "VERIFIED"},
        "control_epoch": 1, "expectation_results": [], "freshness": {}, "expectation_evidence": [], "evidence": [],
        "artifacts": [], "runtime_version": "0.4.1",
        "browser": {"browser_session_id": session, "context_id": "c", "page_id": "p"},
    }


def test_quorum_source_spoofing_and_receipt_chain_splicing_are_detected():
    spoofed = VerificationQuorum(
        policy=VerificationPolicy.N_OF_M, required=2,
        checks=(
            VerificationCheck("dom", "one", EvidenceSourceClass.DOM_STATE),
            VerificationCheck("network-label", "two", EvidenceSourceClass.NETWORK),
        ),
    )
    with pytest.raises(ValueError, match="does not match"):
        spoofed.validate(expectation_types={"one": "element_exists", "two": "element_exists"})
    results = [
        ExpectationResult("one", "element_exists", {}, {}, "pass", [], 1, "", True, None),
        ExpectationResult("two", "element_exists", {}, {}, "pass", [], 1, "", True, None),
    ]
    quorum = evaluate_quorum(spoofed, results)
    assert quorum.verdict is Verdict.INDETERMINATE and quorum.achieved == 1

    first = chain_receipt(_chain_receipt("one", session="session-a"))
    foreign = chain_receipt(_chain_receipt("two", session="session-b"), previous_receipt_hash=first["receipt_chain"]["receipt_hash"])
    assert verify_receipt_hash(foreign)
    assert not verify_receipt_chain([first, foreign]).valid
    second = chain_receipt(_chain_receipt("two", session="session-a"), previous_receipt_hash=first["receipt_chain"]["receipt_hash"])
    assert not verify_receipt_chain([second, first]).valid
    assert not verify_receipt_chain([first, first]).valid
    # A prefix is internally valid; detecting deletion/truncation requires a
    # separately retained expected head or an independent attestation.
    assert verify_receipt_chain([first]).valid
    omitted = deepcopy(first); omitted.pop("control_epoch")
    assert not verify_receipt_hash(omitted)


def test_machine_receipt_rejects_malformed_control_epoch():
    raw = _receipt(_navigate(), _backend()).to_dict()
    raw["control_epoch"] = "not-an-epoch"
    with pytest.raises(Exception, match="control_epoch"):
        parse_execution_receipt(raw)
