from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from dingdongditch.contract.operation import (
    Action,
    ActionType,
    KeyPressScope,
    Operation,
)
from dingdongditch.runtime.executor import execute_operation


class TransactionBackend:
    def __init__(self, *, fresh: bool) -> None:
        self.fresh = fresh
        self.dispatched = False
        self.is_started = True
        self.browser_config = SimpleNamespace(describe=lambda: {})
        self.backend_identity = "test"
        self.browser_identity = "test"
        self.browser_session_id = "session"
        self.page_id = "page"
        self.page = SimpleNamespace(url="https://example.test")
        self.telemetry = []

    def exclusive_use(self, scope):
        return nullcontext()

    def mark_session_reused(self):
        pass

    def browser_environment(self):
        return {}

    def _same_document_url(self, actual, expected):
        return actual == expected

    def observe(self, collector):
        return SimpleNamespace(collected_at_ms=1, url=self.page.url)

    def validate_observation_reference(self, reference):
        return SimpleNamespace(
            fresh=self.fresh,
            reason="fresh" if self.fresh else "changed",
            to_dict=lambda: {"fresh": self.fresh},
        )

    def dispatch(self, operation, **kwargs):
        self.dispatched = True
        if not self.fresh:
            raise AssertionError("dispatch should not occur for a stale reference")
        return SimpleNamespace(
            started_at_ms=2,
            completed_at_ms=3,
            ok=True,
            error=None,
            failure_kind=None,
            action_evidence={"dispatched": True},
            resolution_trace=None,
            recovery_attempts=[],
        )

    def capture_screenshot(self, **kwargs):
        return {"artifact": "test.png"}


def test_stale_observation_cannot_reach_dispatch():
    backend = TransactionBackend(fresh=False)
    operation = Operation(
        operation_id="transaction-test",
        url="https://example.test",
        action=Action(
            type=ActionType.PRESS_KEY,
            key="A",
            key_scope=KeyPressScope.ACTIVE_PAGE,
        ),
    )
    receipt = execute_operation(
        operation,
        backend=backend,
        observation_reference=object(),
    )
    assert receipt.failure_kind == "stale_observation_reference", receipt.execution_error
    assert receipt.action_evidence["dispatch_attempted"] is False
    assert backend.dispatched is False


def test_successful_dispatch_receipt_attests_bound_observation_transaction():
    backend = TransactionBackend(fresh=True)
    operation = Operation(
        operation_id="transaction-success",
        url="https://example.test",
        action=Action(
            type=ActionType.PRESS_KEY,
            key="A",
            key_scope=KeyPressScope.ACTIVE_PAGE,
        ),
    )
    receipt = execute_operation(
        operation, backend=backend, observation_reference=object()
    )
    assert backend.dispatched is True
    assert receipt.failure_kind is None, receipt.execution_error
    assert receipt.action_evidence["observation_transaction"] == {"fresh": True}, (
        receipt.execution_error
    )
