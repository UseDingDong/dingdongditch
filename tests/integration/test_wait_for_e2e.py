"""Integration tests for declared wait_for conditions (all engines)."""

from __future__ import annotations

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
from dingdongditch.contract.wait import (
    LoadState,
    WaitCondition,
    WaitConditionType,
)
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


def _tid(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def _wait(
    url: str,
    condition: WaitCondition,
    *,
    op_id: str = "wait",
    timeout_ms: int = 3_000,
) -> Operation:
    return Operation(
        operation_id=op_id,
        url=url,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_condition=condition,
            wait_timeout_ms=timeout_ms,
        ),
        expectations=[],
    )


def _click(url: str, test_id: str, op_id: str = "click") -> Operation:
    return Operation(
        operation_id=op_id,
        url=url,
        action=Action(type=ActionType.CLICK, locator=_tid(test_id)),
        expectations=[
            Expectation(
                type=ExpectationType.ELEMENT_EXISTS,
                locator=_tid(test_id),
                exists=True,
            )
        ],
    )


@pytest.mark.parametrize("engine", ENGINES)
def test_wait_element_visible_and_hidden(fixture_url, engine):
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        execute_operation(_click(fixture_url, "delayed-control"), backend=backend)
        visible = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE, locator=_tid("result-item")
                ),
            ),
            backend=backend,
        )
        assert visible.verdict == Verdict.VERIFIED
        assert visible.action_evidence["condition_satisfied"] is True
        assert visible.action_evidence["timeout_occurred"] is False
        assert visible.browser["engine"] == engine.value
        assert visible.schema_version == "1.7.0"

        execute_operation(_click(fixture_url, "delay-hide-trigger"), backend=backend)
        hidden = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.ELEMENT_HIDDEN, locator=_tid("hide-soon")
                ),
            ),
            backend=backend,
        )
        assert hidden.verdict == Verdict.VERIFIED
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_wait_visible_timeout_is_not_verified(fixture_url, engine):
    r = execute_plan(
        ExecutionPlan(
            plan_id=f"wait-to-{engine.value}",
            browser_config=_cfg(engine),
            operations=[
                _nav(fixture_url),
                _wait(
                    fixture_url,
                    WaitCondition(
                        type=WaitConditionType.ELEMENT_VISIBLE,
                        locator=_tid("result-item"),
                    ),
                    timeout_ms=400,
                ),
            ],
        )
    )
    assert r.plan_verdict == PlanVerdict.NOT_VERIFIED
    step = r.steps[1]
    assert step.receipt.verdict == Verdict.NOT_VERIFIED
    assert step.receipt.action_evidence["timeout_occurred"] is True
    assert step.receipt.failure_kind is None or step.receipt.execution_status == "completed"


@pytest.mark.parametrize("engine", ENGINES)
def test_wait_ambiguous_fails_closed(fixture_url, engine):
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        r = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE,
                    locator=_tid("ambiguous-target"),
                ),
                timeout_ms=500,
            ),
            backend=backend,
        )
        assert r.verdict == Verdict.EXECUTION_FAILED
        assert r.target_resolution is not None
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_wait_text_url_attr_value_checked_selected_viewport(fixture_url, engine):
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        execute_operation(_click(fixture_url, "delay-state-trigger"), backend=backend)

        text = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.TEXT_PRESENT,
                    locator=_tid("wait-text"),
                    text_value="after",
                    text_match=TextMatchMode.EXACT,
                ),
                op_id="w-text",
            ),
            backend=backend,
        )
        assert text.verdict == Verdict.VERIFIED

        attr = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.ATTRIBUTE_EQUALS,
                    locator=_tid("wait-attr"),
                    attribute_name="data-phase",
                    attribute_value="ready",
                ),
                op_id="w-attr",
            ),
            backend=backend,
        )
        assert attr.verdict == Verdict.VERIFIED

        value = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.VALUE_EQUALS,
                    locator=_tid("wait-value"),
                    value="ready-value",
                ),
                op_id="w-val",
            ),
            backend=backend,
        )
        assert value.verdict == Verdict.VERIFIED

        checked = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.CHECKED_EQUALS,
                    locator=_tid("wait-check"),
                    checked=True,
                ),
                op_id="w-chk",
            ),
            backend=backend,
        )
        assert checked.verdict == Verdict.VERIFIED

        selected = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.SELECTED_VALUE_EQUALS,
                    locator=_tid("wait-select"),
                    selected_value="later",
                ),
                op_id="w-sel",
            ),
            backend=backend,
        )
        assert selected.verdict == Verdict.VERIFIED

        # Already at top; already-visible should be in viewport.
        vp = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.ELEMENT_IN_VIEWPORT,
                    locator=_tid("already-visible"),
                    in_viewport=True,
                ),
                op_id="w-vp",
            ),
            backend=backend,
        )
        assert vp.verdict == Verdict.VERIFIED

        execute_operation(_click(fixture_url, "delay-hash-trigger"), backend=backend)
        url_wait = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.URL_MATCHES,
                    url_value="#waited",
                    url_match=UrlMatchMode.CONTAINS,
                ),
                op_id="w-url",
            ),
            backend=backend,
        )
        assert url_wait.verdict == Verdict.VERIFIED
        assert "url" in url_wait.action_evidence["final_observed_state"]
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_wait_load_state(fixture_url, engine):
    r = execute_operation(
        Operation(
            operation_id="load",
            url=fixture_url,
            action=Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(
                    type=WaitConditionType.LOAD_STATE,
                    load_state=LoadState.DOMCONTENTLOADED,
                ),
                wait_timeout_ms=5_000,
            ),
        ),
        browser_config=_cfg(engine),
    )
    # Page may not be loaded yet; ensure_on_url runs first for non-navigate.
    # For wait-only op, ensure_on_url navigates then wait runs — should verify.
    assert r.verdict == Verdict.VERIFIED
    assert r.action_evidence["condition_type"] == "load_state"


