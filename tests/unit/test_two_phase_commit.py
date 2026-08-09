from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

from dingdongditch import (
    Action, ActionType, AuthorityEnvelope, CommitRejectedReason, Locator,
    LocatorStrategy, Operation, ProvenanceClass, StatefulSessionRuntime,
)
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.runtime.executor import _failed_receipt


def _operation(*, text: str | None = None, click: bool = False) -> Operation:
    if click:
        return Operation("send", "https://shop.example.test/form", Action(ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "send")))
    return Operation("send", "https://shop.example.test/form", Action(ActionType.NAVIGATE if text is None else ActionType.FILL, locator=(Locator(LocatorStrategy.TEST_ID, "message") if text is not None else None), text=text))


def _policy(**changes) -> AuthorityEnvelope:
    base = dict(
        policy_id="transaction-host-policy",
        granted_authorities=(ProvenanceClass.HOST_POLICY,),
        allowed_origins=("https://shop.example.test",),
        allowed_action_types=("navigate", "fill", "click"),
        require_preparation_for=("navigate", "fill", "click"),
    )
    base.update(changes)
    return AuthorityEnvelope(**base)


def _backend():
    backend = MagicMock()
    backend.is_started = True
    backend.page_id = "page-1"
    backend.page.url = "https://shop.example.test/form"
    backend.page.evaluate.return_value = {"url": backend.page.url, "readyState": "complete", "title": "form", "root": "<html>one</html>"}
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True}]
    backend.list_dialog_history.return_value = []
    backend.backend_identity = "fake"
    backend.browser_identity = "fake"
    backend.browser_environment.return_value = {"page_id": "page-1", "browser_session_id": "fake"}
    backend.read_element_state.return_value = {"exists": True, "ambiguous": False, "text": "Send"}
    return backend


def _executed_receipt(operation: Operation, backend, *, verdict: Verdict = Verdict.VERIFIED) -> ExecutionReceipt:
    receipt = _failed_receipt(
        operation=operation, started_at=1, collector=EvidenceCollector(scope_id="test", window_started_at_ms=1),
        locator_desc=None, execution_status="completed", execution_error="", failure_kind=None,
        browser=backend.browser_environment(), backend_identity="fake", browser_identity="fake", verdict=verdict,
    )
    return replace(receipt, _sealed=False, action_executed_successfully=True).seal()


def _runtime_with_backend(backend):
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        session = runtime.open_session(authority_envelope=_policy())
    return runtime, session


def test_prepare_then_commit_once_with_payload_binding_and_post_verification():
    backend = _backend()
    runtime, session = _runtime_with_backend(backend)
    operation = _operation(text="send this")
    prepared = runtime.prepare_operation(session.session_id, operation)
    assert prepared.token and prepared.operation_hash
    with patch("dingdongditch.runtime.stateful_session._execute_operation", return_value=_executed_receipt(operation, backend)) as execute:
        committed = runtime.commit_operation(session.session_id, prepared.token, operation=operation)
    assert committed.committed and committed.receipt.transaction["status"] == "COMMITTED"
    execute.assert_called_once()
    assert runtime.commit_operation(session.session_id, prepared.token).rejection_reason is CommitRejectedReason.ALREADY_COMMITTED

    prepared = runtime.prepare_operation(session.session_id, operation)
    altered = _operation(text="substituted")
    assert runtime.commit_operation(session.session_id, prepared.token, operation=altered).rejection_reason is CommitRejectedReason.PAYLOAD_CHANGED

    prepared = runtime.prepare_operation(session.session_id, operation)
    with patch("dingdongditch.runtime.stateful_session._execute_operation", return_value=_executed_receipt(operation, backend, verdict=Verdict.NOT_VERIFIED)):
        committed = runtime.commit_operation(session.session_id, prepared.token)
    assert committed.committed and committed.receipt.verdict is Verdict.NOT_VERIFIED


def test_commit_rejects_expiry_and_material_browser_changes():
    backend = _backend()
    runtime, session = _runtime_with_backend(backend)
    operation = _operation(click=True)
    backend.read_element_state.return_value = {"exists": True, "ambiguous": False, "text": "Send"}

    prepared = runtime.prepare_operation(session.session_id, operation)
    backend.page.evaluate.return_value = {"url": backend.page.url, "readyState": "complete", "title": "form", "root": "<html>changed</html>"}
    assert runtime.commit_operation(session.session_id, prepared.token).rejection_reason is CommitRejectedReason.PREPARED_STATE_CHANGED

    backend = _backend(); runtime, session = _runtime_with_backend(backend); backend.read_element_state.return_value = {"exists": True, "ambiguous": False, "text": "Send"}
    prepared = runtime.prepare_operation(session.session_id, operation)
    backend.read_element_state.return_value = {"exists": True, "ambiguous": False, "text": "Different"}
    assert runtime.commit_operation(session.session_id, prepared.token).rejection_reason is CommitRejectedReason.TARGET_CHANGED

    backend = _backend(); runtime, session = _runtime_with_backend(backend); prepared = runtime.prepare_operation(session.session_id, _operation())
    backend.page.url = "https://other.example.test/form"
    assert runtime.commit_operation(session.session_id, prepared.token).rejection_reason is CommitRejectedReason.ORIGIN_CHANGED

    backend = _backend(); runtime, session = _runtime_with_backend(backend); prepared = runtime.prepare_operation(session.session_id, _operation())
    backend.page_id = "page-2"
    assert runtime.commit_operation(session.session_id, prepared.token).rejection_reason is CommitRejectedReason.PAGE_CHANGED

    backend = _backend(); runtime, session = _runtime_with_backend(backend); prepared = runtime.prepare_operation(session.session_id, _operation())
    runtime._records[session.session_id].preparations[prepared.token].public = replace(prepared, expires_at_ms=0)
    assert runtime.commit_operation(session.session_id, prepared.token).rejection_reason is CommitRejectedReason.PREPARATION_EXPIRED


def test_commit_rechecks_authority_and_direct_consequential_dispatch_is_rejected():
    backend = _backend(); runtime, session = _runtime_with_backend(backend); operation = _operation()
    direct = runtime.execute_operation(session.session_id, operation)
    assert direct.receipt.execution_status == "preparation_required"
    prepared = runtime.prepare_operation(session.session_id, operation)
    runtime._records[session.session_id].authority_envelope = _policy(policy_id="replacement")
    assert runtime.commit_operation(session.session_id, prepared.token).rejection_reason is CommitRejectedReason.AUTHORITY_CHANGED
