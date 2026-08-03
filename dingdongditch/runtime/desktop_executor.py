"""Ordered execution for typed Windows desktop plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dingdongditch import __version__
from dingdongditch.backends.windows_desktop_backend import (
    DesktopBackendError,
    WindowsDesktopBackend,
    monotonic_ms,
)
from dingdongditch.contract.desktop import DesktopExecutionPlan
from dingdongditch.contract.plan import CompletionStatus, PlanVerdict
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.contract.verdict import Verdict


DESKTOP_RECEIPT_SCHEMA_VERSION = "1.0.0"


@dataclass
class DesktopActionReceipt:
    schema_version: str
    operation_id: str
    verdict: Verdict
    action_type: str
    execution_status: str
    failure_kind: str | None
    execution_error: str | None
    started_at_ms: int
    finished_at_ms: int
    backend_identity: str
    session_id: str
    action_evidence: dict[str, Any]
    screenshots: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "verdict": self.verdict.value,
            "action_evidence": dict(self.action_evidence),
            "screenshots": list(self.screenshots),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesktopActionReceipt":
        values = dict(data)
        values["verdict"] = Verdict(values["verdict"])
        return cls(**values)


@dataclass
class DesktopPlanReceipt:
    schema_version: str
    plan_id: str
    plan_verdict: PlanVerdict
    completion_status: CompletionStatus
    declared_step_count: int
    attempted_step_count: int
    verified_step_count: int
    skipped_step_count: int
    started_at_ms: int
    finished_at_ms: int
    backend_identity: str
    session_id: str
    capabilities: dict[str, Any]
    steps: list[DesktopActionReceipt]
    skipped_operation_ids: list[str]
    failure_kind: str | None
    execution_error: str | None
    lifecycle: dict[str, Any]
    plan: dict[str, Any] | None

    @property
    def duration_ms(self) -> int:
        return max(0, self.finished_at_ms - self.started_at_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "plan_verdict": self.plan_verdict.value,
            "completion_status": self.completion_status.value,
            "steps": [item.to_dict() for item in self.steps],
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesktopPlanReceipt":
        values = dict(data)
        values.pop("duration_ms", None)
        values["plan_verdict"] = PlanVerdict(values["plan_verdict"])
        values["completion_status"] = CompletionStatus(values["completion_status"])
        values["steps"] = [
            DesktopActionReceipt.from_dict(item) for item in values["steps"]
        ]
        return cls(**values)


def _should_capture(config: ScreenshotConfig, verdict: Verdict) -> bool:
    return config.policy in (
        ScreenshotPolicy.ALWAYS,
        ScreenshotPolicy.BEFORE_AND_AFTER,
    ) or (
        config.policy == ScreenshotPolicy.AFTER_SUCCESS
        and verdict == Verdict.VERIFIED
    ) or (
        config.policy == ScreenshotPolicy.ON_FAILURE
        and verdict != Verdict.VERIFIED
    )


def execute_desktop_plan(
    plan: DesktopExecutionPlan,
    *,
    backend: WindowsDesktopBackend | None = None,
    stop_session: bool | None = None,
) -> DesktopPlanReceipt:
    """Execute exactly the declared operations through one desktop backend."""
    started = monotonic_ms()
    owns_backend = backend is None
    if stop_session is None:
        stop_session = owns_backend
    steps: list[DesktopActionReceipt] = []
    skipped: list[str] = []
    failure_kind: str | None = None
    error: str | None = None
    plan_description: dict[str, Any] | None = None
    try:
        plan.validate()
        plan_description = plan.describe()
    except ValueError as exc:
        skipped = [item.operation_id for item in plan.operations]
        return DesktopPlanReceipt(
            schema_version=DESKTOP_RECEIPT_SCHEMA_VERSION,
            plan_id=plan.plan_id,
            plan_verdict=PlanVerdict.EXECUTION_FAILED,
            completion_status=CompletionStatus.NOT_STARTED,
            declared_step_count=len(plan.operations),
            attempted_step_count=0,
            verified_step_count=0,
            skipped_step_count=len(skipped),
            started_at_ms=started,
            finished_at_ms=monotonic_ms(),
            backend_identity="windows-uia-pywinauto",
            session_id="not-started",
            capabilities=WindowsDesktopBackend.capabilities(),
            steps=[],
            skipped_operation_ids=skipped,
            failure_kind="invalid_desktop_plan",
            execution_error=str(exc),
            lifecycle={"state": "not_started", "cleanup_errors": []},
            plan=None,
        )

    try:
        if backend is None:
            backend = WindowsDesktopBackend(
                artifact_root=(
                    plan.screenshot_config.artifact_root
                    if plan.screenshot_config
                    else "artifacts/desktop"
                )
            )
        backend.start()
        for index, operation in enumerate(plan.operations):
            dispatch = backend.dispatch(operation.action)
            verdict = Verdict.VERIFIED if dispatch.ok else Verdict.EXECUTION_FAILED
            config = (
                operation.screenshot_config
                or plan.screenshot_config
                or ScreenshotConfig()
            )
            screenshots: list[dict[str, Any]] = []
            if _should_capture(config, verdict):
                try:
                    screenshot = backend.capture_screenshot(
                        plan_id=plan.plan_id,
                        operation_id=operation.operation_id,
                        reason=(
                            "after_success"
                            if verdict == Verdict.VERIFIED
                            else "failure"
                        ),
                        config=config,
                    )
                    requested_regions = [
                        region.describe()
                        for region in config.desktop_redaction_regions
                    ]
                    if config.mandatory_redaction and (
                        screenshot.get("redaction_status") != "applied"
                        or screenshot.get("redacted_regions") != requested_regions
                    ):
                        raise DesktopBackendError(
                            "desktop backend did not attest every mandatory "
                            "redaction region",
                            failure_kind="screenshot_redaction_failed",
                        )
                    screenshots.append(screenshot)
                except Exception as shot_error:
                    dispatch.evidence["screenshot_error"] = str(shot_error)
                    dispatch.evidence["requested_desktop_redaction_regions"] = [
                        region.describe()
                        for region in config.desktop_redaction_regions
                    ]
                    if config.mandatory_redaction:
                        verdict = Verdict.EXECUTION_FAILED
                        dispatch.failure_kind = "screenshot_redaction_failed"
                        dispatch.error = str(shot_error)
            receipt = DesktopActionReceipt(
                schema_version=DESKTOP_RECEIPT_SCHEMA_VERSION,
                operation_id=operation.operation_id,
                verdict=verdict,
                action_type=operation.action.type.value,
                execution_status=(
                    "completed" if verdict == Verdict.VERIFIED else "failed"
                ),
                failure_kind=dispatch.failure_kind,
                execution_error=dispatch.error,
                started_at_ms=dispatch.started_at_ms,
                finished_at_ms=dispatch.completed_at_ms,
                backend_identity=backend.backend_identity,
                session_id=backend.session_id,
                action_evidence=dispatch.evidence,
                screenshots=screenshots,
            )
            steps.append(receipt)
            if verdict != Verdict.VERIFIED:
                failure_kind = dispatch.failure_kind
                error = dispatch.error
                skipped = [
                    item.operation_id for item in plan.operations[index + 1 :]
                ]
                break
    except DesktopBackendError as exc:
        failure_kind = exc.failure_kind
        error = str(exc)
        skipped = [
            item.operation_id for item in plan.operations[len(steps) :]
        ]
    except Exception as exc:
        failure_kind = "desktop_runtime_error"
        error = str(exc)
        skipped = [
            item.operation_id for item in plan.operations[len(steps) :]
        ]
    finally:
        assert backend is not None
        if stop_session:
            backend.stop()

    all_verified = (
        len(steps) == len(plan.operations)
        and all(item.verdict == Verdict.VERIFIED for item in steps)
    )
    lifecycle = {
        "state": backend.lifecycle_state.value,
        "cleanup_errors": list(backend.cleanup_errors),
        "owned_process_ids": list(backend.owned_process_ids),
        "owned_window_handles": list(backend.owned_window_handles),
        "remaining_owned_process_ids": backend.remaining_owned_process_ids(),
    }
    return DesktopPlanReceipt(
        schema_version=DESKTOP_RECEIPT_SCHEMA_VERSION,
        plan_id=plan.plan_id,
        plan_verdict=(
            PlanVerdict.VERIFIED if all_verified else PlanVerdict.EXECUTION_FAILED
        ),
        completion_status=(
            CompletionStatus.COMPLETED if all_verified else CompletionStatus.STOPPED
        ),
        declared_step_count=len(plan.operations),
        attempted_step_count=len(steps),
        verified_step_count=sum(
            item.verdict == Verdict.VERIFIED for item in steps
        ),
        skipped_step_count=len(skipped),
        started_at_ms=started,
        finished_at_ms=monotonic_ms(),
        backend_identity=backend.backend_identity,
        session_id=backend.session_id,
        capabilities=backend.capabilities(),
        steps=steps,
        skipped_operation_ids=skipped,
        failure_kind=failure_kind,
        execution_error=error,
        lifecycle=lifecycle,
        plan=plan_description,
    )
