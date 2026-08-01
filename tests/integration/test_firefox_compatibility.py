"""Firefox compatibility + cross-engine parity (real bundled browsers)."""

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
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.plan import (
    CompletionStatus,
    ExecutionPlan,
    PlanVerdict,
)
from dingdongditch.contract.target import (
    ConstraintType,
    NameMatchMode,
    TargetConstraint,
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


def _success_plan(
    url: str, plan_id: str, engine: BrowserEngine, *, headless: bool = True
) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id=plan_id,
        browser_config=_cfg(engine, headless=headless),
        operations=[
            _nav(url, f"{plan_id}-nav"),
            _fill(url, plan_id, f"{plan_id}-fill"),
            _click(url, f"{plan_id}-click"),
        ],
    )


@pytest.mark.parametrize("engine", ENGINES)
def test_standalone_navigate_fill_click_and_input_value(fixture_url, engine):
    cfg = _cfg(engine)
    nav = execute_operation(_nav(fixture_url, "n"), browser_config=cfg)
    assert nav.verdict == Verdict.VERIFIED
    assert nav.browser["engine"] == engine.value

    fill = execute_operation(
        _fill(fixture_url, f"value-{engine.value}", "f"), browser_config=cfg
    )
    assert fill.verdict == Verdict.VERIFIED

    click = execute_operation(_click(fixture_url, "c"), browser_config=cfg)
    assert click.verdict == Verdict.VERIFIED


@pytest.mark.parametrize("engine", ENGINES)
def test_constrained_and_ambiguous_targets(fixture_url, engine):
    cfg = _cfg(engine)
    backend = PlaywrightBackend(browser_config=cfg)
    backend.start()
    try:
        execute_operation(_nav(fixture_url, "pre"), backend=backend)
        ok = execute_operation(
            Operation(
                operation_id="role",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=Locator(
                        strategy=LocatorStrategy.ROLE_NAME,
                        role="button",
                        name="Activate Target",
                        name_match=NameMatchMode.EXACT,
                        constraints=(
                            TargetConstraint(
                                type=ConstraintType.VISIBLE, visible=True
                            ),
                        ),
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
            backend=backend,
        )
        assert ok.verdict == Verdict.VERIFIED
        assert ok.target_resolution is not None

        amb = execute_operation(
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
            backend=backend,
        )
        assert amb.verdict == Verdict.EXECUTION_FAILED
        assert amb.target_resolution is not None
        assert amb.target_resolution.get("dispatch_permitted") is False
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_ordered_plan_success_same_session(fixture_url, engine):
    receipt = execute_plan(_success_plan(fixture_url, f"ok-{engine.value}", engine))
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.completion_status == CompletionStatus.COMPLETED
    assert receipt.browser["engine"] == engine.value
    assert receipt.browser_session_id
    ids = {
        (s.browser_session_id, s.context_id, s.page_id)
        for s in receipt.steps
        if s.attempted
    }
    assert len(ids) == 1
    receipt.check_invariants()


@pytest.mark.parametrize("engine", [BrowserEngine.FIREFOX])
def test_firefox_headed_and_headless_plans(fixture_url, engine):
    for headless in (True, False):
        r = execute_plan(
            _success_plan(
                fixture_url, f"ff-{'less' if headless else 'hed'}", engine, headless=headless
            )
        )
        assert r.plan_verdict == PlanVerdict.VERIFIED
        assert r.browser["engine"] == "firefox"
        assert r.browser["headless"] is headless
        assert r.browser.get("browser_version")


def test_firefox_stop_on_failure_variants(fixture_url):
    engine = BrowserEngine.FIREFOX
    nv = execute_plan(
        ExecutionPlan(
            plan_id="ff-nv",
            browser_config=_cfg(engine),
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
    nv.check_invariants()

    fail = execute_plan(
        ExecutionPlan(
            plan_id="ff-fail",
            browser_config=_cfg(engine),
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

    ind = execute_plan(
        ExecutionPlan(
            plan_id="ff-ind",
            browser_config=_cfg(engine),
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
                _click(fixture_url, "skip"),
            ],
        )
    )
    assert ind.plan_verdict == PlanVerdict.INDETERMINATE
    assert ind.steps[2].skipped is True


def test_firefox_ten_sequential_owned_plans(fixture_url):
    ids = []
    for i in range(10):
        r = execute_plan(
            _success_plan(fixture_url, f"ff-seq-{i}", BrowserEngine.FIREFOX)
        )
        assert r.plan_verdict == PlanVerdict.VERIFIED
        ids.append((r.browser_session_id, r.context_id, r.page_id))
    assert len(set(ids)) == 10


def test_firefox_success_after_stopped_and_injected_reuse(fixture_url):
    stopped = execute_plan(
        ExecutionPlan(
            plan_id="ff-stop",
            browser_config=_cfg(BrowserEngine.FIREFOX),
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
                _nav(fixture_url, "skip"),
            ],
        )
    )
    assert stopped.completion_status == CompletionStatus.STOPPED

    ok = execute_plan(
        _success_plan(fixture_url, "ff-after-stop", BrowserEngine.FIREFOX)
    )
    assert ok.plan_verdict == PlanVerdict.VERIFIED

    backend = PlaywrightBackend(browser_config=_cfg(BrowserEngine.FIREFOX))
    backend.start()
    try:
        sid = backend.browser_session_id
        r1 = execute_plan(
            ExecutionPlan(
                plan_id="ff-inj-1",
                operations=[_nav(fixture_url, "n1")],
            ),
            backend=backend,
        )
        r2 = execute_plan(
            ExecutionPlan(
                plan_id="ff-inj-2",
                operations=[_fill(fixture_url, "shared", "f2")],
            ),
            backend=backend,
        )
        assert r1.browser_session_id == sid == r2.browser_session_id
        assert backend.is_started is True
    finally:
        backend.stop()
        assert backend.is_started is False


def test_firefox_skipped_steps_never_dispatch(fixture_url):
    real = PlaywrightBackend.dispatch
    seen: list[str] = []

    def counting(self, operation, *args, **kwargs):
        seen.append(operation.operation_id)
        return real(self, operation, *args, **kwargs)

    with patch.object(PlaywrightBackend, "dispatch", counting):
        r = execute_plan(
            ExecutionPlan(
                plan_id="ff-nodispatch",
                browser_config=_cfg(BrowserEngine.FIREFOX),
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
                    _click(fixture_url, "skipped-click"),
                ],
            )
        )
    assert r.steps[1].skipped is True
    assert "skipped-click" not in seen


def test_cross_engine_verdict_parity(fixture_url):
    results = {}
    for engine in ENGINES:
        r = execute_plan(_success_plan(fixture_url, f"parity-{engine.value}", engine))
        results[engine.value] = (
            r.plan_verdict,
            r.completion_status,
            r.verified_step_count,
            r.skipped_step_count,
        )
        assert r.browser["engine"] == engine.value
    assert results["chromium"] == results["firefox"]


def test_firefox_fill_state_persists(fixture_url):
    r = execute_plan(
        ExecutionPlan(
            plan_id="ff-persist",
            browser_config=_cfg(BrowserEngine.FIREFOX),
            operations=[
                _nav(fixture_url, "n"),
                _fill(fixture_url, "keep-ff", "f"),
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


def test_all_bundled_engines_supported_safari_rejected():
    for engine in (
        BrowserEngine.CHROMIUM,
        BrowserEngine.FIREFOX,
        BrowserEngine.WEBKIT,
    ):
        BrowserConfig(engine=engine).validate()
    with pytest.raises(Exception):
        BrowserConfig(engine="safari").validate()  # type: ignore[arg-type]
