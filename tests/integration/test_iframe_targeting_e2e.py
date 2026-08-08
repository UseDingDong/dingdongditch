"""Integration tests: explicit same-page iframe targeting (all engines)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urljoin

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
    UrlMatchMode,
)
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.page_precondition import (
    PageCondition,
    PageConditionType,
    PagePrecondition,
)
from dingdongditch.contract.plan import PlanVerdict
from dingdongditch.contract.verdict import Verdict
from dingdongditch.contract.wait import WaitCondition, WaitConditionType
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan

ENGINES = [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT]
ROOT = Path(__file__).resolve().parents[2]


def _cfg(engine: BrowserEngine) -> BrowserConfig:
    return BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=engine,
        channel=BrowserChannel.BUNDLED,
        headless=True,
    )


def _host_url(fixture_url: str) -> str:
    return urljoin(fixture_url, "iframe_host.html")


def _tid(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def _nav(url: str) -> Operation:
    return Operation(
        operation_id="nav",
        url=url,
        action=Action(type=ActionType.NAVIGATE),
        expectations=[
            Expectation(
                type=ExpectationType.URL,
                url_value="iframe_host.html",
                url_match=UrlMatchMode.CONTAINS,
            )
        ],
        timeout_ms=30_000,
    )


@pytest.mark.parametrize("engine", ENGINES)
def test_click_and_fill_inside_unique_same_origin_iframe(fixture_url, engine):
    url = _host_url(fixture_url)
    frame = _tid("unique-frame")
    cfg = _cfg(engine)
    backend = PlaywrightBackend(browser_config=cfg)
    backend.start()
    try:
        assert execute_operation(_nav(url), backend=backend).verdict == Verdict.VERIFIED

        click = execute_operation(
            Operation(
                operation_id="frame-click",
                url=url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=_tid("frame-click"),
                    frame=frame,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=_tid("frame-click"),
                        frame=frame,
                        attribute_name="data-state",
                        attribute_value="clicked",
                    )
                ],
                timeout_ms=15_000,
            ),
            backend=backend,
        )
        assert click.verdict == Verdict.VERIFIED
        assert click.browser is not None
        sid = click.browser.get("browser_session_id")
        assert sid and click.browser.get("context_id") and click.browser.get("page_id")
        assert click.target_resolution is not None
        assert click.target_resolution.get("frame_locator") is not None

        fill = execute_operation(
            Operation(
                operation_id="frame-fill",
                url=url,
                action=Action(
                    type=ActionType.FILL,
                    locator=_tid("frame-input"),
                    text="iframe-value",
                    frame=frame,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=_tid("frame-input"),
                        frame=frame,
                        attribute_name="value",
                        attribute_value="iframe-value",
                    )
                ],
                timeout_ms=15_000,
            ),
            backend=backend,
        )
        assert fill.verdict == Verdict.VERIFIED
        assert fill.browser.get("browser_session_id") == sid
        assert fill.browser.get("page_id") == click.browser.get("page_id")
        assert fill.schema_version == "1.8.0"
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_wait_for_inside_iframe(fixture_url, engine):
    url = _host_url(fixture_url)
    frame = _tid("unique-frame")
    cfg = _cfg(engine)
    backend = PlaywrightBackend(browser_config=cfg)
    backend.start()
    try:
        assert execute_operation(_nav(url), backend=backend).verdict == Verdict.VERIFIED
        assert (
            execute_operation(
                Operation(
                    operation_id="reveal",
                    url=url,
                    action=Action(
                        type=ActionType.CLICK,
                        locator=_tid("frame-reveal"),
                        frame=frame,
                    ),
                    expectations=[],
                    timeout_ms=15_000,
                ),
                backend=backend,
            ).action_executed_successfully
            is True
        )
        wait = execute_operation(
            Operation(
                operation_id="wait-in-frame",
                url=url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=3_000,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.ELEMENT_VISIBLE,
                        locator=_tid("frame-delayed"),
                        frame=frame,
                    ),
                ),
                expectations=[],
                timeout_ms=10_000,
            ),
            backend=backend,
        )
        assert wait.verdict == Verdict.VERIFIED
        assert wait.action_evidence and wait.action_evidence.get("condition_satisfied")
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_main_document_unchanged_without_frame(fixture_url, engine):
    url = _host_url(fixture_url)
    cfg = _cfg(engine)
    r = execute_operation(
        Operation(
            operation_id="main-click",
            url=url,
            action=Action(type=ActionType.CLICK, locator=_tid("main-click")),
            expectations=[
                Expectation(
                    type=ExpectationType.ATTRIBUTE,
                    locator=_tid("main-click"),
                    attribute_name="data-state",
                    attribute_value="clicked",
                )
            ],
            timeout_ms=20_000,
        ),
        browser_config=cfg,
    )
    # navigate+click via ensure_on_url — need navigate first for fresh page
    # execute_operation ensure_on_url loads url then clicks; good.
    assert r.verdict == Verdict.VERIFIED
    assert r.target_resolution is not None
    assert r.target_resolution.get("frame_locator") is None


@pytest.mark.parametrize("engine", ENGINES)
def test_missing_iframe_fails_closed(fixture_url, engine):
    url = _host_url(fixture_url)
    r = execute_operation(
        Operation(
            operation_id="missing-frame",
            url=url,
            action=Action(
                type=ActionType.CLICK,
                locator=_tid("frame-click"),
                frame=_tid("no-such-frame"),
            ),
            expectations=[],
            timeout_ms=10_000,
            locate_retry_ms=200,
        ),
        browser_config=_cfg(engine),
    )
    assert r.verdict == Verdict.EXECUTION_FAILED
    assert r.failure_kind == "missing_frame"


@pytest.mark.parametrize("engine", ENGINES)
def test_ambiguous_iframe_fails_closed(fixture_url, engine):
    url = _host_url(fixture_url)
    r = execute_operation(
        Operation(
            operation_id="ambiguous-frame",
            url=url,
            action=Action(
                type=ActionType.CLICK,
                locator=_tid("frame-click"),
                frame=_tid("ambiguous-frame"),
            ),
            expectations=[],
            timeout_ms=10_000,
            locate_retry_ms=0,
        ),
        browser_config=_cfg(engine),
    )
    assert r.verdict == Verdict.EXECUTION_FAILED
    assert r.failure_kind == "ambiguous_frame"


@pytest.mark.parametrize("engine", ENGINES)
def test_detached_iframe_fails_closed(fixture_url, engine):
    url = _host_url(fixture_url)
    cfg = _cfg(engine)
    backend = PlaywrightBackend(browser_config=cfg)
    backend.start()
    try:
        assert execute_operation(_nav(url), backend=backend).verdict == Verdict.VERIFIED
        assert (
            execute_operation(
                Operation(
                    operation_id="detach",
                    url=url,
                    action=Action(type=ActionType.CLICK, locator=_tid("detach-trigger")),
                    expectations=[],
                    timeout_ms=10_000,
                ),
                backend=backend,
            ).action_executed_successfully
            is True
        )
        r = execute_operation(
            Operation(
                operation_id="use-detached",
                url=url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=_tid("frame-click"),
                    frame=_tid("detach-frame"),
                ),
                expectations=[],
                timeout_ms=10_000,
                locate_retry_ms=200,
            ),
            backend=backend,
        )
        assert r.verdict == Verdict.EXECUTION_FAILED
        assert r.failure_kind in ("missing_frame", "detached_frame")
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_target_missing_inside_iframe(fixture_url, engine):
    url = _host_url(fixture_url)
    r = execute_operation(
        Operation(
            operation_id="missing-inner",
            url=url,
            action=Action(
                type=ActionType.CLICK,
                locator=_tid("no-such-inner"),
                frame=_tid("unique-frame"),
            ),
            expectations=[],
            timeout_ms=10_000,
            locate_retry_ms=200,
        ),
        browser_config=_cfg(engine),
    )
    assert r.verdict == Verdict.EXECUTION_FAILED
    assert r.failure_kind in ("zero_after_primary", "zero_after_constraints")


@pytest.mark.parametrize("engine", ENGINES)
def test_timeout_inside_iframe(fixture_url, engine):
    url = _host_url(fixture_url)
    r = execute_operation(
        Operation(
            operation_id="wait-timeout-frame",
            url=url,
            action=Action(
                type=ActionType.WAIT_FOR,
                wait_timeout_ms=400,
                wait_condition=WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE,
                    locator=_tid("frame-delayed"),
                    frame=_tid("unique-frame"),
                ),
            ),
            expectations=[],
            timeout_ms=10_000,
        ),
        browser_config=_cfg(engine),
    )
    assert r.verdict == Verdict.NOT_VERIFIED
    assert r.action_evidence and r.action_evidence.get("timeout_occurred") is True


@pytest.mark.parametrize("engine", ENGINES)
def test_cross_origin_iframe_click(fixture_url, engine):
    url = _host_url(fixture_url)
    cfg = _cfg(engine)
    backend = PlaywrightBackend(browser_config=cfg)
    backend.start()
    try:
        assert execute_operation(_nav(url), backend=backend).verdict == Verdict.VERIFIED
        # Allow cross-origin child to load.
        backend.page.wait_for_timeout(500)
        r = execute_operation(
            Operation(
                operation_id="xo-click",
                url=url,
                action=Action(
                    type=ActionType.CLICK,
                    locator=_tid("frame-click"),
                    frame=_tid("cross-origin-frame"),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=_tid("frame-click"),
                        frame=_tid("cross-origin-frame"),
                        attribute_name="data-state",
                        attribute_value="clicked",
                    )
                ],
                timeout_ms=20_000,
                locate_retry_ms=2_000,
            ),
            backend=backend,
        )
        assert r.verdict == Verdict.VERIFIED
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES)
def test_iframe_plan_file_and_stdin_compatible(fixture_url, engine, tmp_path):
    url = _host_url(fixture_url)
    doc = {
        "browser": {
            "provider": "playwright",
            "engine": engine.value,
            "channel": "bundled",
            "headless": True,
        },
        "plan": {
            "plan_id": "iframe-plan",
            "failure_policy": "stop_on_failure",
            "operations": [
                {
                    "operation_id": "nav",
                    "url": url,
                    "action": {"type": "navigate"},
                    "expectations": [
                        {
                            "type": "url",
                            "url_value": "iframe_host.html",
                            "url_match": "contains",
                        }
                    ],
                    "timeout_ms": 30000,
                },
                {
                    "operation_id": "fill-frame",
                    "url": url,
                    "timeout_ms": 15000,
                    "action": {
                        "type": "fill",
                        "text": "from-json",
                        "frame": {"strategy": "test_id", "value": "unique-frame"},
                        "locator": {"strategy": "test_id", "value": "frame-input"},
                    },
                    "expectations": [
                        {
                            "type": "attribute",
                            "attribute_name": "value",
                            "attribute_value": "from-json",
                            "frame": {"strategy": "test_id", "value": "unique-frame"},
                            "locator": {"strategy": "test_id", "value": "frame-input"},
                        }
                    ],
                },
            ],
        },
    }
    path = tmp_path / "iframe_plan.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    from dingdongditch.plan_json import load_plan_file, load_plan_json_text

    file_plan = load_plan_file(path)
    stdin_plan = load_plan_json_text(json.dumps(doc), source="stdin")
    assert file_plan.operations[1].action.frame is not None
    assert stdin_plan.operations[1].action.frame is not None
    assert (
        file_plan.operations[1].action.frame.value
        == stdin_plan.operations[1].action.frame.value
    )

    receipt = execute_plan(file_plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.browser_session_id
    assert receipt.context_id
    assert receipt.page_id
    assert len({s.browser_session_id for s in receipt.steps if s.attempted}) == 1


@pytest.mark.parametrize("engine", ENGINES)
def test_nested_frame_path_click_fill_and_select(fixture_url, engine):
    url = _host_url(fixture_url)
    path = (_tid("unique-frame"), _tid("nested-frame"))
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    backend.start()
    try:
        assert execute_operation(_nav(url), backend=backend).verdict is Verdict.VERIFIED
        # The nested document's script intentionally registers after its
        # controls; wait for its ordinary declared-load window before clicking.
        backend.page.wait_for_timeout(500)
        click = execute_operation(
            Operation(
                "nested-click", url,
                Action(ActionType.CLICK, locator=_tid("nested-frame-click"), frame_path=path),
                expectations=[Expectation(
                    ExpectationType.TEXT, locator=_tid("nested-frame-status"),
                    text_value="clicked", frame_path=path,
                )],
            ),
            backend=backend,
        )
        assert click.verdict is Verdict.VERIFIED
        assert click.target_resolution is not None
        assert click.target_resolution["frame_path_depth"] == 2
        assert len(click.target_resolution["resolved_frame_hops"]) == 2
        assert click.target_resolution["failure_hop"] is None

        fill = execute_operation(
            Operation(
                "nested-fill", url,
                Action(ActionType.FILL, locator=_tid("nested-frame-input"), text="nested-value", frame_path=path),
                expectations=[Expectation(
                    ExpectationType.ATTRIBUTE, locator=_tid("nested-frame-input"),
                    frame_path=path, attribute_name="value", attribute_value="nested-value",
                )],
            ),
            backend=backend,
        )
        assert fill.verdict is Verdict.VERIFIED

        selected = execute_operation(
            Operation(
                "nested-select", url,
                Action(ActionType.SELECT_OPTION, locator=_tid("nested-frame-select"), option_value="nested", frame_path=path),
                expectations=[Expectation(
                    ExpectationType.ATTRIBUTE, locator=_tid("nested-frame-select"),
                    frame_path=path, attribute_name="value", attribute_value="nested",
                )],
            ),
            backend=backend,
        )
        assert selected.verdict is Verdict.VERIFIED
        assert selected.browser["browser_session_id"] == click.browser["browser_session_id"]
    finally:
        backend.stop()


@pytest.mark.parametrize(
    ("path", "expected_kind", "expected_hop"),
    [
        ((_tid("missing-outer"), _tid("nested-frame")), "missing_frame", 0),
        ((_tid("unique-frame"), _tid("missing-inner")), "missing_frame", 1),
        ((_tid("unique-frame"), _tid("ambiguous-inner-frame")), "ambiguous_frame", 1),
    ],
)
def test_nested_frame_path_missing_and_ambiguous_hops_fail_closed(
    fixture_url, path, expected_kind, expected_hop
):
    url = _host_url(fixture_url)
    receipt = execute_operation(
        Operation(
            "nested-frame-failure", url,
            Action(ActionType.CLICK, locator=_tid("nested-frame-click"), frame_path=path),
            expectations=[], locate_retry_ms=0,
        )
    )
    assert receipt.verdict is Verdict.EXECUTION_FAILED
    assert receipt.failure_kind == expected_kind
    assert receipt.target_resolution is not None
    assert receipt.target_resolution["failure_hop"] == expected_hop


def test_nested_frame_reloads_are_resolved_freshly_before_next_operation(fixture_url):
    url = _host_url(fixture_url)
    path = (_tid("unique-frame"), _tid("nested-frame"))
    backend = PlaywrightBackend()
    backend.start()
    try:
        assert execute_operation(_nav(url), backend=backend).verdict is Verdict.VERIFIED
        reload_receipt = execute_operation(
            Operation(
                "reload-inner", url,
                Action(ActionType.CLICK, locator=_tid("reload-nested-frame"), frame=_tid("unique-frame")),
                expectations=[],
            ),
            backend=backend,
        )
        assert reload_receipt.action_executed_successfully is True
        backend.page.wait_for_timeout(300)
        filled = execute_operation(
            Operation(
                "fill-after-reload", url,
                Action(ActionType.FILL, locator=_tid("nested-frame-input"), text="fresh", frame_path=path),
                expectations=[Expectation(
                    ExpectationType.ATTRIBUTE, locator=_tid("nested-frame-input"),
                    frame_path=path, attribute_name="value", attribute_value="fresh",
                )],
                locate_retry_ms=2_000,
            ),
            backend=backend,
        )
        assert filled.verdict is Verdict.VERIFIED
        assert filled.target_resolution["frame_path_depth"] == 2
    finally:
        backend.stop()


def test_nested_frame_path_is_reresolved_after_pre_action_observation(fixture_url):
    """A reload after a declared observation cannot reuse a stale Frame handle."""
    url = _host_url(fixture_url)
    path = (_tid("unique-frame"), _tid("nested-frame"))
    backend = PlaywrightBackend()
    backend.start()
    try:
        assert execute_operation(_nav(url), backend=backend).verdict is Verdict.VERIFIED
        original_read = backend.read_element_state
        reloaded = False

        def reload_after_observation(*args, **kwargs):
            nonlocal reloaded
            state = original_read(*args, **kwargs)
            if not reloaded and kwargs.get("frame_path") == path:
                reloaded = True
                backend.page.frame_locator('iframe[data-testid="unique-frame"]').get_by_test_id(
                    "reload-nested-frame"
                ).click()
                backend.page.wait_for_timeout(300)
            return state

        with patch.object(backend, "read_element_state", side_effect=reload_after_observation):
            receipt = execute_operation(
                Operation(
                    "fresh-after-precondition", url,
                    Action(
                        ActionType.FILL,
                        locator=_tid("nested-frame-input"),
                        text="fresh-after-observation",
                        frame_path=path,
                    ),
                    expectations=[
                        Expectation(
                            ExpectationType.ATTRIBUTE,
                            locator=_tid("nested-frame-input"),
                            frame_path=path,
                            attribute_name="value",
                            attribute_value="fresh-after-observation",
                        )
                    ],
                    page_precondition=PagePrecondition(
                        (
                            PageCondition(
                                "nested-input-visible",
                                PageConditionType.ELEMENT_VISIBLE,
                                locator=_tid("nested-frame-input"),
                                frame_path=path,
                            ),
                        )
                    ),
                    locate_retry_ms=2_000,
                ),
                backend=backend,
            )
        assert reloaded is True
        assert receipt.verdict is Verdict.VERIFIED
        assert receipt.target_resolution["frame_path_depth"] == 2
    finally:
        backend.stop()
