"""Integration tests for press_key, select_option, set_checked, hover, scroll_to_target."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dingdongditch.backends.playwright_backend import PlaywrightBackend
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

ENGINES = [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT]


def _cfg(engine: BrowserEngine, *, headless: bool = True) -> BrowserConfig:
    return BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=engine,
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


@pytest.mark.parametrize("engine", ENGINES)
def test_press_key_target_enter(fixture_url, engine):
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        execute_operation(
            Operation(
                operation_id="fill-key",
                url=fixture_url,
                action=Action(
                    type=ActionType.FILL,
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="key-input"),
                    text="hello",
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="key-input"
                        ),
                        attribute_name="value",
                        attribute_value="hello",
                    )
                ],
            ),
            backend=backend,
        )
        r = execute_operation(
            Operation(
                operation_id="press-enter",
                url=fixture_url,
                action=Action(
                    type=ActionType.PRESS_KEY,
                    key="Enter",
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="key-input"),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                        ),
                        attribute_name="data-state",
                        attribute_value="enter-submitted",
                    )
                ],
            ),
            backend=backend,
        )
        assert r.verdict == Verdict.VERIFIED
        assert r.action_evidence["key"] == "Enter"
        assert r.action_evidence["dispatch_scope"] == "target"
        assert r.browser["engine"] == engine.value
        assert r.schema_version == "1.7.0"
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_press_key_active_page_escape(fixture_url, engine):
    r_plan = execute_plan(
        ExecutionPlan(
            plan_id=f"escape-{engine.value}",
            browser_config=_cfg(engine),
            operations=[
                _nav(fixture_url),
                Operation(
                    operation_id="esc",
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
                                strategy=LocatorStrategy.TEST_ID,
                                value="state-indicator",
                            ),
                            attribute_name="data-state",
                            attribute_value="escape-pressed",
                        )
                    ],
                ),
            ],
        )
    )
    assert r_plan.plan_verdict == PlanVerdict.VERIFIED
    assert r_plan.steps[1].receipt.action_evidence["dispatch_scope"] == "active_page"
    assert r_plan.steps[1].receipt.target_resolution is None


@pytest.mark.parametrize("engine", ENGINES)
def test_select_option_by_value_and_label(fixture_url, engine):
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        by_value = execute_operation(
            Operation(
                operation_id="sel-v",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="color-select"
                    ),
                    option_value="green",
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="select-output"
                        ),
                        attribute_name="data-value",
                        attribute_value="green",
                    )
                ],
            ),
            backend=backend,
        )
        assert by_value.verdict == Verdict.VERIFIED
        assert by_value.action_evidence["selected_value"] == "green"

        by_label = execute_operation(
            Operation(
                operation_id="sel-l",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="color-select"
                    ),
                    option_label="Azure",
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="select-output"
                        ),
                        attribute_name="data-value",
                        attribute_value="blue",
                    )
                ],
            ),
            backend=backend,
        )
        assert by_label.verdict == Verdict.VERIFIED
    finally:
        backend.stop()


def test_select_unknown_option_and_non_select(fixture_url):
    backend = PlaywrightBackend(browser_config=_cfg(BrowserEngine.CHROMIUM))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        bad = execute_operation(
            Operation(
                operation_id="bad-opt",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="color-select"
                    ),
                    option_value="nope",
                ),
                expectations=[],
            ),
            backend=backend,
        )
        assert bad.verdict == Verdict.EXECUTION_FAILED

        not_sel = execute_operation(
            Operation(
                operation_id="not-sel",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="text-input"
                    ),
                    option_value="x",
                ),
                expectations=[],
            ),
            backend=backend,
        )
        assert not_sel.verdict == Verdict.EXECUTION_FAILED
        assert not_sel.failure_kind == "target_not_select"
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_set_checked_toggle_and_idempotent(fixture_url, engine):
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        on = execute_operation(
            Operation(
                operation_id="check-on",
                url=fixture_url,
                action=Action(
                    type=ActionType.SET_CHECKED,
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="agree-box"),
                    checked=True,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="check-output"
                        ),
                        attribute_name="data-agree",
                        attribute_value="true",
                    )
                ],
            ),
            backend=backend,
        )
        assert on.verdict == Verdict.VERIFIED
        assert on.action_evidence["dispatched"] is True
        assert on.action_evidence["checked_after"] is True

        again = execute_operation(
            Operation(
                operation_id="check-again",
                url=fixture_url,
                action=Action(
                    type=ActionType.SET_CHECKED,
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="agree-box"),
                    checked=True,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="check-output"
                        ),
                        attribute_name="data-agree",
                        attribute_value="true",
                    )
                ],
            ),
            backend=backend,
        )
        assert again.verdict == Verdict.VERIFIED
        assert again.action_evidence["already_satisfied"] is True
        assert again.action_evidence["dispatched"] is False

        off = execute_operation(
            Operation(
                operation_id="uncheck",
                url=fixture_url,
                action=Action(
                    type=ActionType.SET_CHECKED,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="prechecked-box"
                    ),
                    checked=False,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="check-output"
                        ),
                        attribute_name="data-prefers",
                        attribute_value="false",
                    )
                ],
            ),
            backend=backend,
        )
        assert off.verdict == Verdict.VERIFIED
    finally:
        backend.stop()


def test_radio_checked_true_and_false_policy(fixture_url):
    backend = PlaywrightBackend(browser_config=_cfg(BrowserEngine.CHROMIUM))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        ok = execute_operation(
            Operation(
                operation_id="radio-on",
                url=fixture_url,
                action=Action(
                    type=ActionType.SET_CHECKED,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="size-large"
                    ),
                    checked=True,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                        ),
                        attribute_name="data-state",
                        attribute_value="size-large",
                    )
                ],
            ),
            backend=backend,
        )
        assert ok.verdict == Verdict.VERIFIED

        bad = execute_operation(
            Operation(
                operation_id="radio-off",
                url=fixture_url,
                action=Action(
                    type=ActionType.SET_CHECKED,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="size-large"
                    ),
                    checked=False,
                ),
                expectations=[],
            ),
            backend=backend,
        )
        assert bad.verdict == Verdict.EXECUTION_FAILED
        assert bad.failure_kind == "unsupported_radio_uncheck"
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_hover_reveals_tooltip(fixture_url, engine):
    r = execute_plan(
        ExecutionPlan(
            plan_id=f"hover-{engine.value}",
            browser_config=_cfg(engine),
            operations=[
                _nav(fixture_url),
                Operation(
                    operation_id="hov",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.HOVER,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="hover-target"
                        ),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_VISIBLE,
                            locator=Locator(
                                strategy=LocatorStrategy.TEST_ID, value="hover-tooltip"
                            ),
                            visible=True,
                        )
                    ],
                ),
            ],
        )
    )
    assert r.plan_verdict == PlanVerdict.VERIFIED


@pytest.mark.parametrize("engine", ENGINES)
def test_scroll_to_target_and_already_visible(fixture_url, engine):
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        # Check idempotent already-visible while still at page top.
        already = execute_operation(
            Operation(
                operation_id="already",
                url=fixture_url,
                action=Action(
                    type=ActionType.SCROLL_TO_TARGET,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="already-visible"
                    ),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ELEMENT_IN_VIEWPORT,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="already-visible"
                        ),
                        in_viewport=True,
                    )
                ],
            ),
            backend=backend,
        )
        assert already.verdict == Verdict.VERIFIED
        assert already.action_evidence["already_satisfied"] is True
        assert already.action_evidence["dispatched"] is False

        scroll = execute_operation(
            Operation(
                operation_id="scroll",
                url=fixture_url,
                action=Action(
                    type=ActionType.SCROLL_TO_TARGET,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="below-fold"
                    ),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ELEMENT_IN_VIEWPORT,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="below-fold"
                        ),
                        in_viewport=True,
                    )
                ],
            ),
            backend=backend,
        )
        assert scroll.verdict == Verdict.VERIFIED
        assert scroll.action_evidence["in_viewport_before"] is False
        assert scroll.action_evidence["in_viewport_after"] is True
        assert scroll.action_evidence["dispatched"] is True
        assert already.browser["page_id"] == scroll.browser["page_id"]
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_combined_plan_new_actions(fixture_url, engine):
    plan = ExecutionPlan(
        plan_id=f"combo-{engine.value}",
        browser_config=_cfg(engine, headless=True),
        operations=[
            _nav(fixture_url, "n"),
            Operation(
                operation_id="fill",
                url=fixture_url,
                action=Action(
                    type=ActionType.FILL,
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="key-input"),
                    text="plan",
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="key-input"
                        ),
                        attribute_name="value",
                        attribute_value="plan",
                    )
                ],
            ),
            Operation(
                operation_id="enter",
                url=fixture_url,
                action=Action(
                    type=ActionType.PRESS_KEY,
                    key="Enter",
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="key-input"),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                        ),
                        attribute_name="data-state",
                        attribute_value="enter-submitted",
                    )
                ],
            ),
            Operation(
                operation_id="sel",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="color-select"
                    ),
                    option_value="red",
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="select-output"
                        ),
                        attribute_name="data-value",
                        attribute_value="red",
                    )
                ],
            ),
            Operation(
                operation_id="chk",
                url=fixture_url,
                action=Action(
                    type=ActionType.SET_CHECKED,
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="agree-box"),
                    checked=True,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="check-output"
                        ),
                        attribute_name="data-agree",
                        attribute_value="true",
                    )
                ],
            ),
            Operation(
                operation_id="hov",
                url=fixture_url,
                action=Action(
                    type=ActionType.HOVER,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="hover-target"
                    ),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ELEMENT_VISIBLE,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="hover-tooltip"
                        ),
                        visible=True,
                    )
                ],
            ),
            Operation(
                operation_id="scr",
                url=fixture_url,
                action=Action(
                    type=ActionType.SCROLL_TO_TARGET,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="below-fold"
                    ),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ELEMENT_IN_VIEWPORT,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="below-fold"
                        ),
                        in_viewport=True,
                    )
                ],
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.completion_status == CompletionStatus.COMPLETED
    assert receipt.verified_step_count == 7
    ids = {
        (s.browser_session_id, s.context_id, s.page_id)
        for s in receipt.steps
        if s.attempted
    }
    assert len(ids) == 1
    receipt.check_invariants()


def test_new_action_failure_stops_plan(fixture_url):
    r = execute_plan(
        ExecutionPlan(
            plan_id="stop-new",
            browser_config=_cfg(BrowserEngine.CHROMIUM),
            operations=[
                _nav(fixture_url, "n"),
                Operation(
                    operation_id="bad-sel",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.SELECT_OPTION,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="color-select"
                        ),
                        option_value="missing",
                    ),
                    expectations=[],
                ),
                Operation(
                    operation_id="never",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.HOVER,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="hover-target"
                        ),
                    ),
                    expectations=[],
                ),
            ],
        )
    )
    assert r.completion_status == CompletionStatus.STOPPED
    assert r.steps[2].skipped is True
    assert r.decisive_operation_id == "bad-sel"


def test_skipped_new_action_never_dispatches(fixture_url):
    real = PlaywrightBackend.dispatch
    seen: list[str] = []

    def counting(self, operation, *args, **kwargs):
        seen.append(operation.operation_id)
        return real(self, operation, *args, **kwargs)

    with patch.object(PlaywrightBackend, "dispatch", counting):
        execute_plan(
            ExecutionPlan(
                plan_id="skip-dispatch",
                browser_config=_cfg(BrowserEngine.CHROMIUM),
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
                        locate_retry_ms=50,
                    ),
                    Operation(
                        operation_id="skipped-hover",
                        url=fixture_url,
                        action=Action(
                            type=ActionType.HOVER,
                            locator=Locator(
                                strategy=LocatorStrategy.TEST_ID, value="hover-target"
                            ),
                        ),
                        expectations=[],
                    ),
                ],
            )
        )
    assert "skipped-hover" not in seen


def test_press_key_not_verified_when_expectation_fails(fixture_url):
    r = execute_plan(
        ExecutionPlan(
            plan_id="nv-key",
            browser_config=_cfg(BrowserEngine.CHROMIUM),
            operations=[
                _nav(fixture_url),
                Operation(
                    operation_id="esc-bad",
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
                                strategy=LocatorStrategy.TEST_ID,
                                value="state-indicator",
                            ),
                            attribute_name="data-state",
                            attribute_value="must-not-happen",
                        )
                    ],
                ),
            ],
        )
    )
    assert r.plan_verdict == PlanVerdict.NOT_VERIFIED


@pytest.mark.parametrize("engine", ENGINES)
def test_headed_basic_plan(fixture_url, engine):
    r = execute_plan(
        ExecutionPlan(
            plan_id=f"headed-basic-{engine.value}",
            browser_config=_cfg(engine, headless=False),
            operations=[
                _nav(fixture_url),
                Operation(
                    operation_id="hov",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.HOVER,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="hover-target"
                        ),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.TEXT,
                            locator=Locator(
                                strategy=LocatorStrategy.TEST_ID, value="hover-tooltip"
                            ),
                            text_value="tooltip-visible",
                            text_match=TextMatchMode.EXACT,
                        )
                    ],
                ),
            ],
        )
    )
    assert r.plan_verdict == PlanVerdict.VERIFIED
    assert r.browser["headless"] is False
    assert r.browser["engine"] == engine.value
