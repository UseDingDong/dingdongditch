"""Integration tests for wait_for video_ended."""

from __future__ import annotations

import pytest

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
)
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.verdict import Verdict
from dingdongditch.contract.wait import WaitCondition, WaitConditionType
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan


def _cfg(engine: BrowserEngine) -> BrowserConfig:
    return BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=engine,
        channel=BrowserChannel.BUNDLED,
        headless=True,
    )


def _tid(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def _wait_video_ready(url: str) -> Operation:
    return Operation(
        operation_id="wait-video-ready",
        url=url,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_timeout_ms=20_000,
            wait_condition=WaitCondition(
                type=WaitConditionType.TEXT_PRESENT,
                locator=_tid("video-ready"),
                text_value="video-ready",
                text_match=TextMatchMode.EXACT,
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.TEXT,
                locator=_tid("video-ready"),
                text_value="video-ready",
                text_match=TextMatchMode.EXACT,
            )
        ],
    )


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
    ids=["chromium", "firefox", "webkit"],
)
def test_video_ended_verified_after_playback(fixture_url, engine):
    plan = ExecutionPlan(
        plan_id=f"video-ended-ok-{engine.value}",
        browser_config=_cfg(engine),
        operations=[
            Operation(
                operation_id="nav",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="index.html",
                        url_match=UrlMatchMode.CONTAINS,
                    )
                ],
            ),
            _wait_video_ready(fixture_url),
            Operation(
                operation_id="play",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK, locator=_tid("play-ending-video")
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ELEMENT_EXISTS,
                        locator=_tid("play-ending-video"),
                        exists=True,
                    )
                ],
            ),
            Operation(
                operation_id="wait-ended",
                url=fixture_url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=15_000,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.VIDEO_ENDED,
                        locator=_tid("ending-video"),
                    ),
                ),
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict.value == "VERIFIED"
    ended = next(s for s in receipt.steps if s.operation_id == "wait-ended")
    assert ended.operation_verdict == Verdict.VERIFIED.value
    assert ended.receipt is not None
    assert ended.receipt.action_evidence["condition_satisfied"] is True
    assert ended.receipt.action_evidence["final_observed_state"]["ended"] is True


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
    ids=["chromium", "firefox", "webkit"],
)
def test_video_ended_timeout_when_never_starts(fixture_url, engine):
    backend = PlaywrightBackend(browser_config=_cfg(engine))
    try:
        execute_operation(
            Operation(
                operation_id="nav",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[],
            ),
            backend=backend,
        )
        execute_operation(_wait_video_ready(fixture_url), backend=backend)
        wait = execute_operation(
            Operation(
                operation_id="wait-ended",
                url=fixture_url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=400,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.VIDEO_ENDED,
                        locator=_tid("never-play-video"),
                    ),
                ),
            ),
            backend=backend,
        )
        assert wait.verdict == Verdict.NOT_VERIFIED
        assert wait.action_evidence["timeout_occurred"] is True
        assert wait.action_evidence["condition_satisfied"] is False
    finally:
        backend.stop()


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
    ids=["chromium", "firefox", "webkit"],
)
def test_video_ended_timeout_when_interrupted(fixture_url, engine):
    plan = ExecutionPlan(
        plan_id=f"video-interrupted-{engine.value}",
        browser_config=_cfg(engine),
        operations=[
            Operation(
                operation_id="nav",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="index.html",
                        url_match=UrlMatchMode.CONTAINS,
                    )
                ],
            ),
            _wait_video_ready(fixture_url),
            Operation(
                operation_id="interrupt",
                url=fixture_url,
                action=Action(
                    type=ActionType.CLICK, locator=_tid("interrupt-ending-video")
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ELEMENT_EXISTS,
                        locator=_tid("interrupt-ending-video"),
                        exists=True,
                    )
                ],
            ),
            Operation(
                operation_id="wait-ended",
                url=fixture_url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=1_500,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.VIDEO_ENDED,
                        locator=_tid("ending-video"),
                    ),
                ),
            ),
        ],
    )
    receipt = execute_plan(plan)
    ended = next(s for s in receipt.steps if s.operation_id == "wait-ended")
    assert ended.attempted is True
    assert ended.operation_verdict == Verdict.NOT_VERIFIED.value
    assert ended.receipt is not None
    assert ended.receipt.action_evidence["timeout_occurred"] is True
    assert ended.receipt.action_evidence["final_observed_state"]["ended"] is False
    assert receipt.plan_verdict.value == "NOT_VERIFIED"

def test_video_ended_ambiguous_fails_closed(fixture_url):
    backend = PlaywrightBackend(browser_config=_cfg(BrowserEngine.CHROMIUM))
    try:
        execute_operation(
            Operation(
                operation_id="nav",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[],
            ),
            backend=backend,
        )
        execute_operation(_wait_video_ready(fixture_url), backend=backend)
        wait = execute_operation(
            Operation(
                operation_id="wait-amb",
                url=fixture_url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=2_000,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.VIDEO_ENDED,
                        locator=_tid("ambiguous-video"),
                    ),
                ),
            ),
            backend=backend,
        )
        assert wait.verdict == Verdict.EXECUTION_FAILED
        assert wait.failure_kind in (
            "multiple_after_primary",
            "multiple_after_constraints",
        )
    finally:
        backend.stop()


def test_video_ended_non_video_target_rejected(fixture_url):
    backend = PlaywrightBackend(browser_config=_cfg(BrowserEngine.CHROMIUM))
    try:
        execute_operation(
            Operation(
                operation_id="nav",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[],
            ),
            backend=backend,
        )
        wait = execute_operation(
            Operation(
                operation_id="wait-button",
                url=fixture_url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=1_000,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.VIDEO_ENDED,
                        locator=_tid("noop-control"),
                    ),
                ),
            ),
            backend=backend,
        )
        assert wait.verdict == Verdict.EXECUTION_FAILED
        assert wait.failure_kind == "target_not_video"
    finally:
        backend.stop()


def test_video_ended_missing_target_fails_validation():
    with pytest.raises(ValueError, match="requires a locator"):
        Action(
            type=ActionType.WAIT_FOR,
            wait_condition=WaitCondition(type=WaitConditionType.VIDEO_ENDED),
        ).validate()
