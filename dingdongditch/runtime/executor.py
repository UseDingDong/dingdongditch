from __future__ import annotations

from typing import Any

from dingdongditch import __version__
from dingdongditch.backends.playwright_backend import PlaywrightBackend, monotonic_ms
from dingdongditch.contract.browser import (
    BrowserConfig,
    BrowserConfigError,
    default_browser_config,
)
from dingdongditch.contract.capabilities import RUNTIME_LIMITATIONS
from dingdongditch.contract.operation import ActionType, Operation
from dingdongditch.contract.page_precondition import PageConditionResultValue
from dingdongditch.contract.receipt import RECEIPT_SCHEMA_VERSION, ExecutionReceipt
from dingdongditch.contract.verdict import Verdict
from dingdongditch.contract.download import TrustedDownloadConfig
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.models import ObservationSummary, RecoveryAttempt
from dingdongditch.runtime.freshness import evaluate_freshness
from dingdongditch.runtime.page_preconditions import evaluate_page_precondition
from dingdongditch.runtime.verifier import evaluate_expectations

def _decide_verdict(
    *,
    action_ok: bool,
    expectations_declared: int,
    expectation_results: list,
    freshness_stale: list[str],
    action_type: str | None = None,
    action_evidence: dict | None = None,
) -> Verdict:
    if not action_ok:
        return Verdict.EXECUTION_FAILED

    if action_type == "wait_for":
        evidence = action_evidence or {}
        if evidence.get("condition_satisfied") is True:
            if expectations_declared == 0:
                return Verdict.VERIFIED
            # Additional host expectations must also pass.
        elif evidence.get("timeout_occurred") is True:
            return Verdict.NOT_VERIFIED
        elif expectations_declared == 0:
            return Verdict.INDETERMINATE

    if action_type in {"switch_to_page", "close_page", "switch_to_opener"}:
        if action_ok and (action_evidence or {}).get("dispatched") is True:
            return Verdict.VERIFIED

    if action_type == "download":
        download = (action_evidence or {}).get("download") or {}
        if (
            download.get("state") == "completed"
            and download.get("artifact") is not None
            and download.get("page_policy_passed") is True
        ):
            if expectations_declared == 0:
                return Verdict.VERIFIED

    if action_type == "click":
        evidence = action_evidence or {}
        transition = evidence.get("page_transition") or {}
        if (
            action_ok
            and transition.get("policy")
            and transition.get("policy") != "same_page"
        ):
            page_results = evidence.get("new_page_verification_results") or []
            if all(result.get("passed") is True for result in page_results):
                return Verdict.VERIFIED

    if expectations_declared == 0:
        # Successful execution is acknowledged but not verified task success.
        return Verdict.INDETERMINATE

    if freshness_stale:
        return Verdict.INDETERMINATE

    results = [r.result for r in expectation_results]
    if any(r == "indeterminate" for r in results):
        return Verdict.INDETERMINATE
    if any(r == "fail" for r in results):
        return Verdict.NOT_VERIFIED
    if results and all(r == "pass" for r in results):
        return Verdict.VERIFIED
    return Verdict.INDETERMINATE


