"""Native ordered plan execution."""

from __future__ import annotations

import warnings

from dingdongditch import __version__
from dingdongditch.backends.playwright_backend import PlaywrightBackend, monotonic_ms
from dingdongditch.contract.browser import BrowserConfigError
from dingdongditch.contract.plan import (
    PLAN_LIMITATIONS,
    PLAN_RECEIPT_SCHEMA_VERSION,
    STOPPING_VERDICTS,
    CompletionStatus,
    ExecutionPlan,
    FailurePolicy,
    PlanFailureKind,
    PlanReceipt,
    PlanStepRecord,
    PlanVerdict,
    PlanValidationError,
    aggregate_plan_outcome,
)
from dingdongditch.contract.verdict import Verdict
from dingdongditch.contract.download import TrustedDownloadConfig
from dingdongditch.authentication import AuthenticationCapability
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_timing import PlanTimingState


def _skipped_records(
    plan: ExecutionPlan,
    *,
    from_index: int,
    reason: str,
) -> list[PlanStepRecord]:
    return [
        PlanStepRecord(
            step_index=i,
            operation_id=plan.operations[i].operation_id,
            attempted=False,
            skipped=True,
            skip_reason=reason,
        )
        for i in range(from_index, len(plan.operations))
    ]


def _build_receipt(
    *,
    plan: ExecutionPlan,
    steps: list[PlanStepRecord],
    started_at: int,
    finished_at: int,
    setup_failed: bool,
    backend: PlaywrightBackend | None,
    execution_error: str | None,
    failure_kind_override: str | None = None,
    plan_timing_summary: dict | None = None,
) -> PlanReceipt:
    plan_verdict, completion, decisive_idx, decisive_oid, fail_kind = aggregate_plan_outcome(
        steps=steps,
        declared_count=len(plan.operations),
        setup_failed=setup_failed,
    )
    if failure_kind_override:
        fail_kind = failure_kind_override

    attempted = [s for s in steps if s.attempted]
    verified = [
        s for s in attempted if s.operation_verdict == Verdict.VERIFIED.value
    ]
    skipped = [s for s in steps if s.skipped]

    browser_env = backend.browser_environment() if backend and backend.is_started else None
    if browser_env is None and not setup_failed:
        browser_env = plan.browser_config.describe()

    receipt = PlanReceipt(
        schema_version=PLAN_RECEIPT_SCHEMA_VERSION,
        plan_id=plan.plan_id,
        plan_verdict=plan_verdict,
        completion_status=completion,
        failure_policy=plan.failure_policy.value,
        declared_step_count=len(plan.operations),
        attempted_step_count=len(attempted),
        verified_step_count=len(verified),
        skipped_step_count=len(skipped),
        decisive_step_index=decisive_idx,
        decisive_operation_id=decisive_oid,
        failure_kind=fail_kind,
        started_at_ms=started_at,
        finished_at_ms=finished_at,
        browser=browser_env
        if browser_env is not None
        else {
            **plan.browser_config.describe(),
            "backend_identity": "playwright-sync",
        },
        backend_identity=(
            backend.backend_identity if backend is not None else "playwright-sync"
        ),
        browser_session_id=(
            backend.browser_session_id if backend is not None else None
        ),
        context_id=backend.context_id if backend is not None else None,
        page_id=backend.page_id if backend is not None else None,
        steps=steps,
        limitations=list(PLAN_LIMITATIONS),
        runtime_version=__version__,
        execution_error=execution_error,
        plan_describe=plan.describe(),
        plan_timing=plan_timing_summary,
        lifecycle=(
            {
                "ownership": "runtime_owned" if backend is None else "available",
                "state": backend.lifecycle_state.value,
                "cleanup_errors": list(backend.cleanup_errors),
                "terminal_session_identity": backend.terminal_session_identity,
            }
            if backend is not None
            else None
        ),
        telemetry=list(backend.telemetry) if backend is not None else [],
    )
    receipt.check_invariants()
    return receipt


