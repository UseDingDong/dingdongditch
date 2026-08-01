"""Unit tests for plan timing contracts and video_ended adaptive math."""

from __future__ import annotations

import math

import pytest

from dingdongditch.contract.operation import Action, ActionType, Operation
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.runtime.plan_timing import (
    VIDEO_ENDED_ADAPTIVE_MARGIN_MS,
    PlanTimingState,
    apply_extension_decision,
    compute_video_ended_extension,
)


def _op(oid: str = "a") -> Operation:
    return Operation(
        operation_id=oid,
        url="https://example.com",
        action=Action(type=ActionType.NAVIGATE),
    )


def test_plan_timing_requires_budgets_when_adaptive_enabled():
    with pytest.raises(ValueError, match="initial_plan_timeout_ms"):
        ExecutionPlan(
            plan_id="p",
            operations=[_op()],
            adaptive_timeout_enabled=True,
            max_plan_timeout_ms=5_000,
        ).validate()
    with pytest.raises(ValueError, match="max_plan_timeout_ms"):
        ExecutionPlan(
            plan_id="p",
            operations=[_op()],
            adaptive_timeout_enabled=True,
            initial_plan_timeout_ms=1_000,
        ).validate()


def test_plan_timing_rejects_max_below_initial():
    with pytest.raises(ValueError, match="max_plan_timeout_ms must be >="):
        ExecutionPlan(
            plan_id="p",
            operations=[_op()],
            initial_plan_timeout_ms=5_000,
            max_plan_timeout_ms=1_000,
        ).validate()


def test_plan_timing_fixed_budget_without_adaptive_ok():
    ExecutionPlan(
        plan_id="p",
        operations=[_op()],
        initial_plan_timeout_ms=2_000,
        adaptive_timeout_enabled=False,
        max_plan_timeout_ms=2_000,
    ).validate()


def test_adaptation_disabled_never_grants():
    state = PlanTimingState.from_plan(
        initial_plan_timeout_ms=500,
        adaptive_timeout_enabled=False,
        max_plan_timeout_ms=5_000,
        plan_started_at_ms=1_000,
    )
    decision = compute_video_ended_extension(
        observed={
            "duration": 10.0,
            "currentTime": 0.0,
            "playbackRate": 1.0,
            "loop": False,
            "ended": False,
            "paused": False,
            "readyState": 4,
        },
        now_ms=1_100,
        wait_deadline_ms=1_200,
        plan_timing=state,
    )
    assert decision.extension_reason == "adaptation_disabled"
    assert decision.granted_extension_ms == 0


def test_finite_duration_requests_remaining_plus_margin():
    state = PlanTimingState.from_plan(
        initial_plan_timeout_ms=200,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        plan_started_at_ms=0,
    )
    decision = compute_video_ended_extension(
        observed={
            "duration": 5.0,
            "currentTime": 1.0,
            "playbackRate": 1.0,
            "loop": False,
            "ended": False,
            "paused": False,
            "readyState": 4,
        },
        now_ms=50,
        wait_deadline_ms=200,
        plan_timing=state,
    )
    assert decision.extension_reason == "video_ended_remaining_playback"
    assert decision.observed_duration == 5.0
    assert decision.observed_current_time == 1.0
    assert decision.observed_playback_rate == 1.0
    expected_needed = int(math.ceil(4.0 * 1000.0)) + VIDEO_ENDED_ADAPTIVE_MARGIN_MS
    assert decision.requested_extension_ms == max(0, (50 + expected_needed) - 200)
    assert decision.granted_extension_ms == decision.requested_extension_ms
    assert decision.ceiling_prevented_full_extension is False


def test_partial_playback_and_rate_reduce_request():
    state = PlanTimingState.from_plan(
        initial_plan_timeout_ms=100,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        plan_started_at_ms=0,
    )
    mid = compute_video_ended_extension(
        observed={
            "duration": 4.0,
            "currentTime": 3.0,
            "playbackRate": 1.0,
            "loop": False,
            "ended": False,
            "paused": False,
            "readyState": 4,
        },
        now_ms=0,
        wait_deadline_ms=50,
        plan_timing=state,
    )
    fast = compute_video_ended_extension(
        observed={
            "duration": 4.0,
            "currentTime": 0.0,
            "playbackRate": 2.0,
            "loop": False,
            "ended": False,
            "paused": False,
            "readyState": 4,
        },
        now_ms=0,
        wait_deadline_ms=50,
        plan_timing=state,
    )
    assert mid.requested_extension_ms < fast.requested_extension_ms
    # 4s at 2x => 2s remaining wall time (+ margin)
    assert fast.requested_extension_ms == (2_000 + VIDEO_ENDED_ADAPTIVE_MARGIN_MS) - 50