def _failed_receipt(
    *,
    operation: Operation,
    started_at: int,
    collector: EvidenceCollector,
    locator_desc: dict | None,
    execution_status: str,
    execution_error: str,
    failure_kind: str | None,
    browser: dict | None,
    backend_identity: str,
    browser_identity: str,
    action_evidence: dict | None = None,
    target_resolution: dict | None = None,
) -> ExecutionReceipt:
    finished = monotonic_ms()
    return ExecutionReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        operation_id=operation.operation_id,
        verdict=Verdict.EXECUTION_FAILED,
        action_type=operation.action.type.value,
        target_locator=locator_desc,
        target_url=operation.url,
        started_at_ms=started_at,
        finished_at_ms=finished,
        action_started_at_ms=None,
        action_completed_at_ms=None,
        verification_completed_at_ms=None,
        execution_status=execution_status,
        execution_error=execution_error,
        pre_action_observation=None,
        post_action_observation=None,
        expectation_results=[],
        evidence=collector.signals,
        freshness=evaluate_freshness(
            policy=operation.freshness,
            action_started_at_ms=None,
            verification_completed_at_ms=None,
            signals=collector.signals,
            signal_ids_used_for_verification=set(),
        ),
        recovery_attempts=[],
        limitations=list(RUNTIME_LIMITATIONS),
        backend_identity=backend_identity,
        browser_identity=browser_identity,
        runtime_version=__version__,
        action_executed_successfully=False,
        expectations_declared=len(operation.expectations),
        target_resolution=target_resolution,
        browser=browser,
        failure_kind=failure_kind,
        action_evidence=action_evidence,
        page_precondition=(action_evidence or {}).get("page_precondition"),
        navigation_occurred=False,
        dispatch_document_url=(action_evidence or {}).get("actual_url"),
    ).seal()


