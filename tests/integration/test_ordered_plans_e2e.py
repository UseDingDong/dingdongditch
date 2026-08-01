"""Integration tests for Milestone 2 native ordered plans."""

from __future__ import annotations

import json
from unittest.mock import patch

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
)
from dingdongditch.contract.expectation import (
    Expectation,
    ExpectationType,
    TextMatchMode,
    UrlMatchMode,
)
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.plan import (
    CompletionStatus,
    ExecutionPlan,
    FailurePolicy,
    PlanVerdict,
)
from dingdongditch.contract.target import NameMatchMode
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan


def _nav(url: str, op_id: str = "nav") -> Operation:
    return Operation(
        operation_id=op_id,
        url=url,
        action=Action(type=ActionType.NAVIGATE),
        expectations=[
            Expectation(
                type=ExpectationType.URL,
                url_value="index.html",
                url_match=UrlMatchMode.CONTAINS,
                expectation_id="url",
            )
        ],
    )


def _fill(url: str, text: str, op_id: str = "fill") -> Operation:
    return Operation(
        operation_id=op_id,
        url=url,
        action=Action(
            type=ActionType.FILL,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
            text=text,
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
                attribute_name="value",
                attribute_value=text,
                expectation_id="filled",
            )
        ],
    )


def _click_activate(url: str, op_id: str = "click") -> Operation:
    return Operation(
        operation_id=op_id,
        url=url,
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
                attribute_name="data-state",
                attribute_value="active",
                expectation_id="active",
            )
        ],
    )