@pytest.mark.parametrize("engine", ENGINES)
def test_wait_plan_success_and_timeout_stops(fixture_url, engine):
    ok = execute_plan(
        ExecutionPlan(
            plan_id=f"wait-ok-{engine.value}",
            browser_config=_cfg(engine),
            operations=[
                _nav(fixture_url, "n"),
                _click(fixture_url, "delayed-control", "c"),
                _wait(
                    fixture_url,
                    WaitCondition(
                        type=WaitConditionType.ELEMENT_VISIBLE,
                        locator=_tid("result-item"),
                    ),
                    op_id="w",
                ),
                Operation(
                    operation_id="after",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.CLICK, locator=_tid("noop-control")
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_EXISTS,
                            locator=_tid("noop-control"),
                            exists=True,
                        )
                    ],
                ),
            ],
        )
    )
    assert ok.plan_verdict == PlanVerdict.VERIFIED
    assert ok.completion_status == CompletionStatus.COMPLETED
    assert ok.steps[2].receipt.verdict == Verdict.VERIFIED
    assert ok.steps[3].attempted is True
    ids = {
        (s.browser_session_id, s.context_id, s.page_id)
        for s in ok.steps
        if s.attempted
    }
    assert len(ids) == 1
    assert ok.browser["engine"] == engine.value
    ok.check_invariants()

    stopped = execute_plan(
        ExecutionPlan(
            plan_id=f"wait-stop-{engine.value}",
            browser_config=_cfg(engine),
            operations=[
                _nav(fixture_url, "n"),
                _wait(
                    fixture_url,
                    WaitCondition(
                        type=WaitConditionType.ELEMENT_VISIBLE,
                        locator=_tid("result-item"),
                    ),
                    timeout_ms=300,
                    op_id="w",
                ),
                _click(fixture_url, "noop-control", "skip"),
            ],
        )
    )
    assert stopped.plan_verdict == PlanVerdict.NOT_VERIFIED
    assert stopped.steps[2].skipped is True
    assert stopped.steps[0].receipt is not None
    stopped.check_invariants()


@pytest.mark.parametrize("engine", [BrowserEngine.CHROMIUM])
def test_headed_wait_plan(fixture_url, engine):
    r = execute_plan(
        ExecutionPlan(
            plan_id="headed-wait",
            browser_config=_cfg(engine, headless=False),
            operations=[
                _nav(fixture_url),
                _click(fixture_url, "delayed-control"),
                _wait(
                    fixture_url,
                    WaitCondition(
                        type=WaitConditionType.TEXT_PRESENT,
                        locator=_tid("state-indicator"),
                        text_value="delayed-ready",
                        text_match=TextMatchMode.CONTAINS,
                    ),
                ),
            ],
        )
    )
    assert r.plan_verdict == PlanVerdict.VERIFIED
    assert r.browser["headless"] is False


def test_text_timeout_not_verified(fixture_url):
    backend = PlaywrightBackend(browser_config=_cfg(BrowserEngine.CHROMIUM))
    backend.start()
    try:
        execute_operation(_nav(fixture_url), backend=backend)
        r = execute_operation(
            _wait(
                fixture_url,
                WaitCondition(
                    type=WaitConditionType.TEXT_PRESENT,
                    locator=_tid("wait-text"),
                    text_value="never-appears",
                    text_match=TextMatchMode.EXACT,
                ),
                timeout_ms=300,
            ),
            backend=backend,
        )
        assert r.verdict == Verdict.NOT_VERIFIED
        assert r.action_evidence["elapsed_ms"] >= 250
    finally:
        backend.stop()