def _execute_operation(
    operation: Operation,
    *,
    headless: bool = True,
    browser_config: BrowserConfig | None = None,
    backend: PlaywrightBackend | None = None,
    plan_timing: Any | None = None,
    plan_id: str = "standalone",
    step_id: str = "step-0",
    screenshot_config: Any | None = None,
    trusted_download_config: TrustedDownloadConfig | None = None,
    observation_reference: Any | None = None,
) -> ExecutionReceipt:
    """Execute one externally planned operation and return an attested receipt.

    Browser configuration is session-level. When ``backend`` is omitted, a temporary
    PlaywrightBackend is created from ``browser_config`` (or default bundled
    Chromium with the given ``headless`` flag).
    """
    started_at = monotonic_ms()
    collector = EvidenceCollector(
        scope_id=operation.operation_id, window_started_at_ms=started_at
    )
    owns_backend = backend is None
    locator_desc = (
        operation.action.locator.describe() if operation.action.locator else None
    )
    if operation.action.frame is not None:
        locator_desc = {
            "locator": locator_desc,
            "frame": operation.action.frame.describe(),
        }
    elif (
        operation.action.type == ActionType.WAIT_FOR
        and operation.action.wait_condition is not None
        and operation.action.wait_condition.frame is not None
    ):
        wc = operation.action.wait_condition
        locator_desc = {
            "locator": wc.locator.describe() if wc.locator else None,
            "frame": wc.frame.describe(),
        }

    resolved_config: BrowserConfig
    if backend is not None:
        resolved_config = backend.browser_config
        if (
            browser_config is not None
            and browser_config.describe() != resolved_config.describe()
        ):
            return _failed_receipt(
                operation=operation,
                started_at=started_at,
                collector=collector,
                locator_desc=locator_desc,
                execution_status="validation_failed",
                execution_error=(
                    "browser_config does not match the provided backend session config"
                ),
                failure_kind="contradictory_browser_config",
                browser=browser_config.describe(),
                backend_identity=backend.backend_identity,
                browser_identity=backend.browser_identity,
            )
    elif browser_config is not None:
        # Explicit BrowserConfig is authoritative; headless= applies only as default.
        resolved_config = browser_config
    else:
        resolved_config = default_browser_config(headless=headless)

    try:
        operation.validate()
        if backend is None:
            resolved_config.validate()
    except BrowserConfigError as exc:
        return _failed_receipt(
            operation=operation,
            started_at=started_at,
            collector=collector,
            locator_desc=locator_desc,
            execution_status="validation_failed",
            execution_error=str(exc),
            failure_kind=exc.failure_kind.value,
            browser=resolved_config.describe(),
            backend_identity="playwright-sync",
            browser_identity=resolved_config.engine.value,
        )
    except ValueError as exc:
        return _failed_receipt(
            operation=operation,
            started_at=started_at,
            collector=collector,
            locator_desc=locator_desc,
            execution_status="validation_failed",
            execution_error=str(exc),
            failure_kind=None,
            browser=resolved_config.describe(),
            backend_identity="playwright-sync",
            browser_identity=resolved_config.engine.value,
        )

    if owns_backend:
        try:
            backend = PlaywrightBackend(
                browser_config=resolved_config,
                trusted_download_config=trusted_download_config,
            )
        except BrowserConfigError as exc:
            return _failed_receipt(
                operation=operation,
                started_at=started_at,
                collector=collector,
                locator_desc=locator_desc,
                execution_status="validation_failed",
                execution_error=str(exc),
                failure_kind=exc.failure_kind.value,
                browser=resolved_config.describe(),
                backend_identity="playwright-sync",
                browser_identity=resolved_config.engine.value,
            )

    assert backend is not None

    pre_obs: ObservationSummary | None = None
    post_obs: ObservationSummary | None = None
    action_started: int | None = None
    action_completed: int | None = None
    verification_completed: int | None = None
    execution_status = "not_started"
    execution_error: str | None = None
    action_ok = False
    expectation_results = []
    recovery_attempts: list[RecoveryAttempt] = []
    target_resolution: dict | None = None
    failure_kind: str | None = None
    action_evidence: dict | None = None
    observation_validation: dict[str, Any] | None = None
    guard_branch: str | None = None
    guard_probe_resolution: dict[str, Any] | None = None
    active_expectations = operation.expectations
    guarded_skip = False

    try:
        if owns_backend:
            try:
                backend.start()
            except BrowserConfigError as exc:
                return _failed_receipt(
                    operation=operation,
                    started_at=started_at,
                    collector=collector,
                    locator_desc=locator_desc,
                    execution_status="browser_setup_failed",
                    execution_error=str(exc),
                    failure_kind=exc.failure_kind.value,
                    browser={
                        **resolved_config.describe(),
                        "backend_identity": backend.backend_identity,
                    },
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                )
        else:
            if not backend.is_started:
                return _failed_receipt(
                    operation=operation,
                    started_at=started_at,
                    collector=collector,
                    locator_desc=locator_desc,
                    execution_status="browser_setup_failed",
                    execution_error="host-owned backend must be active before execution",
                    failure_kind="browser_session_not_active",
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                )
            backend.mark_session_reused()

        page_precondition: dict[str, Any] | None = None
        if operation.action.type != ActionType.NAVIGATE:
            if operation.page_precondition is None:
                actual_url = backend.page.url
                if actual_url in ("about:blank", "about:blank/", ""):
                    # Preserve the original standalone-operation bootstrap:
                    # a newly created blank page may enter the host-declared
                    # document before the legacy exact-URL precondition is
                    # evaluated.  A nonblank mismatch is never navigated.
                    backend.ensure_on_url(operation.url, operation.timeout_ms)
                    actual_url = backend.page.url
                legacy_matched = backend._same_document_url(
                    actual_url, operation.url
                )
                page_precondition = {
                    "expected_url": operation.url,
                    "actual_url": actual_url,
                    "matched": legacy_matched,
                    "fragment_differences_ignored": True,
                    "mode": "legacy_exact_url",
                    "logic": "all",
                    "result": (
                        "pass"
                        if legacy_matched
                        else "fail"
                    ),
                    "condition_results": [],
                }
            else:
                try:
                    evaluation = evaluate_page_precondition(
                        operation.page_precondition,
                        backend=backend,
                        collector=collector,
                    )
                    page_precondition = evaluation.to_dict()
                except Exception as exc:
                    try:
                        actual_url = getattr(
                            getattr(backend, "page", None), "url", ""
                        )
                    except Exception:
                        actual_url = ""
                    evaluated_at = monotonic_ms()
                    condition_results = []
                    for condition in operation.page_precondition.conditions:
                        expected = condition.describe()
                        expected.pop("condition_id", None)
                        expected.pop("type", None)
                        condition_results.append(
                            {
                                "condition_id": condition.condition_id,
                                "condition_type": condition.type.value,
                                "expected": expected,
                                "observed": {
                                    "evaluator_error": (
                                        f"{type(exc).__name__}: {exc}"
                                    )
                                },
                                "result": "indeterminate",
                                "evidence_refs": [],
                                "evaluated_at_ms": evaluated_at,
                                "explanation": "page precondition evaluator error",
                            }
                        )
                    page_precondition = {
                        "mode": "explicit_conditions",
                        "logic": "all",
                        "result": "indeterminate",
                        "matched": False,
                        "actual_url": actual_url,
                        "evaluated_at_ms": evaluated_at,
                        "condition_results": condition_results,
                        "evaluator_error": f"{type(exc).__name__}: {exc}",
                    }
            if not page_precondition["matched"]:
                indeterminate = (
                    page_precondition.get("result")
                    == PageConditionResultValue.INDETERMINATE.value
                )
                return _failed_receipt(
                    operation=operation,
                    started_at=started_at,
                    collector=collector,
                    locator_desc=locator_desc,
                    execution_status="page_precondition_failed",
                    execution_error=(
                        "declared page precondition was indeterminate"
                        if indeterminate
                        else (
                            f"current page does not match declared operation URL: "
                            f"expected={operation.url!r} "
                            f"actual={page_precondition.get('actual_url')!r}"
                        )
                        if operation.page_precondition is None
                        else (
                            "current page does not satisfy the declared "
                            "page precondition"
                        )
                    ),
                    failure_kind=(
                        "page_precondition_indeterminate"
                        if indeterminate
                        else "page_precondition_mismatch"
                    ),
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                    action_evidence={
                        "page_precondition": page_precondition,
                        **(
                            {"expected_url": page_precondition["expected_url"]}
                            if "expected_url" in page_precondition
                            else {}
                        ),
                        "actual_url": page_precondition.get("actual_url"),
                        "navigation_occurred": False,
                    },
                )

        if plan_timing is not None and plan_timing.expired(monotonic_ms()):
            completed = monotonic_ms()
            return ExecutionReceipt(
                schema_version=RECEIPT_SCHEMA_VERSION,
                operation_id=operation.operation_id,
                verdict=Verdict.NOT_VERIFIED,
                action_type=operation.action.type.value,
                target_locator=locator_desc,
                target_url=operation.url,
                started_at_ms=started_at,
                finished_at_ms=completed,
                action_started_at_ms=None,
                action_completed_at_ms=None,
                verification_completed_at_ms=completed,
                execution_status="not_started",
                execution_error="plan deadline expired before operation dispatch",
                pre_action_observation=None,
                post_action_observation=None,
                expectation_results=[],
                evidence=list(collector.signals),
                freshness=evaluate_freshness(
                    policy=operation.freshness,
                    action_started_at_ms=None,
                    verification_completed_at_ms=completed,
                    signals=collector.signals,
                    signal_ids_used_for_verification=set(),
                ),
                recovery_attempts=[],
                limitations=list(RUNTIME_LIMITATIONS),
                backend_identity=backend.backend_identity,
                browser_identity=backend.browser_identity,
                runtime_version=__version__,
                action_executed_successfully=False,
                expectations_declared=len(operation.expectations),
                target_resolution=None,
                browser=backend.browser_environment(),
                failure_kind="plan_deadline_expired",
                action_evidence={
                    "timeout_occurred": True,
                    "timeout_kind": "plan_deadline",
                },
            ).seal()

        pre = backend.observe(collector)
        pre_obs = ObservationSummary(
            collected_at_ms=pre.collected_at_ms,
            url=pre.url,
            notes="pre-action observation",
            signal_ids=[s.signal_id for s in collector.signals],
        )

        # The observation precondition and dispatch share one backend lease.  The
        # freshness check is deliberately the final operation before dispatch so
        # no other runtime owner can interleave work between validation and use.
        if observation_reference is not None:
            validation = backend.validate_observation_reference(
                observation_reference
            )
            observation_validation = validation.to_dict()
            if not validation.fresh:
                return _failed_receipt(
                    operation=operation,
                    started_at=started_at,
                    collector=collector,
                    locator_desc=locator_desc,
                    execution_status="observation_precondition_failed",
                    execution_error=(
                        "observation reference rejected immediately before "
                        f"dispatch: {validation.reason}"
                    ),
                    failure_kind="stale_observation_reference",
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                    action_evidence={
                        "observation_transaction": validation.to_dict(),
                        "dispatch_attempted": False,
                    },
                )

        if operation.guard is not None:
            probe_started = monotonic_ms()
            try:
                probe = backend.probe_guarded_action_target(operation)
            except Exception as exc:
                return _failed_receipt(
                    operation=operation, started_at=started_at, collector=collector,
                    locator_desc=locator_desc, execution_status="guard_resolution_failed",
                    execution_error=f"guard target resolution failed: {type(exc).__name__}",
                    failure_kind="guard_target_resolution_error",
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                    action_evidence={"guarded": True, "branch": None, "dispatched": False,
                                     "skipped": False, "already_satisfied": False,
                                     "guard_expectation_results": [],
                                     "normal_expectation_results": [],
                                     "target_resolution_result": None},
                )
            guard_probe_resolution = probe.trace.to_dict()
            if probe.ok:
                guard_branch = "target_present"
            elif probe.match_count == 0 and probe.failure_kind in {
                "zero_after_primary", "zero_after_constraints"
            }:
                guard_branch = "target_absent"
                guarded_skip = True
                action_started = probe_started
                action_completed = monotonic_ms()
                action_ok = True
                execution_status = "completed"
                active_expectations = list(operation.guard.when_target_absent.expectations)
                target_resolution = guard_probe_resolution
                action_evidence = {
                    "guarded": True, "branch": "target_absent",
                    "dispatched": False, "skipped": True,
                    "already_satisfied": True,
                    "guard_target_resolution": guard_probe_resolution,
                }
            else:
                return _failed_receipt(
                    operation=operation, started_at=started_at, collector=collector,
                    locator_desc=locator_desc, execution_status="guard_resolution_failed",
                    execution_error=probe.error or "guarded target resolution failed",
                    failure_kind=probe.failure_kind,
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                    action_evidence={
                        "guarded": True, "branch": None, "dispatched": False,
                        "skipped": False, "already_satisfied": False,
                        "guard_target_resolution": guard_probe_resolution,
                        "guard_expectation_results": [],
                        "normal_expectation_results": [],
                        "target_resolution_result": guard_probe_resolution,
                    },
                    target_resolution=guard_probe_resolution,
                )

        if not guarded_skip:
            dispatch = backend.dispatch(
                operation, collector=collector, plan_timing=plan_timing
            )
            action_started = dispatch.started_at_ms
            action_completed = dispatch.completed_at_ms
            action_ok = dispatch.ok
            execution_status = "completed" if dispatch.ok else "failed"
            execution_error = dispatch.error
            failure_kind = dispatch.failure_kind
            action_evidence = dispatch.action_evidence
            if operation.guard is not None:
                action_evidence = dict(action_evidence or {})
                action_evidence.update({
                    "guarded": True, "branch": "target_present", "skipped": False,
                    "already_satisfied": False,
                    "guard_target_resolution": guard_probe_resolution,
                })
            if observation_validation is not None:
                action_evidence = dict(action_evidence or {})
                action_evidence["observation_transaction"] = observation_validation
            if dispatch.resolution_trace is not None:
                target_resolution = dispatch.resolution_trace.to_dict()
            for raw in dispatch.recovery_attempts:
                recovery_attempts.append(
                    RecoveryAttempt(
                        reason=raw["reason"], attempt_index=raw["attempt_index"],
                        occurred_at_ms=raw["occurred_at_ms"], detail=raw.get("detail", ""),
                    )
                )

        post = backend.observe(collector)
        post_obs = ObservationSummary(
            collected_at_ms=post.collected_at_ms,
            url=post.url,
            notes="post-action observation",
            signal_ids=[
                s.signal_id
                for s in collector.signals
                if s.collected_at_ms >= post.collected_at_ms
            ],
        )

        network_payload = {"records": []}
        for signal in reversed(collector.signals):
            if signal.kind.value == "network" and "records" in signal.payload:
                network_payload = signal.payload
                break

        verification_completed = monotonic_ms()
        if action_ok and active_expectations:
            deadline = monotonic_ms() + operation.timeout_ms
            if plan_timing is not None and plan_timing.plan_deadline_ms is not None:
                deadline = min(deadline, plan_timing.plan_deadline_ms)
            while True:
                verification_completed = monotonic_ms()
                expectation_results = evaluate_expectations(
                    backend=backend,
                    expectations=list(active_expectations),
                    collector=collector,
                    action_started_at_ms=action_started,
                    verification_completed_at_ms=verification_completed,
                    freshness=operation.freshness,
                    post_network_payload=network_payload,
                    post_url=backend.page.url,
                )
                if all(r.result == "pass" for r in expectation_results):
                    break
                if any(
                    r.result == "indeterminate" and r.freshness_ok is False
                    for r in expectation_results
                ):
                    break
                if monotonic_ms() >= deadline:
                    break
                backend.page.wait_for_timeout(50)
                post = backend.observe(collector)
                post_obs = ObservationSummary(
                    collected_at_ms=post.collected_at_ms,
                    url=post.url,
                    notes="post-action observation (verification poll)",
                    signal_ids=[],
                )
                for signal in reversed(collector.signals):
                    if signal.kind.value == "network" and "records" in signal.payload:
                        network_payload = signal.payload
                        break
        elif action_ok and not active_expectations:
            pass

        used_ids: set[str] = set()
        for er in expectation_results:
            used_ids.update(er.evidence_refs)

        freshness = evaluate_freshness(
            policy=operation.freshness,
            action_started_at_ms=action_started,
            verification_completed_at_ms=verification_completed,
            signals=collector.signals,
            signal_ids_used_for_verification=used_ids,
        )

        for er in expectation_results:
            if er.freshness_ok is False:
                for ref in er.evidence_refs:
                    if ref not in freshness.stale_signal_ids:
                        freshness.stale_signal_ids.append(ref)

        verdict = _decide_verdict(
            action_ok=action_ok,
            expectations_declared=len(active_expectations),
            expectation_results=expectation_results,
            freshness_stale=freshness.stale_signal_ids if active_expectations else [],
            action_type=operation.action.type.value,
            action_evidence=action_evidence,
        )

        if operation.guard is not None:
            action_evidence = dict(action_evidence or {})
            serialized_results = [result.to_dict() for result in expectation_results]
            action_evidence["guard_expectation_results"] = (
                serialized_results if guard_branch == "target_absent" else []
            )
            action_evidence["normal_expectation_results"] = (
                serialized_results if guard_branch == "target_present" else []
            )
            action_evidence["target_resolution_result"] = target_resolution
            if guard_branch == "target_absent" and verdict != Verdict.VERIFIED:
                action_evidence["already_satisfied"] = False
                failure_kind = "guarded_target_absent_condition_not_proven"
                execution_status = "guard_condition_failed"
                execution_error = (
                    "guarded target was absent and the declared already-satisfied "
                    "condition was not proven"
                )

        finished = monotonic_ms()
        receipt = ExecutionReceipt(
            schema_version=RECEIPT_SCHEMA_VERSION,
            operation_id=operation.operation_id,
            verdict=verdict,
            action_type=operation.action.type.value,
            target_locator=locator_desc,
            target_url=operation.url,
            started_at_ms=started_at,
            finished_at_ms=finished,
            action_started_at_ms=action_started,
            action_completed_at_ms=action_completed,
            verification_completed_at_ms=verification_completed,
            execution_status=execution_status,
            execution_error=execution_error,
            pre_action_observation=pre_obs,
            post_action_observation=post_obs,
            expectation_results=expectation_results,
            evidence=list(collector.signals),
            freshness=freshness,
            recovery_attempts=recovery_attempts,
            limitations=list(RUNTIME_LIMITATIONS),
            backend_identity=backend.backend_identity,
            browser_identity=backend.browser_identity,
            runtime_version=__version__,
            action_executed_successfully=action_ok and not guarded_skip,
            expectations_declared=len(active_expectations),
            target_resolution=target_resolution,
            browser=backend.browser_environment(),
            failure_kind=failure_kind,
            action_evidence=action_evidence,
            page_transition=(
                operation.page_transition.describe()
                if operation.page_transition is not None
                else None
            ),
            page_precondition=page_precondition,
            navigation_occurred=operation.action.type == ActionType.NAVIGATE and action_ok,
            dispatch_document_url=backend.page.url,
            telemetry=list(backend.telemetry),
        )

        from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
        config = screenshot_config or operation.screenshot_config or ScreenshotConfig()
        policy = config.policy
        should_capture = policy in {ScreenshotPolicy.ALWAYS, ScreenshotPolicy.AFTER_SUCCESS} and verdict == Verdict.VERIFIED
        should_capture = should_capture or policy == ScreenshotPolicy.ON_FAILURE and verdict != Verdict.VERIFIED
        should_capture = should_capture or policy == ScreenshotPolicy.BEFORE_AND_AFTER
        if should_capture and config.max_per_operation > 0:
            shot = backend.capture_screenshot(plan_id=plan_id, step_id=step_id, operation_id=operation.operation_id, reason="after_success" if verdict == Verdict.VERIFIED else "failure", config=config)
            receipt.action_evidence = dict(receipt.action_evidence or {})
            receipt.action_evidence["screenshots"] = [shot]
            receipt.action_evidence["screenshot_policy"] = config.describe()
            if config.mandatory_redaction and (
                not shot.get("captured")
                or shot.get("redaction_status") != "applied"
            ):
                receipt.verdict = Verdict.EXECUTION_FAILED
                receipt.execution_status = "evidence_capture_failed"
                receipt.failure_kind = "screenshot_redaction_failed"
                receipt.execution_error = (
                    "mandatory screenshot redaction could not be honored: "
                    f"{shot.get('capture_error') or shot.get('redaction_status')}"
                )
        return receipt.seal()
    except Exception as exc:
        return _failed_receipt(
            operation=operation,
            started_at=started_at,
            collector=collector,
            locator_desc=locator_desc,
            execution_status="failed",
            execution_error=f"{type(exc).__name__}: {exc}",
            failure_kind="internal_runtime_error",
            browser=backend.browser_environment(),
            backend_identity=backend.backend_identity,
            browser_identity=backend.browser_identity,
        )
    finally:
        if owns_backend:
            backend.stop()


def execute_operation(
    operation: Operation,
    *,
    headless: bool = True,
    browser_config: BrowserConfig | None = None,
    backend: PlaywrightBackend | None = None,
    plan_timing: Any | None = None,
    plan_id: str = "standalone",
    step_id: str = "step-0",
    screenshot_config: Any | None = None,
    trusted_download_config: TrustedDownloadConfig | None = None,
    observation_reference: Any | None = None,
) -> ExecutionReceipt:
    if backend is None:
        return _execute_operation(
            operation,
            headless=headless,
            browser_config=browser_config,
            backend=None,
            plan_timing=plan_timing,
            plan_id=plan_id,
            step_id=step_id,
            screenshot_config=screenshot_config,
            trusted_download_config=trusted_download_config,
            observation_reference=observation_reference,
        )
    with backend.exclusive_use(f"operation:{operation.operation_id}"):
        return _execute_operation(
            operation,
            headless=headless,
            browser_config=browser_config,
            backend=backend,
            plan_timing=plan_timing,
            plan_id=plan_id,
            step_id=step_id,
            screenshot_config=screenshot_config,
            trusted_download_config=trusted_download_config,
            observation_reference=observation_reference,
        )