def test_one_operation_plan_succeeds(fixture_url):
    plan = ExecutionPlan(
        plan_id="one-op",
        operations=[_nav(fixture_url)],
        browser_config=BrowserConfig(headless=True),
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.completion_status == CompletionStatus.COMPLETED
    assert receipt.attempted_step_count == 1
    assert receipt.skipped_step_count == 0
    assert receipt.steps[0].receipt is not None
    assert receipt.steps[0].receipt.verdict == Verdict.VERIFIED


def test_navigate_fill_click_plan_succeeds_same_session(fixture_url):
    plan = ExecutionPlan(
        plan_id="nfc",
        browser_config=BrowserConfig(headless=True),
        operations=[
            _nav(fixture_url, "p-nav"),
            _fill(fixture_url, "plan-alpha", "p-fill"),
            _click_activate(fixture_url, "p-click"),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.completion_status == CompletionStatus.COMPLETED
    assert receipt.declared_step_count == 3
    assert receipt.attempted_step_count == 3
    assert receipt.verified_step_count == 3
    assert [s.operation_id for s in receipt.steps] == ["p-nav", "p-fill", "p-click"]

    ids = {
        (
            s.browser_session_id,
            s.context_id,
            s.page_id,
        )
        for s in receipt.steps
        if s.attempted
    }
    assert len(ids) == 1
    assert receipt.browser_session_id == receipt.steps[0].browser_session_id
    assert receipt.context_id == receipt.steps[0].context_id
    assert receipt.page_id == receipt.steps[0].page_id
    # Fill persisted into later page state (indicator becomes filled then active).
    assert receipt.steps[1].receipt.verdict == Verdict.VERIFIED
    assert receipt.steps[2].receipt.verdict == Verdict.VERIFIED
    # Plan starts the session before steps; step receipts see a retained session.
    assert receipt.steps[0].receipt.browser["newly_launched"] is False
    assert receipt.steps[1].receipt.browser["newly_launched"] is False
    assert receipt.steps[2].receipt.browser["newly_launched"] is False


def test_headed_plan_succeeds(fixture_url):
    plan = ExecutionPlan(
        plan_id="headed",
        browser_config=BrowserConfig(headless=False),
        operations=[_nav(fixture_url)],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.browser["headless"] is False


def test_first_step_execution_failed_skips_rest(fixture_url):
    plan = ExecutionPlan(
        plan_id="first-fail",
        operations=[
            Operation(
                operation_id="missing",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="does-not-exist"
                    ),
                ),
                expectations=[],
                locate_retry_ms=200,
            ),
            _nav(fixture_url, "never"),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.EXECUTION_FAILED
    assert receipt.completion_status == CompletionStatus.STOPPED
    assert receipt.attempted_step_count == 1
    assert receipt.skipped_step_count == 1
    assert receipt.steps[1].skipped is True
    assert receipt.steps[1].skip_reason == "prior_step_prevented_execution"
    assert receipt.decisive_operation_id == "missing"
    assert receipt.decisive_step_index == 0


def test_middle_not_verified_stops(fixture_url):
    plan = ExecutionPlan(
        plan_id="mid-nv",
        operations=[
            _nav(fixture_url, "ok1"),
            Operation(
                operation_id="wrong-expect",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="noop-control"
                    ),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                        ),
                        attribute_name="data-state",
                        attribute_value="must-not-happen",
                        expectation_id="bad",
                    )
                ],
            ),
            _click_activate(fixture_url, "skipped"),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.NOT_VERIFIED
    assert receipt.completion_status == CompletionStatus.STOPPED
    assert receipt.steps[0].operation_verdict == Verdict.VERIFIED.value
    assert receipt.steps[1].operation_verdict == Verdict.NOT_VERIFIED.value
    assert receipt.steps[2].skipped is True
    assert receipt.decisive_operation_id == "wrong-expect"


def test_middle_ambiguous_execution_failed_stops(fixture_url):
    plan = ExecutionPlan(
        plan_id="mid-amb",
        operations=[
            _nav(fixture_url, "ok1"),
            Operation(
                operation_id="amb",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="ambiguous-target"
                    ),
                ),
                expectations=[],
            ),
            _click_activate(fixture_url, "skipped"),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.EXECUTION_FAILED
    assert receipt.steps[1].operation_verdict == Verdict.EXECUTION_FAILED.value
    assert receipt.steps[2].skipped is True


def test_middle_indeterminate_stops(fixture_url):
    plan = ExecutionPlan(
        plan_id="mid-ind",
        operations=[
            _nav(fixture_url, "ok1"),
            Operation(
                operation_id="no-expect",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="noop-control"
                    ),
                ),
                expectations=[],
            ),
            _click_activate(fixture_url, "skipped"),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.INDETERMINATE
    assert receipt.steps[1].operation_verdict == Verdict.INDETERMINATE.value
    assert receipt.steps[2].skipped is True


def test_invalid_empty_plan_id_before_launch():
    with patch(
        "dingdongditch.backends.playwright_backend.sync_playwright"
    ) as sync_pw:
        plan = ExecutionPlan(plan_id="", operations=[
            Operation(
                operation_id="x",
                url="https://example.com",
                action=Action(type=ActionType.NAVIGATE),
            )
        ])
        receipt = execute_plan(plan)
        assert receipt.completion_status == CompletionStatus.NOT_STARTED
        assert receipt.plan_verdict == PlanVerdict.EXECUTION_FAILED
        sync_pw.assert_not_called()


def test_zero_operations_before_launch():
    with patch(
        "dingdongditch.backends.playwright_backend.sync_playwright"
    ) as sync_pw:
        plan = ExecutionPlan(plan_id="empty", operations=[])
        receipt = execute_plan(plan)
        assert receipt.failure_kind == "zero_operations"
        sync_pw.assert_not_called()


def test_duplicate_operation_ids_before_launch(fixture_url):
    with patch(
        "dingdongditch.backends.playwright_backend.sync_playwright"
    ) as sync_pw:
        plan = ExecutionPlan(
            plan_id="dup",
            operations=[_nav(fixture_url, "same"), _nav(fixture_url, "same")],
        )
        receipt = execute_plan(plan)
        assert receipt.failure_kind == "duplicate_operation_ids"
        sync_pw.assert_not_called()


def test_unsupported_browser_before_launch():
    with patch(
        "dingdongditch.backends.playwright_backend.sync_playwright"
    ) as sync_pw:
        plan = ExecutionPlan(
            plan_id="ch",
            browser_config=BrowserConfig(channel=BrowserChannel.CHROME),
            operations=[
                Operation(
                    operation_id="n",
                    url="https://example.com",
                    action=Action(type=ActionType.NAVIGATE),
                )
            ],
        )
        receipt = execute_plan(plan)
        assert receipt.completion_status == CompletionStatus.NOT_STARTED
        assert receipt.plan_verdict == PlanVerdict.EXECUTION_FAILED
        sync_pw.assert_not_called()


def test_plan_receipt_serializes(fixture_url):
    plan = ExecutionPlan(
        plan_id="ser",
        operations=[_nav(fixture_url)],
    )
    receipt = execute_plan(plan)
    payload = receipt.to_dict()
    encoded = json.dumps(payload, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["schema_version"] == "2.2.0"
    assert decoded["plan_verdict"] == "VERIFIED"
    assert decoded["steps"][0]["receipt"]["verdict"] == "VERIFIED"


def test_standalone_still_works_alongside_plans(fixture_url):
    solo = execute_operation(_nav(fixture_url, "solo"))
    assert solo.verdict == Verdict.VERIFIED
    plan = execute_plan(
        ExecutionPlan(plan_id="with-solo", operations=[_nav(fixture_url, "in-plan")])
    )
    assert plan.plan_verdict == PlanVerdict.VERIFIED


def test_constrained_locator_inside_plan(fixture_url):
    plan = ExecutionPlan(
        plan_id="constrained",
        operations=[
            _nav(fixture_url, "n"),
            Operation(
                operation_id="role-click",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=Locator(
                        strategy=LocatorStrategy.ROLE_NAME,
                        role="button",
                        name="Activate Target",
                        name_match=NameMatchMode.EXACT,
                    ),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="target-control"
                        ),
                        attribute_name="data-state",
                        attribute_value="active",
                    )
                ],
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.steps[1].receipt.target_resolution is not None


def test_fill_state_persists_into_later_expectation(fixture_url):
    plan = ExecutionPlan(
        plan_id="persist",
        operations=[
            _nav(fixture_url, "n"),
            _fill(fixture_url, "persist-me", "f"),
            Operation(
                operation_id="check-indicator",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="noop-control"
                    ),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.TEXT,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                        ),
                        text_value="filled",
                        text_match=TextMatchMode.EXACT,
                    )
                ],
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED


def test_cleanup_after_success_and_failure(fixture_url):
    backend = PlaywrightBackend(browser_config=BrowserConfig(headless=True))
    # Plan-owned path: owns and stops.
    r_ok = execute_plan(
        ExecutionPlan(plan_id="clean-ok", operations=[_nav(fixture_url)])
    )
    assert r_ok.plan_verdict == PlanVerdict.VERIFIED

    r_fail = execute_plan(
        ExecutionPlan(
            plan_id="clean-fail",
            operations=[
                Operation(
                    operation_id="miss",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.CLICK,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="nope"
                        ),
                    ),
                    expectations=[],
                    locate_retry_ms=100,
                )
            ],
        )
    )
    assert r_fail.plan_verdict == PlanVerdict.EXECUTION_FAILED

    # External backend still usable after plan-owned runs.
    backend.start()
    try:
        assert backend.is_started
    finally:
        backend.stop()
        assert backend.is_started is False