def _execute_plan(
    plan: ExecutionPlan,
    *,
    backend: PlaywrightBackend | None = None,
    trusted_download_config: TrustedDownloadConfig | None = None,
    authentication: AuthenticationCapability | None = None,
) -> PlanReceipt:
    """Execute an ordered plan through one retained browser session.

    Reuses ``execute_operation`` for every step. Does not invent, reorder, retry,
    or heal operations.
    """
    started_at = monotonic_ms()
    owns_backend = backend is None
    steps: list[PlanStepRecord] = []
    execution_error: str | None = None
    failure_kind_override: str | None = None
    final_receipt: PlanReceipt | None = None

    # --- validate before launch ---
    try:
        plan.validate()
    except BrowserConfigError as exc:
        return _build_receipt(
            plan=plan,
            steps=_skipped_records(
                plan, from_index=0, reason="plan_validation_failed"
            ),
            started_at=started_at,
            finished_at=monotonic_ms(),
            setup_failed=True,
            backend=None,
            execution_error=str(exc),
            failure_kind_override=exc.failure_kind.value,
        )
    except PlanValidationError as exc:
        return _build_receipt(
            plan=plan,
            steps=_skipped_records(
                plan, from_index=0, reason="plan_validation_failed"
            ),
            started_at=started_at,
            finished_at=monotonic_ms(),
            setup_failed=True,
            backend=None,
            execution_error=str(exc),
            failure_kind_override=exc.failure_kind.value,
        )
    except ValueError as exc:
        return _build_receipt(
            plan=plan,
            steps=_skipped_records(
                plan, from_index=0, reason="plan_validation_failed"
            ),
            started_at=started_at,
            finished_at=monotonic_ms(),
            setup_failed=True,
            backend=None,
            execution_error=str(exc),
            failure_kind_override=PlanFailureKind.INVALID_OPERATION.value,
        )

    assert plan.failure_policy == FailurePolicy.STOP_ON_FAILURE

    if owns_backend:
        try:
            backend = PlaywrightBackend(
                browser_config=plan.browser_config,
                trusted_download_config=trusted_download_config,
                authentication=authentication,
            )
        except BrowserConfigError as exc:
            return _build_receipt(
                plan=plan,
                steps=_skipped_records(
                    plan, from_index=0, reason="browser_setup_failed"
                ),
                started_at=started_at,
                finished_at=monotonic_ms(),
                setup_failed=True,
                backend=None,
                execution_error=str(exc),
                failure_kind_override=exc.failure_kind.value,
            )

    assert backend is not None
    if not owns_backend and backend.browser_config != plan.browser_config:
        return _build_receipt(
            plan=plan,
            steps=_skipped_records(
                plan, from_index=0, reason="browser_configuration_mismatch"
            ),
            started_at=started_at,
            finished_at=monotonic_ms(),
            setup_failed=True,
            backend=backend,
            execution_error=(
                "supplied backend configuration does not match plan.browser_config"
            ),
            failure_kind_override="contradictory_browser_config",
        )
    timing = PlanTimingState.from_plan(
        initial_plan_timeout_ms=plan.initial_plan_timeout_ms,
        adaptive_timeout_enabled=plan.adaptive_timeout_enabled,
        max_plan_timeout_ms=plan.max_plan_timeout_ms,
        plan_started_at_ms=started_at,
    )

    try:
        try:
            backend.start()
        except BrowserConfigError as exc:
            return _build_receipt(
                plan=plan,
                steps=_skipped_records(
                    plan, from_index=0, reason="browser_setup_failed"
                ),
                started_at=started_at,
                finished_at=monotonic_ms(),
                setup_failed=True,
                backend=backend,
                execution_error=str(exc),
                failure_kind_override=exc.failure_kind.value,
                plan_timing_summary=timing.summary_dict(),
            )

        session_id = backend.browser_session_id
        context_id = backend.context_id
        page_id = backend.page_id

        for index, operation in enumerate(plan.operations):
            try:
                receipt = execute_operation(
                    operation,
                    backend=backend,
                    plan_timing=timing,
                    plan_id=plan.plan_id,
                    step_id=f"step-{index}",
                    screenshot_config=plan.screenshot_config,
                )
            except Exception as exc:  # unexpected — structured stop
                execution_error = f"{type(exc).__name__}: {exc}"
                failure_kind_override = PlanFailureKind.UNEXPECTED_EXCEPTION.value
                steps.append(
                    PlanStepRecord(
                        step_index=index,
                        operation_id=operation.operation_id,
                        attempted=True,
                        skipped=False,
                        operation_verdict=Verdict.EXECUTION_FAILED.value,
                        failure_kind=failure_kind_override,
                        started_at_ms=monotonic_ms(),
                        finished_at_ms=monotonic_ms(),
                        browser_session_id=session_id,
                        context_id=context_id,
                        page_id=page_id,
                        receipt=None,
                    )
                )
                steps.extend(
                    _skipped_records(
                        plan,
                        from_index=index + 1,
                        reason="prior_step_prevented_execution",
                    )
                )
                break

            # Prove session stability across steps.
            env = receipt.browser or {}
            step = PlanStepRecord(
                step_index=index,
                operation_id=operation.operation_id,
                attempted=True,
                skipped=False,
                operation_verdict=receipt.verdict.value,
                failure_kind=receipt.failure_kind,
                started_at_ms=receipt.started_at_ms,
                finished_at_ms=receipt.finished_at_ms,
                browser_session_id=env.get("browser_session_id") or session_id,
                context_id=env.get("context_id") or context_id,
                page_id=env.get("page_id") or page_id,
                receipt=receipt,
            )
            steps.append(step)

            if receipt.failure_kind == "plan_deadline_expired":
                failure_kind_override = PlanFailureKind.PLAN_DEADLINE_EXPIRED.value

            if receipt.verdict in STOPPING_VERDICTS:
                steps.extend(
                    _skipped_records(
                        plan,
                        from_index=index + 1,
                        reason="prior_step_prevented_execution",
                    )
                )
                break

        finished = monotonic_ms()
        final_receipt = _build_receipt(
            plan=plan,
            steps=steps,
            started_at=started_at,
            finished_at=finished,
            setup_failed=False,
            backend=backend,
            execution_error=execution_error,
            failure_kind_override=failure_kind_override,
            plan_timing_summary=timing.summary_dict(),
        )
        return final_receipt
    finally:
        if owns_backend:
            backend.stop()
            if final_receipt is not None:
                final_receipt.lifecycle = {
                    "ownership": "runtime_owned",
                    "state": backend.lifecycle_state.value,
                    "cleanup_errors": list(backend.cleanup_errors),
                    "terminal_session_identity": backend.terminal_session_identity,
                }
                final_receipt.telemetry = list(backend.telemetry)
        if final_receipt is not None:
            final_receipt.seal()


def execute_plan(
    plan: ExecutionPlan,
    *,
    backend: PlaywrightBackend | None = None,
    trusted_download_config: TrustedDownloadConfig | None = None,
    authentication: AuthenticationCapability | None = None,
) -> PlanReceipt:
    warnings.warn(
        "execute_plan is a trusted-host compatibility API; expose GovernedAgentSession or GovernedAgentService to external planners",
        DeprecationWarning,
        stacklevel=2,
    )
    if backend is None:
        return _execute_plan(
            plan, backend=None, trusted_download_config=trusted_download_config,
            authentication=authentication,
        )
    with backend.exclusive_use(f"plan:{plan.plan_id}"):
        return _execute_plan(
            plan, backend=backend, trusted_download_config=trusted_download_config,
            authentication=authentication,
        )