def test_short_remaining_needs_no_extension():
    state = PlanTimingState.from_plan(
        initial_plan_timeout_ms=30_000,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        plan_started_at_ms=0,
    )
    decision = compute_video_ended_extension(
        observed={
            "duration": 1.0,
            "currentTime": 0.0,
            "playbackRate": 1.0,
            "loop": False,
            "ended": False,
            "paused": False,
            "readyState": 4,
        },
        now_ms=0,
        wait_deadline_ms=20_000,
        plan_timing=state,
    )
    assert decision.extension_reason == "no_extension_needed"
    assert decision.granted_extension_ms == 0


def test_max_ceiling_caps_extension():
    state = PlanTimingState.from_plan(
        initial_plan_timeout_ms=200,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=1_000,
        plan_started_at_ms=0,
    )
    decision = compute_video_ended_extension(
        observed={
            "duration": 30.0,
            "currentTime": 0.0,
            "playbackRate": 1.0,
            "loop": False,
            "ended": False,
            "paused": False,
            "readyState": 4,
        },
        now_ms=0,
        wait_deadline_ms=200,
        plan_timing=state,
    )
    assert decision.ceiling_prevented_full_extension is True
    assert decision.extension_reason == "video_ended_remaining_playback_capped"
    assert decision.granted_extension_ms == 800  # ceiling 1000 - wait 200
    assert decision.resulting_wait_deadline_ms == 1_000
    assert decision.resulting_plan_deadline_ms == 1_000


@pytest.mark.parametrize(
    "observed,reason",
    [
        (
            {
                "duration": float("inf"),
                "currentTime": 0.0,
                "playbackRate": 1.0,
                "loop": False,
                "ended": False,
                "paused": False,
                "readyState": 4,
            },
            "infinite_duration",
        ),
        (
            {
                "duration": float("nan"),
                "currentTime": 0.0,
                "playbackRate": 1.0,
                "loop": False,
                "ended": False,
                "paused": False,
                "readyState": 4,
            },
            "nan_duration",
        ),
        (
            {
                "duration": 0.0,
                "currentTime": 0.0,
                "playbackRate": 1.0,
                "loop": False,
                "ended": False,
                "paused": False,
                "readyState": 4,
            },
            "zero_duration",
        ),
        (
            {
                "duration": 5.0,
                "currentTime": 0.0,
                "playbackRate": 1.0,
                "loop": True,
                "ended": False,
                "paused": False,
                "readyState": 4,
            },
            "looping_media",
        ),
        (
            {
                "duration": 5.0,
                "currentTime": 0.0,
                "playbackRate": 1.0,
                "loop": False,
                "ended": False,
                "paused": True,
                "readyState": 4,
            },
            "never_started",
        ),
        (
            {
                "duration": 5.0,
                "currentTime": 1.0,
                "playbackRate": 1.0,
                "loop": False,
                "ended": False,
                "paused": False,
                "readyState": 0,
            },
            "stalled_or_no_metadata",
        ),
    ],
)
def test_untrusted_media_facts_do_not_extend(observed, reason):
    state = PlanTimingState.from_plan(
        initial_plan_timeout_ms=200,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        plan_started_at_ms=0,
    )
    decision = compute_video_ended_extension(
        observed=observed,
        now_ms=0,
        wait_deadline_ms=200,
        plan_timing=state,
    )
    assert decision.extension_reason == reason
    assert decision.granted_extension_ms == 0


def test_apply_extension_is_monotonic():
    state = PlanTimingState.from_plan(
        initial_plan_timeout_ms=200,
        adaptive_timeout_enabled=True,
        max_plan_timeout_ms=60_000,
        plan_started_at_ms=0,
    )
    original_plan = state.plan_deadline_ms
    decision = compute_video_ended_extension(
        observed={
            "duration": 3.0,
            "currentTime": 0.0,
            "playbackRate": 1.0,
            "loop": False,
            "ended": False,
            "paused": False,
            "readyState": 4,
        },
        now_ms=10,
        wait_deadline_ms=200,
        plan_timing=state,
    )
    new_wait = apply_extension_decision(
        decision=decision, wait_deadline_ms=200, plan_timing=state
    )
    assert new_wait >= 200
    assert state.plan_deadline_ms >= original_plan
    assert len(state.decisions) == 1
    summary = state.summary_dict()
    assert summary["initial_plan_budget_ms"] == 200
    assert summary["original_deadline_ms"] == original_plan
    assert summary["resulting_deadline_ms"] == state.plan_deadline_ms
    assert summary["extension_decisions"][0]["extension_reason"] == (
        "video_ended_remaining_playback"
    )