def test_failure_policy_default_is_stop_on_failure():
    plan = ExecutionPlan(
        plan_id="pol",
        operations=[
            Operation(
                operation_id="a",
                url="https://example.com",
                action=Action(type=ActionType.NAVIGATE),
            )
        ],
    )
    assert plan.failure_policy == FailurePolicy.STOP_ON_FAILURE


def test_browser_start_once_for_multi_step_plan(fixture_url):
    real_start = PlaywrightBackend.start
    launches = {"count": 0}

    def counting_start(self):
        was_cold = not (self._started and self._page is not None)
        result = real_start(self)
        if was_cold:
            launches["count"] += 1
        return result

    with patch.object(PlaywrightBackend, "start", counting_start):
        receipt = execute_plan(
            ExecutionPlan(
                plan_id="once",
                browser_config=BrowserConfig(headless=True),
                operations=[
                    _nav(fixture_url, "a"),
                    _fill(fixture_url, "once", "b"),
                    _click_activate(fixture_url, "c"),
                ],
            )
        )
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert launches["count"] == 1


def test_skipped_steps_do_not_dispatch_actions(fixture_url):
    real_dispatch = PlaywrightBackend.dispatch
    dispatched_ops: list[str] = []

    def counting_dispatch(self, operation, *args, **kwargs):
        dispatched_ops.append(operation.operation_id)
        return real_dispatch(self, operation, *args, **kwargs)

    with patch.object(PlaywrightBackend, "dispatch", counting_dispatch):
        receipt = execute_plan(
            ExecutionPlan(
                plan_id="no-skip-dispatch",
                operations=[
                    Operation(
                        operation_id="miss",
                        url=fixture_url,
                        action=Action(
                            type=ActionType.CLICK,
                            locator=Locator(
                                strategy=LocatorStrategy.TEST_ID, value="nope"
                            ),
                        ),
                        expectations=[],
                        locate_retry_ms=100,
                    ),
                    _click_activate(fixture_url, "skipped-click"),
                ],
            )
        )
    assert receipt.steps[1].skipped is True
    # Attempted step may enter dispatch (and fail closed); skipped step must not.
    assert "miss" in dispatched_ops
    assert "skipped-click" not in dispatched_ops


def test_unexpected_step_exception_preserves_prior_and_skips(fixture_url):
    real_exec = execute_operation
    calls = {"n": 0}

    def flaky(operation, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated step crash")
        return real_exec(operation, **kwargs)

    with patch(
        "dingdongditch.runtime.plan_executor.execute_operation",
        side_effect=flaky,
    ):
        receipt = execute_plan(
            ExecutionPlan(
                plan_id="crash",
                operations=[
                    _nav(fixture_url, "ok"),
                    _fill(fixture_url, "x", "crash-here"),
                    _click_activate(fixture_url, "skipped"),
                ],
            )
        )
    assert receipt.completion_status == CompletionStatus.STOPPED
    assert receipt.steps[0].attempted and receipt.steps[0].receipt is not None
    assert receipt.steps[0].operation_verdict == Verdict.VERIFIED.value
    assert receipt.steps[1].attempted
    assert receipt.steps[1].receipt is None
    assert receipt.steps[2].skipped is True
    assert "RuntimeError" in (receipt.execution_error or "")
