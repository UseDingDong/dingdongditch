"""Chromium stabilization: repeated plans, ownership, invariants, cleanup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserChannel, BrowserConfig, BrowserEngine
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
            )
        ],
    )


def _click(url: str, op_id: str = "click") -> Operation:
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
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="target-control"
                ),
                attribute_name="data-state",
                attribute_value="active",
            )
        ],
    )


def _success_plan(url: str, plan_id: str, *, headless: bool = True) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id=plan_id,
        browser_config=BrowserConfig(headless=headless),
        operations=[
            _nav(url, f"{plan_id}-nav"),
            _fill(url, plan_id, f"{plan_id}-fill"),
            _click(url, f"{plan_id}-click"),
        ],
    )


def test_ten_sequential_owned_plans_no_leaked_ids(fixture_url):
    ids = []
    for i in range(10):
        r = execute_plan(_success_plan(fixture_url, f"seq-{i}"))
        assert r.plan_verdict == PlanVerdict.VERIFIED
        r.check_invariants()
        assert r.completion_status == CompletionStatus.COMPLETED
        assert r.decisive_step_index is None
        assert r.skipped_step_count == 0
        ids.append((r.browser_session_id, r.context_id, r.page_id))
    # Each owned plan gets distinct session/context/page IDs.
    assert len(set(ids)) == 10
    assert all(all(x is not None for x in triple) for triple in ids)


def test_success_after_stopped_and_stopped_after_success(fixture_url):
    fail = execute_plan(
        ExecutionPlan(
            plan_id="stop-first",
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
                _nav(fixture_url, "skipped"),
            ],
        )
    )
    assert fail.completion_status == CompletionStatus.STOPPED
    fail.check_invariants()

    ok = execute_plan(_success_plan(fixture_url, "after-stop"))
    assert ok.plan_verdict == PlanVerdict.VERIFIED
    ok.check_invariants()

    fail2 = execute_plan(
        ExecutionPlan(
            plan_id="stop-after-ok",
            operations=[
                _nav(fixture_url, "ok"),
                Operation(
                    operation_id="bad-expect",
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
                                strategy=LocatorStrategy.TEST_ID,
                                value="state-indicator",
                            ),
                            attribute_name="data-state",
                            attribute_value="impossible",
                        )
                    ],
                ),
                _click(fixture_url, "skip"),
            ],
        )
    )
    assert fail2.plan_verdict == PlanVerdict.NOT_VERIFIED
    assert fail2.decisive_operation_id == "bad-expect"
    fail2.check_invariants()


def test_injected_backend_reuse_preserves_ids_and_is_not_closed(fixture_url):
    backend = PlaywrightBackend(browser_config=BrowserConfig(headless=True))
    backend.start()
    try:
        sid, cid, pid = (
            backend.browser_session_id,
            backend.context_id,
            backend.page_id,
        )
        r1 = execute_plan(
            ExecutionPlan(
                plan_id="inject-1",
                operations=[_nav(fixture_url, "n1")],
            ),
            backend=backend,
        )
        r2 = execute_plan(
            ExecutionPlan(
                plan_id="inject-2",
                operations=[_fill(fixture_url, "shared", "f2")],
            ),
            backend=backend,
        )
        assert r1.plan_verdict == PlanVerdict.VERIFIED
        assert r2.plan_verdict == PlanVerdict.VERIFIED
        assert r1.browser_session_id == sid == r2.browser_session_id
        assert r1.context_id == cid == r2.context_id
        assert r1.page_id == pid == r2.page_id
        assert backend.is_started is True
    finally:
        backend.stop()
        assert backend.is_started is False


def test_headed_headless_parity(fixture_url):
    hless = execute_plan(_success_plan(fixture_url, "parity-less", headless=True))
    headed = execute_plan(_success_plan(fixture_url, "parity-hed", headless=False))
    assert hless.plan_verdict == headed.plan_verdict == PlanVerdict.VERIFIED
    assert hless.completion_status == headed.completion_status
    assert hless.verified_step_count == headed.verified_step_count == 3
    assert hless.browser["headless"] is True
    assert headed.browser["headless"] is False
    hless.check_invariants()
    headed.check_invariants()


def test_page_id_stable_through_navigate_fill_click(fixture_url):
    r = execute_plan(_success_plan(fixture_url, "stable-page"))
    pages = {s.page_id for s in r.steps if s.attempted}
    assert len(pages) == 1
    assert r.page_id in pages


def test_url_and_fill_persist_across_steps(fixture_url):
    r = execute_plan(
        ExecutionPlan(
            plan_id="persist-state",
            operations=[
                _nav(fixture_url, "n"),
                _fill(fixture_url, "keep-me", "f"),
                Operation(
                    operation_id="check",
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
                                strategy=LocatorStrategy.TEST_ID,
                                value="state-indicator",
                            ),
                            text_value="filled",
                            text_match=TextMatchMode.EXACT,
                        )
                    ],
                ),
            ],
        )
    )
    assert r.plan_verdict == PlanVerdict.VERIFIED
    assert "index.html" in (r.steps[0].receipt.post_action_observation.url or "")


def test_constraint_resolution_same_in_plan_and_standalone(fixture_url):
    loc = Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Activate Target",
        name_match=NameMatchMode.EXACT,
    )
    op = Operation(
        operation_id="role-click",
        url=fixture_url,
        action=Action(type=ActionType.CLICK, locator=loc),
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
    )
    # Standalone needs prior navigate on shared backend.
    backend = PlaywrightBackend(browser_config=BrowserConfig(headless=True))
    backend.start()
    try:
        execute_operation(_nav(fixture_url, "pre"), backend=backend)
        solo = execute_operation(op, backend=backend)
    finally:
        backend.stop()

    plan = execute_plan(
        ExecutionPlan(
            plan_id="constrained-plan",
            operations=[_nav(fixture_url, "n"), op],
        )
    )
    assert solo.verdict == Verdict.VERIFIED
    assert plan.plan_verdict == PlanVerdict.VERIFIED
    assert solo.target_resolution is not None
    assert plan.steps[1].receipt.target_resolution is not None


def test_receipt_invariants_on_success_and_stop(fixture_url):
    ok = execute_plan(_success_plan(fixture_url, "inv-ok"))
    ok.check_invariants()
    assert ok.decisive_step_index is None
    assert ok.skipped_step_count == 0

    stopped = execute_plan(
        ExecutionPlan(
            plan_id="inv-stop",
            operations=[
                _nav(fixture_url, "a"),
                Operation(
                    operation_id="ind",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.CLICK,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="noop-control"
                        ),
                    ),
                    expectations=[],
                ),
                _click(fixture_url, "c"),
            ],
        )
    )
    stopped.check_invariants()
    assert stopped.plan_verdict == PlanVerdict.INDETERMINATE
    assert stopped.decisive_step_index == 1
    assert stopped.steps[2].skipped is True


def test_cleanup_idempotent_start_stop(fixture_url):
    backend = PlaywrightBackend(browser_config=BrowserConfig(headless=True))
    backend.start()
    backend.start()  # idempotent
    assert backend.is_started
    backend.stop()
    backend.stop()  # idempotent
    assert backend.is_started is False
    # Fresh owned plan after stop still works.
    r = execute_plan(_success_plan(fixture_url, "after-idempotent"))
    assert r.plan_verdict == PlanVerdict.VERIFIED


def test_validation_failures_never_start_playwright():
    with patch(
        "dingdongditch.backends.playwright_backend.sync_playwright"
    ) as sync_pw:
        for plan in [
            ExecutionPlan(plan_id="", operations=[_nav("https://example.com")]),
            ExecutionPlan(plan_id="z", operations=[]),
            ExecutionPlan(
                plan_id="d",
                operations=[
                    _nav("https://example.com", "same"),
                    _nav("https://example.com", "same"),
                ],
            ),
            ExecutionPlan(
                plan_id="ch",
                browser_config=BrowserConfig(channel=BrowserChannel.CHROME),
                operations=[_nav("https://example.com")],
            ),
        ]:
            r = execute_plan(plan)
            assert r.completion_status == CompletionStatus.NOT_STARTED
            r.check_invariants()
        sync_pw.assert_not_called()


def test_unexpected_exception_no_retry(fixture_url):
    real = execute_operation
    calls = {"n": 0}

    def flaky(operation, **kwargs):
        calls["n"] += 1
        if operation.operation_id == "boom":
            raise RuntimeError("boom once")
        return real(operation, **kwargs)

    with patch(
        "dingdongditch.runtime.plan_executor.execute_operation", side_effect=flaky
    ):
        r = execute_plan(
            ExecutionPlan(
                plan_id="no-retry",
                operations=[
                    _nav(fixture_url, "ok"),
                    _fill(fixture_url, "x", "boom"),
                    _click(fixture_url, "later"),
                ],
            )
        )
    assert calls["n"] == 2  # nav + boom only; no retry of boom
    assert r.steps[0].receipt is not None
    assert r.steps[2].skipped is True
    r.check_invariants()
