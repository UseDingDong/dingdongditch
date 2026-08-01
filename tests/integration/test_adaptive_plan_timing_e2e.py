"""Integration tests for adaptive plan timing (video_ended)."""

from __future__ import annotations

import pytest

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
from dingdongditch.contract.plan import ExecutionPlan, PlanFailureKind, PlanVerdict
from dingdongditch.contract.verdict import Verdict
from dingdongditch.contract.wait import WaitCondition, WaitConditionType
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


def _nav(url: str) -> Operation:
    return Operation(
        operation_id="nav",
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


def _click(url: str, test_id: str, op_id: str) -> Operation:
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


def _wait_video_ended(
    url: str, *, timeout_ms: int, video_id: str = "ending-video"
) -> Operation:
    return Operation(
        operation_id="wait-ended",
        url=url,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_timeout_ms=timeout_ms,
            wait_condition=WaitCondition(
                type=WaitConditionType.VIDEO_ENDED,
                locator=_tid(video_id),
            ),
        ),
    )


def test_invalid_plan_timing_fails_before_browser(fixture_url):
    plan = ExecutionPlan(
        plan_id="bad-timing",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        adaptive_timeout_enabled=True,
        initial_plan_timeout_ms=1_000,
        operations=[_nav(fixture_url)],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.EXECUTION_FAILED
    assert receipt.failure_kind == PlanFailureKind.INVALID_PLAN_TIMING.value
    assert receipt.browser_session_id is None


def test_fixed_plan_budget_without_adaptation(fixture_url):
    plan = ExecutionPlan(
        plan_id="fixed-budget",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=1_500,
        adaptive_timeout_enabled=False,
        max_plan_timeout_ms=1_500,
        operations=[
            _nav(fixture_url),
            _wait_video_ended(
                fixture_url, timeout_ms=10_000, video_id="never-play-video"
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.NOT_VERIFIED
    assert receipt.failure_kind == PlanFailureKind.PLAN_DEADLINE_EXPIRED.value
    timing = receipt.plan_timing
    assert timing is not None
    assert timing["adaptive_timeout_enabled"] is False
    assert timing["initial_plan_budget_ms"] == 1_500
    assert timing["extension_decisions"] == []


def test_adaptation_disabled_does_not_extend_video_wait(fixture_url):
    plan = ExecutionPlan(
        plan_id="adapt-off",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=30_000,
        adaptive_timeout_enabled=False,
        max_plan_timeout_ms=60_000,
        operations=[
            _nav(fixture_url),
            _wait_video_ready(fixture_url),
            _click(fixture_url, "play-ending-video", "play"),
            _wait_video_ended(fixture_url, timeout_ms=100),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.NOT_VERIFIED
    timing = receipt.plan_timing
    assert timing is not None
    assert timing["extension_decisions"] == []
    ended = next(s for s in receipt.steps if s.operation_id == "wait-ended")
    assert ended.receipt is not None
    assert ended.receipt.action_evidence.get("timeout_occurred") is True


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
    ids=["chromium", "firefox", "webkit"],
)
def test_finite_video_extends_wait_and_plan(fixture_url, engine):
    plan = ExecutionPlan(
        plan_id=f"adapt-extend-{engine.value}",
        browser_config=_cfg(engine),
        initial_plan_timeout_ms=30_000,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        operations=[
            _nav(fixture_url),
            _wait_video_ready(fixture_url),
            _click(fixture_url, "play-ending-video", "play"),
            _wait_video_ended(fixture_url, timeout_ms=100),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED, (
        receipt.failure_kind,
        receipt.plan_timing,
    )
    timing = receipt.plan_timing
    assert timing is not None
    grants = [d for d in timing["extension_decisions"] if d["granted_extension_ms"] > 0]
    assert grants, timing
    grant = grants[0]
    assert grant["extension_reason"] in (
        "video_ended_remaining_playback",
        "video_ended_remaining_playback_capped",
    )
    assert grant["observed_duration"] is not None
    assert grant["observed_duration"] > 0
    assert grant["observed_current_time"] is not None
    assert grant["observed_playback_rate"] is not None
    assert grant["requested_extension_ms"] > 0
    assert grant["max_plan_timeout_ms"] == 60_000
    assert timing["resulting_deadline_ms"] >= timing["original_deadline_ms"]
    ended = next(s for s in receipt.steps if s.operation_id == "wait-ended")
    assert ended.operation_verdict == Verdict.VERIFIED.value
    assert ended.receipt is not None
    assert "adaptive_timing" in ended.receipt.action_evidence


def test_partial_playback_extends_using_remaining(fixture_url):
    plan = ExecutionPlan(
        plan_id="adapt-mid",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=30_000,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        operations=[
            _nav(fixture_url),
            _wait_video_ready(fixture_url),
            _click(fixture_url, "play-ending-video-mid", "play"),
            _wait_video_ended(fixture_url, timeout_ms=250),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    grant = next(
        d
        for d in receipt.plan_timing["extension_decisions"]
        if d["granted_extension_ms"] > 0
    )
    assert grant["observed_current_time"] > 0


def test_playback_rate_affects_estimate(fixture_url):
    plan = ExecutionPlan(
        plan_id="adapt-fast",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=30_000,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        operations=[
            _nav(fixture_url),
            _wait_video_ready(fixture_url),
            _click(fixture_url, "play-ending-video-fast", "play"),
            _wait_video_ended(fixture_url, timeout_ms=100),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    # Rate is observed during adaptation and/or final state.
    decisions = receipt.plan_timing["extension_decisions"]
    rates = [
        d.get("observed_playback_rate")
        for d in decisions
        if d.get("observed_playback_rate") is not None
    ]
    ended = next(s for s in receipt.steps if s.operation_id == "wait-ended")
    final = ended.receipt.action_evidence.get("final_observed_state") or {}
    assert 2.0 in rates or final.get("playbackRate") == 2.0


def test_short_video_with_ample_budget_needs_no_extension(fixture_url):
    plan = ExecutionPlan(
        plan_id="adapt-ample",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=30_000,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        operations=[
            _nav(fixture_url),
            _wait_video_ready(fixture_url),
            _click(fixture_url, "play-ending-video", "play"),
            _wait_video_ended(fixture_url, timeout_ms=20_000),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    grants = [
        d
        for d in receipt.plan_timing["extension_decisions"]
        if d["granted_extension_ms"] > 0
    ]
    assert grants == []


def test_max_ceiling_caps_runtime_extension(fixture_url):
    # Medium clip needs more than max_plan_timeout_ms from plan start when the
    # wait budget is tiny; ceiling must cap the grant (may still VERIFIED if
    # real playback finishes under the capped deadline).
    plan = ExecutionPlan(
        plan_id="adapt-ceiling",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=5_000,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=5_500,
        operations=[
            _nav(fixture_url),
            _wait_video_ready(fixture_url),
            _click(fixture_url, "play-medium-ending-video", "play"),
            _wait_video_ended(
                fixture_url, timeout_ms=100, video_id="medium-ending-video"
            ),
        ],
    )
    receipt = execute_plan(plan)
    timing = receipt.plan_timing
    assert timing is not None
    assert timing["resulting_deadline_ms"] <= timing["plan_started_at_ms"] + 5_500
    capped = [
        d
        for d in timing["extension_decisions"]
        if d.get("ceiling_prevented_full_extension")
        or d.get("extension_reason")
        in (
            "video_ended_remaining_playback_capped",
            "ceiling_blocks_extension",
        )
    ]
    assert capped, timing["extension_decisions"]
    assert capped[0]["requested_extension_ms"] >= capped[0]["granted_extension_ms"]


def test_looping_media_does_not_extend(fixture_url):
    plan = ExecutionPlan(
        plan_id="adapt-loop",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=30_000,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        operations=[
            _nav(fixture_url),
            _wait_video_ready(fixture_url),
            _click(fixture_url, "play-looping-video", "play"),
            _wait_video_ended(fixture_url, timeout_ms=600, video_id="looping-video"),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.NOT_VERIFIED
    reasons = [d["extension_reason"] for d in receipt.plan_timing["extension_decisions"]]
    assert "looping_media" in reasons
    assert all(
        d["granted_extension_ms"] == 0 for d in receipt.plan_timing["extension_decisions"]
    )


def test_never_started_does_not_extend(fixture_url):
    plan = ExecutionPlan(
        plan_id="adapt-never",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=30_000,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        operations=[
            _nav(fixture_url),
            _wait_video_ready(fixture_url),
            _wait_video_ended(fixture_url, timeout_ms=500, video_id="never-play-video"),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.NOT_VERIFIED
    reasons = [d["extension_reason"] for d in receipt.plan_timing["extension_decisions"]]
    assert any(
        r
        in (
            "never_started",
            "nan_duration",
            "invalid_duration",
            "zero_duration",
            "stalled_or_no_metadata",
        )
        for r in reasons
    )
    assert all(
        d["granted_extension_ms"] == 0 for d in receipt.plan_timing["extension_decisions"]
    )


def test_plan_deadline_expires_cleanly(fixture_url):
    plan = ExecutionPlan(
        plan_id="deadline-clean",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        initial_plan_timeout_ms=800,
        adaptive_timeout_enabled=False,
        operations=[
            _nav(fixture_url),
            Operation(
                operation_id="wait-visible",
                url=fixture_url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=30_000,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.ELEMENT_VISIBLE,
                        locator=_tid("missing-never"),
                    ),
                ),
            ),
            _click(fixture_url, "play-ending-video", "should-skip"),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.NOT_VERIFIED
    assert receipt.failure_kind == PlanFailureKind.PLAN_DEADLINE_EXPIRED.value
    skipped = [s for s in receipt.steps if s.skipped]
    assert any(s.operation_id == "should-skip" for s in skipped)
