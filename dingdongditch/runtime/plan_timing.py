"""Bounded plan-deadline state and video_ended adaptive extension math.

Monotonic-clock only. No site-specific logic. Extension is fail-closed and
limited to explicitly supported wait conditions (currently video_ended).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from dingdongditch.contract.runtime import (
    MAX_PLAN_TIMEOUT_MS_CEILING,
    MIN_PLAN_TIMEOUT_MS,
)

# Bounded cushion for buffering / ended-event delivery after projected end.
VIDEO_ENDED_ADAPTIVE_MARGIN_MS = 2_000

@dataclass
class TimingExtensionDecision:
    """One adaptive timing decision for receipts."""

    condition_type: str
    extension_reason: str
    observed_duration: float | None = None
    observed_current_time: float | None = None
    observed_playback_rate: float | None = None
    requested_extension_ms: int = 0
    granted_extension_ms: int = 0
    original_wait_deadline_ms: int | None = None
    resulting_wait_deadline_ms: int | None = None
    original_plan_deadline_ms: int | None = None
    resulting_plan_deadline_ms: int | None = None
    max_plan_timeout_ms: int | None = None
    ceiling_prevented_full_extension: bool = False
    adaptive_timeout_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_type": self.condition_type,
            "extension_reason": self.extension_reason,
            "observed_duration": self.observed_duration,
            "observed_current_time": self.observed_current_time,
            "observed_playback_rate": self.observed_playback_rate,
            "requested_extension_ms": self.requested_extension_ms,
            "granted_extension_ms": self.granted_extension_ms,
            "original_wait_deadline_ms": self.original_wait_deadline_ms,
            "resulting_wait_deadline_ms": self.resulting_wait_deadline_ms,
            "original_plan_deadline_ms": self.original_plan_deadline_ms,
            "resulting_plan_deadline_ms": self.resulting_plan_deadline_ms,
            "max_plan_timeout_ms": self.max_plan_timeout_ms,
            "ceiling_prevented_full_extension": self.ceiling_prevented_full_extension,
            "adaptive_timeout_enabled": self.adaptive_timeout_enabled,
        }


@dataclass
class PlanTimingState:
    """Mutable overall plan deadline shared across steps (monotonic ms)."""

    initial_plan_timeout_ms: int | None
    adaptive_timeout_enabled: bool
    max_plan_timeout_ms: int | None
    plan_started_at_ms: int
    plan_deadline_ms: int | None
    decisions: list[TimingExtensionDecision] = field(default_factory=list)

    @classmethod
    def from_plan(
        cls,
        *,
        initial_plan_timeout_ms: int | None,
        adaptive_timeout_enabled: bool,
        max_plan_timeout_ms: int | None,
        plan_started_at_ms: int,
    ) -> PlanTimingState:
        deadline = None
        if initial_plan_timeout_ms is not None:
            deadline = plan_started_at_ms + initial_plan_timeout_ms
        return cls(
            initial_plan_timeout_ms=initial_plan_timeout_ms,
            adaptive_timeout_enabled=adaptive_timeout_enabled,
            max_plan_timeout_ms=max_plan_timeout_ms,
            plan_started_at_ms=plan_started_at_ms,
            plan_deadline_ms=deadline,
        )

    def plan_ceiling_ms(self) -> int | None:
        if self.max_plan_timeout_ms is None:
            return None
        return self.plan_started_at_ms + self.max_plan_timeout_ms

    def expired(self, now_ms: int) -> bool:
        if self.plan_deadline_ms is None:
            return False
        return now_ms >= self.plan_deadline_ms

    def summary_dict(self) -> dict[str, Any]:
        return {
            "initial_plan_budget_ms": self.initial_plan_timeout_ms,
            "original_deadline_ms": (
                None
                if self.initial_plan_timeout_ms is None
                else self.plan_started_at_ms + self.initial_plan_timeout_ms
            ),
            "resulting_deadline_ms": self.plan_deadline_ms,
            "max_plan_timeout_ms": self.max_plan_timeout_ms,
            "adaptive_timeout_enabled": self.adaptive_timeout_enabled,
            "plan_started_at_ms": self.plan_started_at_ms,
            "extension_decisions": [d.to_dict() for d in self.decisions],
        }


def _is_finite_number(value: Any) -> bool:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(n)


def compute_video_ended_extension(
    *,
    observed: dict[str, Any],
    now_ms: int,
    wait_deadline_ms: int,
    plan_timing: PlanTimingState | None,
    margin_ms: int = VIDEO_ENDED_ADAPTIVE_MARGIN_MS,
) -> TimingExtensionDecision:
    """Decide whether video_ended may extend wait and plan deadlines.

    Returns a decision; caller applies granted_extension_ms to deadlines.
    """
    enabled = bool(plan_timing and plan_timing.adaptive_timeout_enabled)
    base = TimingExtensionDecision(
        condition_type="video_ended",
        extension_reason="adaptation_disabled",
        original_wait_deadline_ms=wait_deadline_ms,
        resulting_wait_deadline_ms=wait_deadline_ms,
        original_plan_deadline_ms=(
            plan_timing.plan_deadline_ms if plan_timing else None
        ),
        resulting_plan_deadline_ms=(
            plan_timing.plan_deadline_ms if plan_timing else None
        ),
        max_plan_timeout_ms=(
            plan_timing.max_plan_timeout_ms if plan_timing else None
        ),
        adaptive_timeout_enabled=enabled,
    )

    if plan_timing is None or not plan_timing.adaptive_timeout_enabled:
        return base

    duration = observed.get("duration")
    current_time = observed.get("currentTime")
    playback_rate = observed.get("playbackRate")
    loop = observed.get("loop")
    ended = bool(observed.get("ended"))
    paused = bool(observed.get("paused"))

    base.observed_duration = float(duration) if _is_finite_number(duration) else None
    base.observed_current_time = (
        float(current_time) if _is_finite_number(current_time) else None
    )
    base.observed_playback_rate = (
        float(playback_rate) if _is_finite_number(playback_rate) else None
    )

    if ended:
        base.extension_reason = "already_ended"
        return base

    if loop is True:
        base.extension_reason = "looping_media"
        return base

    if not _is_finite_number(duration):
        # Infinity / NaN / missing
        raw = observed.get("duration")
        if isinstance(raw, float) and math.isinf(raw):
            base.extension_reason = "infinite_duration"
        elif raw is not None and (
            (isinstance(raw, float) and math.isnan(raw))
            or str(raw).lower() == "nan"
        ):
            base.extension_reason = "nan_duration"
        else:
            base.extension_reason = "invalid_duration"
        return base

    duration_f = float(duration)
    if duration_f <= 0:
        base.extension_reason = "zero_duration"
        return base

    if not _is_finite_number(playback_rate) or float(playback_rate) <= 0:
        base.extension_reason = "invalid_playback_rate"
        return base

    rate_f = float(playback_rate)
    current_f = float(current_time) if _is_finite_number(current_time) else 0.0

    # Never-started: paused at t=0 with no ended signal.
    if paused and current_f <= 0.0:
        base.extension_reason = "never_started"
        return base

    # Stalled / not enough data to trust duration for budgeting.
    ready_state = observed.get("readyState")
    if _is_finite_number(ready_state) and int(ready_state) < 1:
        base.extension_reason = "stalled_or_no_metadata"
        return base

    remaining_sec = max(0.0, (duration_f - current_f) / rate_f)
    needed_ms = int(math.ceil(remaining_sec * 1000.0)) + int(margin_ms)
    target_deadline = now_ms + needed_ms

    # How much the wait deadline still needs.
    wait_request = max(0, target_deadline - wait_deadline_ms)
    plan_request = 0
    if plan_timing.plan_deadline_ms is not None:
        plan_request = max(0, target_deadline - plan_timing.plan_deadline_ms)
    requested = max(wait_request, plan_request)
    base.requested_extension_ms = requested

    if requested <= 0:
        base.extension_reason = "no_extension_needed"
        return base

    ceiling = plan_timing.plan_ceiling_ms()
    # Cap the resulting wait/plan deadlines by plan ceiling when present.
    max_wait_deadline = target_deadline
    max_plan_deadline = target_deadline
    capped = False
    if ceiling is not None:
        if max_wait_deadline > ceiling:
            capped = True
            max_wait_deadline = ceiling
        if plan_timing.plan_deadline_ms is not None and max_plan_deadline > ceiling:
            capped = True
            max_plan_deadline = ceiling

    granted_wait = max(0, max_wait_deadline - wait_deadline_ms)
    granted_plan = 0
    if plan_timing.plan_deadline_ms is not None:
        granted_plan = max(0, max_plan_deadline - plan_timing.plan_deadline_ms)
    granted = max(granted_wait, granted_plan)

    base.granted_extension_ms = granted
    base.ceiling_prevented_full_extension = capped and granted < requested
    if granted <= 0:
        base.extension_reason = (
            "ceiling_blocks_extension" if capped else "no_extension_needed"
        )
        return base

    base.extension_reason = (
        "video_ended_remaining_playback_capped"
        if base.ceiling_prevented_full_extension
        else "video_ended_remaining_playback"
    )
    base.resulting_wait_deadline_ms = wait_deadline_ms + granted_wait
    if plan_timing.plan_deadline_ms is not None:
        base.resulting_plan_deadline_ms = plan_timing.plan_deadline_ms + granted_plan
    return base


def apply_extension_decision(
    *,
    decision: TimingExtensionDecision,
    wait_deadline_ms: int,
    plan_timing: PlanTimingState | None,
) -> int:
    """Apply a granted extension to wait deadline and plan timing state."""
    new_wait = wait_deadline_ms
    if decision.granted_extension_ms > 0:
        if decision.resulting_wait_deadline_ms is not None:
            new_wait = max(wait_deadline_ms, decision.resulting_wait_deadline_ms)
        if (
            plan_timing is not None
            and plan_timing.plan_deadline_ms is not None
            and decision.resulting_plan_deadline_ms is not None
        ):
            plan_timing.plan_deadline_ms = max(
                plan_timing.plan_deadline_ms, decision.resulting_plan_deadline_ms
            )
    if plan_timing is not None:
        plan_timing.decisions.append(decision)
    return new_wait
