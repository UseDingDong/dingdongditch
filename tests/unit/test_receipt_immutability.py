from __future__ import annotations

import pytest

from dingdongditch.contract.operation import Action, ActionType, KeyPressScope, Operation
from dingdongditch.runtime.executor import execute_operation

from tests.unit.test_observation_dispatch_transaction import TransactionBackend


def test_execution_receipt_is_deeply_immutable_after_publication():
    backend = TransactionBackend(fresh=True)
    operation = Operation(
        operation_id="immutable-receipt",
        url="https://example.test",
        action=Action(
            type=ActionType.PRESS_KEY, key="A", key_scope=KeyPressScope.ACTIVE_PAGE
        ),
    )
    receipt = execute_operation(operation, backend=backend)
    with pytest.raises(TypeError):
        receipt.failure_kind = "changed"
    with pytest.raises((TypeError, AttributeError)):
        receipt.action_evidence["changed"] = True
    with pytest.raises((TypeError, AttributeError)):
        receipt.evidence.append({})
