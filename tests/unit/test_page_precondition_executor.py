from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dingdongditch.backends.playwright_backend import (
    ActionDispatchResult,
    PageObservation,
    PlaywrightBackend,
)
from dingdongditch.contract.browser import BrowserConfig
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.page_precondition import (
    PageCondition,
    PageConditionType,
    PagePrecondition,
)
from dingdongditch.runtime.executor import execute_operation


def explicit_exact(expected="https://example.test/page"):
    return PagePrecondition(
        (
            PageCondition(
                condition_id="exact",
                type=PageConditionType.EXACT_URL,
                url_value=expected,
            ),
        )
    )


def operation(precondition):
    return Operation(
        operation_id="escape",
        url="https://example.test/canonical-reference",
        action=Action(
            type=ActionType.PRESS_KEY,
            key="Escape",
            key_scope=KeyPressScope.ACTIVE_PAGE,
        ),
        page_precondition=precondition,
    )


def backend(url="https://example.test/page"):
    item = MagicMock(spec=PlaywrightBackend)
    item.browser_config = BrowserConfig()
    item.is_started = True
    item.backend_identity = "playwright-sync"
    item.browser_identity = "chromium"
    item.page = SimpleNamespace(url=url)
    item.telemetry = []
    item.browser_environment.return_value = {"engine": "chromium"}
    item.observe.side_effect = [
        PageObservation(10, url, "", []),
        PageObservation(20, url, "", []),
    ]
    item.dispatch.return_value = ActionDispatchResult(
        ok=True,
        error=None,
        started_at_ms=11,
        completed_at_ms=12,
        action_evidence={"dispatched": True},
    )
    return item


def test_all_conditions_pass_then_action_dispatches_once():
    item = backend()
    receipt = execute_operation(operation(explicit_exact()), backend=item)
    item.dispatch.assert_called_once()
    assert receipt.page_precondition["mode"] == "explicit_conditions"
    assert receipt.page_precondition["result"] == "pass"


def test_failed_condition_blocks_observation_and_dispatch():
    item = backend()
    receipt = execute_operation(
        operation(explicit_exact("https://example.test/other")), backend=item
    )
    item.observe.assert_not_called()
    item.dispatch.assert_not_called()
    assert receipt.failure_kind == "page_precondition_mismatch"
    assert receipt.page_precondition["result"] == "fail"


def test_indeterminate_dom_condition_blocks_dispatch():
    item = backend()
    item.read_element_state.return_value = {
        "match_count": 2,
        "exists": True,
        "ambiguous": True,
    }
    precondition = PagePrecondition(
        (
            PageCondition(
                condition_id="landmark",
                type=PageConditionType.ELEMENT_VISIBLE,
                locator=Locator(strategy=LocatorStrategy.CSS, value="#x"),
            ),
        )
    )
    receipt = execute_operation(operation(precondition), backend=item)
    item.dispatch.assert_not_called()
    assert receipt.failure_kind == "page_precondition_indeterminate"
    assert receipt.page_precondition["result"] == "indeterminate"


def test_evaluator_error_blocks_dispatch_fail_closed():
    item = backend()
    with patch(
        "dingdongditch.runtime.executor.evaluate_page_precondition",
        side_effect=RuntimeError("broken evaluator"),
    ):
        receipt = execute_operation(operation(explicit_exact()), backend=item)
    item.dispatch.assert_not_called()
    assert receipt.failure_kind == "page_precondition_indeterminate"
    assert receipt.page_precondition["result"] == "indeterminate"
    assert [
        result["condition_id"]
        for result in receipt.page_precondition["condition_results"]
    ] == ["exact"]


def test_legacy_receipt_fields_keep_original_meanings():
    item = backend()
    item._same_document_url.side_effect = PlaywrightBackend._same_document_url
    legacy = operation(None)
    legacy.url = "https://example.test/page#expected"
    item.page = SimpleNamespace(url="https://example.test/page#actual")
    receipt = execute_operation(legacy, backend=item)
    assert receipt.page_precondition["mode"] == "legacy_exact_url"
    assert receipt.page_precondition["expected_url"] == legacy.url
    assert receipt.page_precondition["actual_url"] == item.page.url
    assert receipt.page_precondition["matched"] is True
    assert receipt.page_precondition["fragment_differences_ignored"] is True
