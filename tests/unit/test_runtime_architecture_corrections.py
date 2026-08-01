from unittest.mock import MagicMock

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserConfig, BrowserEngine
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.wait import WaitCondition, WaitConditionType
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.plan_builder import PlanBuilder
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan


def test_supplied_backend_configuration_mismatch_does_not_start_or_stop():
    backend = PlaywrightBackend(BrowserConfig(engine=BrowserEngine.CHROMIUM))
    backend.start = MagicMock()
    backend.stop = MagicMock()
    plan = ExecutionPlan(
        plan_id="mismatch",
        browser_config=BrowserConfig(engine=BrowserEngine.FIREFOX),
        operations=[
            Operation(
                operation_id="nav",
                url="http://fixture.invalid/",
                action=Action(type=ActionType.NAVIGATE),
            )
        ],
    )
    receipt = execute_plan(plan, backend=backend)
    assert receipt.failure_kind == "contradictory_browser_config"
    backend.start.assert_not_called()
    backend.stop.assert_not_called()


def test_non_navigation_page_mismatch_never_dispatches_or_navigates():
    backend = MagicMock(spec=PlaywrightBackend)
    backend.browser_config = BrowserConfig()
    backend.is_started = True
    backend.backend_identity = "playwright-sync"
    backend.browser_identity = "chromium"
    backend.page.url = "http://fixture.invalid/actual"
    backend._same_document_url.side_effect = PlaywrightBackend._same_document_url
    backend.browser_environment.return_value = {"engine": "chromium"}
    op = Operation(
        operation_id="click",
        url="http://fixture.invalid/expected",
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.CSS, value="#target"),
        ),
    )
    receipt = execute_operation(op, backend=backend)
    assert receipt.failure_kind == "page_precondition_mismatch"
    assert receipt.navigation_occurred is False
    backend.dispatch.assert_not_called()
    backend.ensure_on_url.assert_not_called()


def test_fragment_difference_is_same_document():
    assert PlaywrightBackend._same_document_url(
        "http://fixture.invalid/page#after", "http://fixture.invalid/page#before"
    )


def test_evidence_identity_is_collector_scoped_and_bounded():
    a = EvidenceCollector("plan-a/op")
    b = EvidenceCollector("plan-b/op")
    assert a.scope_id != b.scope_id
    assert a.max_signals == 512


def test_plan_builder_emits_typed_plan_without_planning():
    locator = Locator(strategy=LocatorStrategy.CSS, value="#target")
    plan = (
        PlanBuilder("built")
        .navigate("nav", "http://fixture.invalid/")
        .click("click", "http://fixture.invalid/", locator)
        .build()
    )
    assert [op.action.type for op in plan.operations] == [
        ActionType.NAVIGATE,
        ActionType.CLICK,
    ]


def test_looping_media_contracts_validate_as_explicit_waits():
    locator = Locator(strategy=LocatorStrategy.CSS, value="video")
    for kind in (
        WaitConditionType.VIDEO_PLAYING,
        WaitConditionType.VIDEO_COMPLETED_ONCE,
    ):
        WaitCondition(type=kind, locator=locator).validate()
