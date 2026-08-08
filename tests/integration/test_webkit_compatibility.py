"""WebKit compatibility + lifecycle (real Playwright-bundled WebKit)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dingdongditch.backends.playwright_backend import (
    PlaywrightBackend,
    launch_playwright_browser,
)
from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
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
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.plan import (
    CompletionStatus,
    ExecutionPlan,
    PlanVerdict,
)
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan

ENGINE = BrowserEngine.WEBKIT


def _cfg(*, headless: bool = True) -> BrowserConfig:
    return BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=ENGINE,
        channel=BrowserChannel.BUNDLED,
        headless=headless,
    )


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
        browser_config=_cfg(headless=headless),
        operations=[
            _nav(url, f"{plan_id}-nav"),
            _fill(url, plan_id, f"{plan_id}-fill"),
            _click(url, f"{plan_id}-click"),
        ],
    )


def test_webkit_config_and_metadata(fixture_url):
    r = execute_operation(_nav(fixture_url), browser_config=_cfg())
    assert r.verdict == Verdict.VERIFIED
    assert r.browser["engine"] == "webkit"
    assert r.browser["provider"] == "playwright"
    assert r.browser["channel"] == "bundled"
    assert r.schema_version == "1.8.0"
    assert "safari_not_supported" in r.limitations


def test_webkit_headed_and_headless_plans(fixture_url):
    for headless in (True, False):
        r = execute_plan(
            _success_plan(
                fixture_url,
                f"wk-{'less' if headless else 'hed'}",
                headless=headless,
            )
        )
        assert r.plan_verdict == PlanVerdict.VERIFIED
        assert r.browser["engine"] == "webkit"
        assert r.browser["headless"] is headless
        assert r.browser.get("browser_version")
        r.check_invariants()


def test_webkit_comprehensive_interaction_plan(fixture_url):
    tid = LocatorStrategy.TEST_ID
    r = execute_plan(
        ExecutionPlan(
            plan_id="wk-all-actions",
            browser_config=_cfg(),
            operations=[
                _nav(fixture_url, "nav"),
                Operation(
                    operation_id="fill",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.FILL,
                        locator=Locator(strategy=tid, value="key-input"),
                        text="wk",
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(strategy=tid, value="key-input"),
                            attribute_name="value",
                            attribute_value="wk",
                        )
                    ],
                ),
                Operation(
                    operation_id="press",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.PRESS_KEY,
                        key="Enter",
                        locator=Locator(strategy=tid, value="key-input"),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(strategy=tid, value="state-indicator"),
                            attribute_name="data-state",
                            attribute_value="enter-submitted",
                        )
                    ],
                ),
                Operation(
                    operation_id="select",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.SELECT_OPTION,
                        locator=Locator(strategy=tid, value="color-select"),
                        option_value="green",
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(strategy=tid, value="select-output"),
                            attribute_name="data-value",
                            attribute_value="green",
                        )
                    ],
                ),
                Operation(
                    operation_id="check",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.SET_CHECKED,
                        locator=Locator(strategy=tid, value="agree-box"),
                        checked=True,
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(strategy=tid, value="check-output"),
                            attribute_name="data-agree",
                            attribute_value="true",
                        )
                    ],
                ),
                Operation(
                    operation_id="hover",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.HOVER,
                        locator=Locator(strategy=tid, value="hover-target"),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.TEXT,
                            locator=Locator(strategy=tid, value="hover-tooltip"),
                            text_value="tooltip-visible",
                            text_match=TextMatchMode.EXACT,
                        )
                    ],
                ),
                Operation(
                    operation_id="scroll",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.SCROLL_TO_TARGET,
                        locator=Locator(strategy=tid, value="below-fold"),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_IN_VIEWPORT,
                            locator=Locator(strategy=tid, value="below-fold"),
                            in_viewport=True,
                        )
                    ],
                ),
            ],
        )
    )
    assert r.plan_verdict == PlanVerdict.VERIFIED
    assert r.completion_status == CompletionStatus.COMPLETED
    assert r.browser["engine"] == "webkit"
    ids = {
        (s.browser_session_id, s.context_id, s.page_id)
        for s in r.steps
        if s.attempted
    }
    assert len(ids) == 1
    r.check_invariants()


def test_webkit_active_page_press_key(fixture_url):
    backend = PlaywrightBackend(browser_config=_cfg())
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        r = execute_operation(
            Operation(
                operation_id="page-esc",
                url=fixture_url,
                action=Action(
                    type=ActionType.PRESS_KEY,
                    key="Escape",
                    key_scope=KeyPressScope.ACTIVE_PAGE,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                        ),
                        attribute_name="data-state",
                        attribute_value="escape-pressed",
                    )
                ],
            ),
            backend=backend,
        )
        assert r.verdict == Verdict.VERIFIED
        assert r.action_evidence["dispatch_scope"] == "active_page"
        assert r.action_evidence["target_resolved"] is False
        assert r.target_resolution is None
    finally:
        backend.stop()


def test_webkit_stop_on_failure_and_skip(fixture_url):
    nv = execute_plan(
        ExecutionPlan(
            plan_id="wk-nv",
            browser_config=_cfg(),
            operations=[
                _nav(fixture_url, "a"),
                Operation(
                    operation_id="wrong",
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
    assert nv.plan_verdict == PlanVerdict.NOT_VERIFIED
    assert nv.steps[2].skipped is True
    assert nv.steps[0].receipt is not None
    nv.check_invariants()

    fail = execute_plan(
        ExecutionPlan(
            plan_id="wk-fail",
            browser_config=_cfg(),
            operations=[
                _nav(fixture_url, "a"),
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
                _click(fixture_url, "skip"),
            ],
        )
    )
    assert fail.plan_verdict == PlanVerdict.EXECUTION_FAILED
    assert fail.steps[2].skipped is True


def test_webkit_ten_sequential_owned_plans(fixture_url):
    ids = []
    for i in range(10):
        r = execute_plan(_success_plan(fixture_url, f"wk-seq-{i}"))
        assert r.plan_verdict == PlanVerdict.VERIFIED
        ids.append((r.browser_session_id, r.context_id, r.page_id))
    assert len(set(ids)) == 10


def test_webkit_injected_backend_reuse(fixture_url):
    backend = PlaywrightBackend(browser_config=_cfg())
    backend.start()
    try:
        sid = backend.browser_session_id
        r1 = execute_plan(
            ExecutionPlan(
                plan_id="wk-inj-1",
                browser_config=_cfg(),
                operations=[_nav(fixture_url, "n1")],
            ),
            backend=backend,
        )
        r2 = execute_plan(
            ExecutionPlan(
                plan_id="wk-inj-2",
                browser_config=_cfg(),
                operations=[_nav(fixture_url, "n2")],
            ),
            backend=backend,
        )
        assert r1.plan_verdict == PlanVerdict.VERIFIED
        assert r2.plan_verdict == PlanVerdict.VERIFIED
        assert r1.browser_session_id == sid == r2.browser_session_id
        assert backend.is_started is True
    finally:
        backend.stop()
    assert backend.is_started is False


def test_webkit_launch_failure_never_falls_back():
    pw = MagicMock()
    pw.webkit.launch.side_effect = RuntimeError("webkit boom")
    with pytest.raises(RuntimeError, match="webkit boom"):
        try:
            launch_playwright_browser(pw, _cfg())
        finally:
            pw.chromium.launch.assert_not_called()
            pw.firefox.launch.assert_not_called()
