from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from dingdongditch import (
    Action, ActionType, AuthorityEnvelope, CommitRejectedReason, Operation,
    ProvenanceClass, StatefulSessionError, StatefulSessionRuntime, verify_receipt_chain,
)
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.runtime.executor import _failed_receipt
from dingdongditch.contract.observation import ObservationReference


def _backend():
    backend = MagicMock()
    backend.is_started = True; backend.page_id = "page-1"; backend.page.url = "https://app.example.test/"
    backend.list_pages.return_value = [{"page_id": "page-1", "current_url": "https://app.example.test/", "active": True, "lifecycle_state": "open", "title": "App"}]
    backend.list_dialog_history.return_value = []; backend.backend_identity = "fake"; backend.browser_identity = "fake"
    backend.cleanup_errors = []
    backend.browser_environment.return_value = {"page_id": "page-1", "browser_session_id": "session", "context_id": "context"}
    backend.page.evaluate.return_value = {"url": backend.page.url, "readyState": "complete", "title": "App", "root": "<html/>"}
    return backend


def _operation() -> Operation:
    return Operation("navigate", "https://app.example.test/", Action(ActionType.NAVIGATE))


def _receipt(operation: Operation, backend) -> ExecutionReceipt:
    raw = _failed_receipt(operation=operation, started_at=1, collector=EvidenceCollector(scope_id="h", window_started_at_ms=1), locator_desc=None, execution_status="completed", execution_error="", failure_kind=None, browser=backend.browser_environment(), backend_identity="fake", browser_identity="fake", verdict=Verdict.VERIFIED)
    return replace(raw, _sealed=False, action_executed_successfully=True).seal()


def _policy(**changes):
    data = dict(policy_id="handoff-policy", granted_authorities=(ProvenanceClass.HOST_POLICY,), allowed_origins=("https://app.example.test",), allowed_action_types=("navigate",), max_action_count=3)
    data.update(changes)
    return AuthorityEnvelope(**data)


def test_hot_handoff_preserves_live_session_governance_and_receipt_chain():
    backend = _backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend), patch(
        "dingdongditch.runtime.stateful_session._execute_operation"
    ) as execute:
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=_policy(), agent_id="agent-a")
        a = opened.control
        operation = _operation()
        execute.return_value = _receipt(operation, backend)
        first = runtime.execute_operation(opened.session_id, operation, agent_id="agent-a", control_token=a["control_token"])
        checkpoint = runtime.prepare_agent_handoff(opened.session_id, agent_id="agent-a", control_token=a["control_token"])
        assert checkpoint.pages[0]["page_id"] == "page-1" and checkpoint.receipt_chain_head == first.receipt.receipt_chain["receipt_hash"]
        handoff = runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "agent-b")
        assert handoff.control_epoch == 1 and runtime.inspect_pages(opened.session_id)[0]["page_id"] == "page-1"
        with pytest.raises(StatefulSessionError):
            runtime.execute_operation(opened.session_id, operation, agent_id="agent-a", control_token=a["control_token"])
        with pytest.raises(StatefulSessionError):
            runtime.execute_operation(opened.session_id, operation, observation_reference=ObservationReference("old", "element", control_epoch=0), agent_id="agent-b", control_token=handoff.control_token)
        second = runtime.execute_operation(opened.session_id, operation, agent_id="agent-b", control_token=handoff.control_token)
        assert second.receipt.receipt_chain["previous_receipt_hash"] == first.receipt.receipt_chain["receipt_hash"]
        assert verify_receipt_chain(runtime.receipt_chain(opened.session_id)).valid
        assert runtime.get_session(opened.session_id).authority_policy["policy_hash"] == _policy().digest
        assert runtime.close_session(opened.session_id, agent_id="agent-b", control_token=handoff.control_token).status.value == "closed"
        with pytest.raises(StatefulSessionError):
            runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "agent-c")


def test_handoff_tokens_expire_and_default_policy_invalidates_pending_preparations():
    backend = _backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=_policy(require_preparation_for=("navigate",)), agent_id="agent-a")
        token = opened.control["control_token"]
        prepared = runtime.prepare_operation(opened.session_id, _operation(), agent_id="agent-a", control_token=token)
        checkpoint = runtime.prepare_agent_handoff(opened.session_id, agent_id="agent-a", control_token=token)
        handoff = runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "agent-b")
        result = runtime.commit_operation(opened.session_id, prepared.token, agent_id="agent-b", control_token=handoff.control_token)
        assert result.rejection_reason is CommitRejectedReason.PREPARATION_INVALIDATED

        checkpoint = runtime.prepare_agent_handoff(opened.session_id, agent_id="agent-b", control_token=handoff.control_token)
        runtime._records[opened.session_id].pending_handoffs[checkpoint.handoff_token]["checkpoint"] = replace(checkpoint, expires_at_ms=0)
        with pytest.raises(StatefulSessionError) as raised:
            runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "agent-c")
        assert raised.value.failure_kind.value == "handoff_token_expired"
