"""Deterministic local demonstration of all execution-governance capabilities.

This deliberately uses a local in-memory browser fixture, not an AI SDK or a
network service. It demonstrates ownership and evidence boundaries; replace
the fixture with a real retained session in a host integration.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

from dingdongditch import (
    Action, ActionType, AuthorityEnvelope, EvidenceSourceClass,
    Locator, LocatorStrategy, Operation, ProvenanceClass, StatefulSessionRuntime, VerificationCheck,
    VerificationPolicy, VerificationQuorum, evaluate_quorum, verify_receipt_chain,
)
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.models import ExpectationResult
from dingdongditch.runtime.executor import _failed_receipt


def _fixture_backend() -> MagicMock:
    backend = MagicMock()
    backend.is_started = True; backend.page_id = "page-local"; backend.page.url = "https://local.example.test/form"
    backend.page.evaluate.return_value = {"url": backend.page.url, "readyState": "complete", "title": "Local form", "root": "<form/>"}
    backend.list_pages.return_value = [{"page_id": "page-local", "current_url": backend.page.url, "title": "Local form", "active": True, "lifecycle_state": "open"}]
    backend.list_dialog_history.return_value = []; backend.cleanup_errors = []
    backend.backend_identity = "local-fixture"; backend.browser_identity = "local-fixture"
    backend.browser_environment.return_value = {"page_id": "page-local", "browser_session_id": "local-session", "context_id": "local-context"}
    return backend


def _verified_receipt(operation: Operation, backend, quorum: dict) -> ExecutionReceipt:
    raw = _failed_receipt(
        operation=operation, started_at=1, collector=EvidenceCollector(scope_id=operation.operation_id, window_started_at_ms=1),
        locator_desc=None, execution_status="completed", execution_error="", failure_kind=None,
        browser=backend.browser_environment(), backend_identity="local-fixture", browser_identity="local-fixture", verdict=Verdict.VERIFIED,
    )
    return replace(raw, _sealed=False, action_executed_successfully=True, quorum_verification=quorum).seal()


def run_demo() -> dict[str, object]:
    """Run locally and return a deterministic security-relevant summary."""
    backend = _fixture_backend()
    policy = AuthorityEnvelope(
        policy_id="local-demo-policy",
        granted_authorities=(ProvenanceClass.HOST_POLICY,),
        allowed_origins=("https://local.example.test",),
        allowed_action_types=("fill", "navigate"),
        irreversible_action_types=("navigate",),
        require_preparation_for=("navigate",),
        transfer_prepared_operations=True,
        max_action_count=3,
    )
    quorum = VerificationQuorum(
        policy=VerificationPolicy.ALL,
        checks=(
            VerificationCheck("dom", "dom", EvidenceSourceClass.DOM_STATE),
            VerificationCheck("network", "network", EvidenceSourceClass.NETWORK),
        ),
    )
    quorum_result = evaluate_quorum(quorum, [
        ExpectationResult("dom", "element_visible", {}, {}, "pass", ["dom-evidence"], 1, "pass", True),
        ExpectationResult("network", "network", {}, {}, "pass", ["network-evidence"], 1, "pass", True),
    ]).to_dict()
    fill = Operation("fill", "https://local.example.test/form", Action(ActionType.FILL, text="hello", locator=Locator(LocatorStrategy.TEST_ID, "message")))
    # The fixture bypasses browser dispatch but governance still controls the session.
    final = Operation("submit", "https://local.example.test/form", Action(ActionType.NAVIGATE), verification_quorum=quorum)
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend), patch(
        "dingdongditch.runtime.stateful_session._execute_operation"
    ) as execute:
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=policy, agent_id="planner-a")
        a_token = opened.control["control_token"]
        execute.side_effect = lambda operation, **_: _verified_receipt(operation, backend, quorum_result)
        runtime.execute_operation(opened.session_id, fill, agent_id="planner-a", control_token=a_token)
        prepared = runtime.prepare_operation(opened.session_id, final, agent_id="planner-a", control_token=a_token)
        checkpoint = runtime.prepare_agent_handoff(opened.session_id, agent_id="planner-a", control_token=a_token)
        handoff = runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "planner-b")
        old_agent_rejected = False
        try:
            runtime.execute_operation(opened.session_id, fill, agent_id="planner-a", control_token=a_token)
        except Exception:
            old_agent_rejected = True
        committed = runtime.commit_operation(opened.session_id, prepared.token, agent_id="planner-b", control_token=handoff.control_token)
        chain_ok = verify_receipt_chain(runtime.receipt_chain(opened.session_id)).valid
        pages = runtime.inspect_pages(opened.session_id)
        runtime.close_session(opened.session_id, agent_id="planner-b", control_token=handoff.control_token)
    return {
        "same_page_preserved": pages[0]["page_id"] == "page-local",
        "old_agent_rejected": old_agent_rejected,
        "commit_succeeded": committed.committed,
        "quorum_verdict": committed.receipt.quorum_verification["verdict"],
        "receipt_chain_valid": chain_ok,
        "handoff_epoch": handoff.control_epoch,
    }


if __name__ == "__main__":
    print(run_demo())
