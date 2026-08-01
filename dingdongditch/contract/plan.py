"""Native ordered ExecutionPlan contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from dingdongditch.contract.browser import BrowserConfig, default_browser_config
from dingdongditch.contract.capabilities import RUNTIME_LIMITATIONS
from dingdongditch.contract.operation import Operation
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.runtime import (
    MAX_PLAN_TIMEOUT_MS_CEILING,
    MIN_PLAN_TIMEOUT_MS,
)
from dingdongditch.contract.verdict import Verdict


class FailurePolicy(str, Enum):
    """Only conservative stop-on-failure execution is supported."""

    STOP_ON_FAILURE = "stop_on_failure"


class PlanVerdict(str, Enum):
    """Plan-level truth — mirrors operation vocabulary; does not invent partial truth."""

    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INDETERMINATE = "INDETERMINATE"


class CompletionStatus(str, Enum):
    """Execution completeness — distinct from plan_verdict."""

    COMPLETED = "completed"
    STOPPED = "stopped"
    NOT_STARTED = "not_started"


class PlanFailureKind(str, Enum):
    EMPTY_PLAN_ID = "empty_plan_id"
    ZERO_OPERATIONS = "zero_operations"
    DUPLICATE_OPERATION_IDS = "duplicate_operation_ids"
    INVALID_OPERATION = "invalid_operation"
    INVALID_FAILURE_POLICY = "invalid_failure_policy"
    INVALID_PLAN_TIMING = "invalid_plan_timing"
    UNSUPPORTED_BROWSER = "unsupported_browser"
    BROWSER_SETUP_FAILED = "browser_setup_failed"
    STEP_STOPPED_PLAN = "step_stopped_plan"
    PLAN_DEADLINE_EXPIRED = "plan_deadline_expired"
    UNEXPECTED_EXCEPTION = "unexpected_exception"


class PlanValidationError(ValueError):
    def __init__(self, message: str, *, failure_kind: PlanFailureKind) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


STOPPING_VERDICTS = frozenset(
    {
        Verdict.NOT_VERIFIED,
        Verdict.EXECUTION_FAILED,
        Verdict.INDETERMINATE,
    }
)


@dataclass
class ExecutionPlan:
    """Host-declared ordered plan. DingDongDitch executes it; it does not invent or alter steps."""

    plan_id: str
    operations: list[Operation]
    browser_config: BrowserConfig = field(default_factory=default_browser_config)
    failure_policy: FailurePolicy = FailurePolicy.STOP_ON_FAILURE
    # Overall plan deadline (separate from per-action / per-wait timeouts).
    initial_plan_timeout_ms: int | None = None
    adaptive_timeout_enabled: bool = False
    max_plan_timeout_ms: int | None = None
    screenshot_config: Any | None = None

    def validate(self) -> None:
        if not self.plan_id or not str(self.plan_id).strip():
            raise PlanValidationError(
                "plan_id is required and must be non-empty",
                failure_kind=PlanFailureKind.EMPTY_PLAN_ID,
            )
        if not self.operations:
            raise PlanValidationError(
                "plan must declare at least one operation",
                failure_kind=PlanFailureKind.ZERO_OPERATIONS,
            )
        if self.failure_policy != FailurePolicy.STOP_ON_FAILURE:
            raise PlanValidationError(
                f"unsupported failure_policy: {self.failure_policy!r} "
                "(only stop_on_failure is supported)",
                failure_kind=PlanFailureKind.INVALID_FAILURE_POLICY,
            )
        ids = [op.operation_id for op in self.operations]
        if any(not oid for oid in ids):
            raise ValueError("every operation requires a non-empty operation_id")
        if len(ids) != len(set(ids)):
            raise PlanValidationError(
                "duplicate operation_id values within one plan",
                failure_kind=PlanFailureKind.DUPLICATE_OPERATION_IDS,
            )
        try:
            self._validate_plan_timing()
        except ValueError as exc:
            raise PlanValidationError(
                str(exc), failure_kind=PlanFailureKind.INVALID_PLAN_TIMING
            ) from exc
        self.browser_config.validate()
        from dingdongditch.contract.screenshot import ScreenshotConfig
        if self.screenshot_config is not None:
            if not isinstance(self.screenshot_config, ScreenshotConfig):
                raise ValueError("screenshot_config must be a ScreenshotConfig")
            self.screenshot_config.validate()
        for op in self.operations:
            op.validate()

    def _validate_plan_timing(self) -> None:
        if not isinstance(self.adaptive_timeout_enabled, bool):
            raise ValueError("adaptive_timeout_enabled must be a bool")

        def _check_budget(name: str, value: int | None) -> None:
            if value is None:
                return
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an int")
            if value < MIN_PLAN_TIMEOUT_MS:
                raise ValueError(f"{name} must be >= {MIN_PLAN_TIMEOUT_MS}")
            if value > MAX_PLAN_TIMEOUT_MS_CEILING:
                raise ValueError(
                    f"{name} must be <= {MAX_PLAN_TIMEOUT_MS_CEILING}"
                )

        _check_budget("initial_plan_timeout_ms", self.initial_plan_timeout_ms)
        _check_budget("max_plan_timeout_ms", self.max_plan_timeout_ms)

        if self.adaptive_timeout_enabled:
            if self.initial_plan_timeout_ms is None:
                raise ValueError(
                    "adaptive_timeout_enabled requires initial_plan_timeout_ms"
                )
            if self.max_plan_timeout_ms is None:
                raise ValueError(
                    "adaptive_timeout_enabled requires max_plan_timeout_ms"
                )
            if self.max_plan_timeout_ms < self.initial_plan_timeout_ms:
                raise ValueError(
                    "max_plan_timeout_ms must be >= initial_plan_timeout_ms"
                )
        elif self.max_plan_timeout_ms is not None and self.initial_plan_timeout_ms is None:
            raise ValueError(
                "max_plan_timeout_ms requires initial_plan_timeout_ms "
                "(or enable adaptive_timeout_enabled with both budgets)"
            )
        elif (
            self.max_plan_timeout_ms is not None
            and self.initial_plan_timeout_ms is not None
            and self.max_plan_timeout_ms < self.initial_plan_timeout_ms
        ):
            raise ValueError(
                "max_plan_timeout_ms must be >= initial_plan_timeout_ms"
            )

    def describe(self) -> dict[str, Any]:
        data = {
            "plan_id": self.plan_id,
            "browser_config": self.browser_config.describe(),
            "failure_policy": self.failure_policy.value,
            "operations": [op.operation_id for op in self.operations],
            "declared_step_count": len(self.operations),
            "adaptive_timeout_enabled": self.adaptive_timeout_enabled,
            "screenshot_config": self.screenshot_config.describe() if self.screenshot_config is not None else None,
        }
        if self.initial_plan_timeout_ms is not None:
            data["initial_plan_timeout_ms"] = self.initial_plan_timeout_ms
        if self.max_plan_timeout_ms is not None:
            data["max_plan_timeout_ms"] = self.max_plan_timeout_ms
        return data


@dataclass
class PlanStepRecord:
    step_index: int
    operation_id: str
    attempted: bool
    skipped: bool
    skip_reason: str | None = None
    operation_verdict: str | None = None
    failure_kind: str | None = None
    started_at_ms: int | None = None
    finished_at_ms: int | None = None
    browser_session_id: str | None = None
    context_id: str | None = None
    page_id: str | None = None
    receipt: ExecutionReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "operation_id": self.operation_id,
            "attempted": self.attempted,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "operation_verdict": self.operation_verdict,
            "failure_kind": self.failure_kind,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "browser_session_id": self.browser_session_id,
            "context_id": self.context_id,
            "page_id": self.page_id,
            "receipt": self.receipt.to_dict() if self.receipt is not None else None,
        }


PLAN_RECEIPT_SCHEMA_VERSION = "2.2.0"

PLAN_LIMITATIONS = RUNTIME_LIMITATIONS


@dataclass
class PlanReceipt:
    schema_version: str
    plan_id: str
    plan_verdict: PlanVerdict
    completion_status: CompletionStatus
    failure_policy: str
    declared_step_count: int
    attempted_step_count: int
    verified_step_count: int
    skipped_step_count: int
    decisive_step_index: int | None
    decisive_operation_id: str | None
    failure_kind: str | None
    started_at_ms: int
    finished_at_ms: int
    browser: dict[str, Any] | None
    backend_identity: str
    browser_session_id: str | None
    context_id: str | None
    page_id: str | None
    steps: list[PlanStepRecord]
    limitations: list[str]
    runtime_version: str
    execution_error: str | None = None
    plan_describe: dict[str, Any] | None = None
    plan_timing: dict[str, Any] | None = None
    lifecycle: dict[str, Any] | None = None
    telemetry: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return max(0, self.finished_at_ms - self.started_at_ms)

    def check_invariants(self) -> None:
        """Raise ValueError if counts/verdicts/completion contradict each other."""
        if self.attempted_step_count > self.declared_step_count:
            raise ValueError("attempted_step_count exceeds declared_step_count")
        if self.verified_step_count > self.attempted_step_count:
            raise ValueError("verified_step_count exceeds attempted_step_count")
        if self.skipped_step_count + self.attempted_step_count > self.declared_step_count:
            # Skipped + attempted should equal declared when steps list is complete.
            if len(self.steps) == self.declared_step_count:
                raise ValueError("skipped+attempted exceeds declared when steps complete")
        if (
            self.plan_verdict == PlanVerdict.VERIFIED
            and self.skipped_step_count > 0
        ):
            raise ValueError("plan VERIFIED cannot coexist with skipped steps")
        if self.completion_status == CompletionStatus.COMPLETED:
            if any(not s.attempted for s in self.steps):
                raise ValueError("completed cannot coexist with unattempted steps")
            if self.decisive_step_index is not None:
                raise ValueError("all-success completed plan must not set decisive step")
        if self.completion_status == CompletionStatus.STOPPED:
            if self.decisive_step_index is None and any(s.attempted for s in self.steps):
                raise ValueError("stopped plan with attempted steps requires decisive step")
        attempted = [s for s in self.steps if s.attempted]
        if attempted:
            ids = {(s.browser_session_id, s.context_id) for s in attempted}
            if len(ids) != 1:
                raise ValueError(
                    "attempted steps must share browser_session_id/context_id"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "plan_verdict": self.plan_verdict.value,
            "completion_status": self.completion_status.value,
            "failure_policy": self.failure_policy,
            "declared_step_count": self.declared_step_count,
            "attempted_step_count": self.attempted_step_count,
            "verified_step_count": self.verified_step_count,
            "skipped_step_count": self.skipped_step_count,
            "decisive_step_index": self.decisive_step_index,
            "decisive_operation_id": self.decisive_operation_id,
            "failure_kind": self.failure_kind,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "duration_ms": self.duration_ms,
            "browser": self.browser,
            "backend_identity": self.backend_identity,
            "browser_session_id": self.browser_session_id,
            "context_id": self.context_id,
            "page_id": self.page_id,
            "steps": [s.to_dict() for s in self.steps],
            "limitations": list(self.limitations),
            "runtime_version": self.runtime_version,
            "execution_error": self.execution_error,
            "plan": self.plan_describe,
            "plan_timing": self.plan_timing,
            "lifecycle": self.lifecycle,
            "telemetry": list(self.telemetry),
        }


def aggregate_plan_outcome(
    *,
    steps: list[PlanStepRecord],
    declared_count: int,
    setup_failed: bool,
) -> tuple[PlanVerdict, CompletionStatus, int | None, str | None, str | None]:
    """Aggregate step outcomes into plan_verdict + completion_status.

    Aggregation table (stop_on_failure):
    - setup/validation failed before any step → EXECUTION_FAILED, not_started
    - all declared steps attempted and VERIFIED → VERIFIED, completed
    - decisive step NOT_VERIFIED → NOT_VERIFIED, stopped
    - decisive step EXECUTION_FAILED → EXECUTION_FAILED, stopped
    - decisive step INDETERMINATE → INDETERMINATE, stopped
    """
    if setup_failed or not steps:
        return (
            PlanVerdict.EXECUTION_FAILED,
            CompletionStatus.NOT_STARTED,
            None,
            None,
            None,
        )

    attempted = [s for s in steps if s.attempted]
    if not attempted:
        return (
            PlanVerdict.EXECUTION_FAILED,
            CompletionStatus.NOT_STARTED,
            None,
            None,
            None,
        )

    last = attempted[-1]
    assert last.operation_verdict is not None
    verdict = Verdict(last.operation_verdict)

    if (
        len(attempted) == declared_count
        and all(s.operation_verdict == Verdict.VERIFIED.value for s in attempted)
    ):
        return (
            PlanVerdict.VERIFIED,
            CompletionStatus.COMPLETED,
            None,
            None,
            None,
        )

    # Stopped or incomplete after a non-VERIFIED decisive step.
    plan_verdict = {
        Verdict.NOT_VERIFIED: PlanVerdict.NOT_VERIFIED,
        Verdict.EXECUTION_FAILED: PlanVerdict.EXECUTION_FAILED,
        Verdict.INDETERMINATE: PlanVerdict.INDETERMINATE,
        Verdict.VERIFIED: PlanVerdict.EXECUTION_FAILED,  # incomplete without stop reason
    }[verdict]

    completion = (
        CompletionStatus.COMPLETED
        if len(attempted) == declared_count and verdict == Verdict.VERIFIED
        else CompletionStatus.STOPPED
    )
    return (
        plan_verdict,
        completion,
        last.step_index,
        last.operation_id,
        last.failure_kind or PlanFailureKind.STEP_STOPPED_PLAN.value,
    )
