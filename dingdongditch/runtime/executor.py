from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
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
from dingdongditch.authentication import AuthenticationCapability
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.bounded import bounded_signals, sanitize_evidence_value
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


def _operation_timing(
    *,
    started_at: int,
    finished_at: int,
    action_started_at: int | None = None,
    action_completed_at: int | None = None,
    verification_started_at: int | None = None,
    verification_completed_at: int | None = None,
    target_resolution: dict | None = None,
    action_type: ActionType | None = None,
    include_verification: bool = False,
    startup_ms: int | None = None,
) -> dict[str, int]:
    """Derive one stable receipt timing schema from monotonic runtime facts."""
    timing: dict[str, int] = {"total_ms": max(0, finished_at - started_at)}
    if startup_ms is not None:
        timing["startup_ms"] = max(0, startup_ms)
    resolution_ms: int | None = None
    if action_started_at is not None and target_resolution is not None:
        stage_times = [
            stage.get("timestamp_ms")
            for stage in target_resolution.get("stages", [])
            if isinstance(stage, dict) and isinstance(stage.get("timestamp_ms"), int)
        ]
        if stage_times:
            resolution_ms = max(0, max(stage_times) - action_started_at)
            timing["target_resolution_ms"] = resolution_ms
    if action_started_at is not None and action_completed_at is not None:
        elapsed = max(0, action_completed_at - action_started_at)
        timing["dispatch_ms"] = max(0, elapsed - (resolution_ms or 0))
        if action_type == ActionType.NAVIGATE:
            timing["navigation_ms"] = elapsed
    if action_completed_at is not None and verification_started_at is not None:
        timing["settle_ms"] = max(0, verification_started_at - action_completed_at)
    if (
        include_verification
        and verification_started_at is not None
        and verification_completed_at is not None
    ):
        timing["verification_ms"] = max(
            0, verification_completed_at - verification_started_at
        )
    return timing


def _backend_startup_ms(backend: PlaywrightBackend, *, operation_started_at: int) -> int | None:
    started = None
    finished = None
    for event in backend.telemetry:
        if event.get("event") == "backend_start_started_at" and event.get("at_ms", 0) >= operation_started_at:
            started = event.get("at_ms")
        if event.get("event") == "backend_start_finished_at" and started is not None:
            finished = event.get("at_ms")
    if isinstance(started, int) and isinstance(finished, int):
        return max(0, finished - started)
    return None


def _screenshot_artifact_reference(shot: dict[str, Any]) -> dict[str, Any]:
    """Convert backend screenshot facts to a safe Layer-3 reference."""
    identity = "|".join(
        str(shot.get(key) or "")
        for key in ("plan_id", "step_id", "operation_id", "page_id", "timestamp_ms")
    )
    artifact_id = "screenshot-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    raw_path = shot.get("artifact_path")
    return {
        "artifact_id": artifact_id,
        "kind": "screenshot",
        "status": "available" if shot.get("captured") else "failed",
        "reason": shot.get("reason"),
        "filename": Path(raw_path).name if isinstance(raw_path, str) and raw_path else None,
        "capture_duration_ms": max(0, int(shot.get("capture_duration_ms") or 0)),
        "redaction": {
            "status": shot.get("redaction_status"),
            "requested": bool(shot.get("redaction_requested")),
            "match_count": int(shot.get("redaction_match_count") or 0),
        },
    }


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
    verdict: Verdict = Verdict.EXECUTION_FAILED,
) -> ExecutionReceipt:
    finished = monotonic_ms()
    return ExecutionReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        operation_id=operation.operation_id,
        verdict=verdict,
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
        evidence=bounded_signals(collector.signals),
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
        action_evidence=sanitize_evidence_value(action_evidence) if action_evidence else None,
        page_precondition=(action_evidence or {}).get("page_precondition"),
        navigation_occurred=False,
        dispatch_document_url=(action_evidence or {}).get("actual_url"),
        operation_timing=_operation_timing(
            started_at=started_at,
            finished_at=finished,
            action_type=operation.action.type,
        ),
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
    authentication: AuthenticationCapability | None = None,
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
    elif operation.action.frame_path:
        locator_desc = {
            "locator": locator_desc,
            "frame_path": [frame.describe() for frame in operation.action.frame_path],
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
    elif (
        operation.action.type == ActionType.WAIT_FOR
        and operation.action.wait_condition is not None
        and operation.action.wait_condition.frame_path
    ):
        wc = operation.action.wait_condition
        locator_desc = {
            "locator": wc.locator.describe() if wc.locator else None,
            "frame_path": [frame.describe() for frame in wc.frame_path],
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
        from dingdongditch.contract.upload import UploadValidationError
        return _failed_receipt(
            operation=operation,
            started_at=started_at,
            collector=collector,
            locator_desc=locator_desc,
            execution_status="validation_failed",
            execution_error=str(exc),
            failure_kind=(
                exc.failure_kind if isinstance(exc, UploadValidationError) else None
            ),
            browser=resolved_config.describe(),
            backend_identity="playwright-sync",
            browser_identity=resolved_config.engine.value,
        )

    if owns_backend:
        try:
            backend = PlaywrightBackend(
                browser_config=resolved_config,
                trusted_download_config=trusted_download_config,
                authentication=authentication,
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
    verification_started: int | None = None
    verification_completed: int | None = None
    execution_status = "not_started"
    execution_error: str | None = None
    action_ok = False
    expectation_results = []
    recovery_attempts: list[RecoveryAttempt] = []
    target_resolution: dict | None = None
    failure_kind: str | None = None
    action_evidence: dict | None = None
    webauthn_participation: dict[str, Any] | None = None
    observation_validation: dict[str, Any] | None = None
    guard_branch: str | None = None
    guard_probe_resolution: dict[str, Any] | None = None
    active_expectations = operation.expectations
    guarded_skip = False
    branch_guard_evidence: dict[str, Any] | None = None

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
                evidence=bounded_signals(collector.signals),
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
                operation_timing=_operation_timing(
                    started_at=started_at,
                    finished_at=completed,
                    action_type=operation.action.type,
                    startup_ms=(
                        _backend_startup_ms(backend, operation_started_at=started_at)
                        if owns_backend
                        else None
                    ),
                ),
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

        if operation.guard is not None and not operation.guard.is_legacy_target_absent:
            # Branch conditions are observations, not predicates.  They are
            # evaluated in authored order and every condition must pass.  A
            # stale/indeterminate condition prevents selection even if another
            # branch would otherwise match; this keeps mutually-exclusive UI
            # state fail-closed.
            condition_started = monotonic_ms()
            branch_records: list[dict[str, Any]] = []
            matched_branches = []
            any_indeterminate = False
            latest_network = {"records": []}
            for signal in reversed(collector.signals):
                if signal.kind.value == "network" and "records" in signal.payload:
                    latest_network = signal.payload
                    break
            for branch in operation.guard.branches:
                checked_at = monotonic_ms()
                results = evaluate_expectations(
                    backend=backend,
                    expectations=list(branch.when),
                    collector=collector,
                    action_started_at_ms=condition_started,
                    verification_completed_at_ms=checked_at,
                    freshness=operation.freshness,
                    post_network_payload=latest_network,
                    post_url=backend.page.url,
                )
                passed = bool(results) and all(item.result == "pass" for item in results)
                indeterminate = any(item.result == "indeterminate" for item in results)
                branch_records.append(
                    {
                        "branch_id": branch.branch_id,
                        "evaluation_order": len(branch_records),
                        "matched": passed,
                        "indeterminate": indeterminate,
                        "condition_results": [item.to_dict() for item in results],
                        "skipped": False,
                    }
                )
                if passed:
                    matched_branches.append(branch)
                if indeterminate:
                    any_indeterminate = True

            branch_guard_evidence = {
                "guarded": True,
                "guard_mode": "declared_branches",
                "branches_evaluated": branch_records,
                "matched_branch_ids": [branch.branch_id for branch in matched_branches],
                "selected_branch": None,
                "skipped_branches": [
                    record["branch_id"] for record in branch_records if not record["matched"]
                ],
                "branch_actions": [],
                "primary_action_dispatched": False,
            }
            if any_indeterminate:
                branch_guard_evidence["failure_reason"] = "guard_condition_indeterminate"
                return _failed_receipt(
                    operation=operation,
                    started_at=started_at,
                    collector=collector,
                    locator_desc=locator_desc,
                    execution_status="guard_condition_indeterminate",
                    execution_error="a declared guard condition was stale or indeterminate",
                    failure_kind="guard_condition_indeterminate",
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                    action_evidence={"guard": branch_guard_evidence},
                    verdict=Verdict.INDETERMINATE,
                )
            if len(matched_branches) > 1:
                branch_guard_evidence["ambiguous_matches"] = [
                    branch.branch_id for branch in matched_branches
                ]
                branch_guard_evidence["failure_reason"] = "guard_ambiguous_matches"
                return _failed_receipt(
                    operation=operation,
                    started_at=started_at,
                    collector=collector,
                    locator_desc=locator_desc,
                    execution_status="guard_ambiguous_matches",
                    execution_error="multiple declared mutually-exclusive guard branches matched",
                    failure_kind="guard_ambiguous_matches",
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                    action_evidence={"guard": branch_guard_evidence},
                    verdict=Verdict.INDETERMINATE,
                )
            if matched_branches:
                selected_id = matched_branches[0].branch_id
                selected_actions = matched_branches[0].execute
            elif operation.guard.otherwise is not None:
                selected_id = "otherwise"
                selected_actions = operation.guard.otherwise
                branch_guard_evidence["fallback_used"] = True
            else:
                branch_guard_evidence["failure_reason"] = "guard_no_branch_matched"
                return _failed_receipt(
                    operation=operation,
                    started_at=started_at,
                    collector=collector,
                    locator_desc=locator_desc,
                    execution_status="guard_no_branch_matched",
                    execution_error="no declared guard branch matched and no otherwise branch exists",
                    failure_kind="guard_no_branch_matched",
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                    action_evidence={"guard": branch_guard_evidence},
                    verdict=Verdict.NOT_VERIFIED,
                )

            branch_guard_evidence["selected_branch"] = selected_id
            for index, branch_action in enumerate(selected_actions):
                # The action inherits the operation's page/session boundaries
                # but cannot carry its own guard or expectations.  This is a
                # finite preparation list, not nested plan execution.
                branch_operation = replace(
                    operation,
                    action=branch_action,
                    expectations=[],
                    guard=None,
                )
                dispatched = backend.dispatch(
                    branch_operation, collector=collector, plan_timing=plan_timing
                )
                action_record = {
                    "index": index,
                    "action_type": branch_action.type.value,
                    "dispatched": dispatched.ok,
                    "failure_kind": dispatched.failure_kind,
                    "target_resolution": (
                        dispatched.resolution_trace.to_dict()
                        if dispatched.resolution_trace is not None
                        else None
                    ),
                }
                branch_guard_evidence["branch_actions"].append(action_record)
                if not dispatched.ok:
                    branch_guard_evidence["failure_reason"] = "guard_branch_action_failed"
                    return _failed_receipt(
                        operation=operation,
                        started_at=started_at,
                        collector=collector,
                        locator_desc=locator_desc,
                        execution_status="guard_branch_action_failed",
                        execution_error=(
                            dispatched.error
                            or "selected guard branch action did not complete"
                        ),
                        failure_kind=(
                            dispatched.failure_kind or "guard_branch_action_failed"
                        ),
                        browser=backend.browser_environment(),
                        backend_identity=backend.backend_identity,
                        browser_identity=backend.browser_identity,
                        action_evidence={"guard": branch_guard_evidence},
                        target_resolution=action_record["target_resolution"],
                    )
                for raw in dispatched.recovery_attempts:
                    recovery_attempts.append(
                        RecoveryAttempt(
                            reason=raw["reason"],
                            attempt_index=raw["attempt_index"],
                            occurred_at_ms=raw["occurred_at_ms"],
                            detail=raw.get("detail", ""),
                        )
                    )

        if operation.guard is not None and operation.guard.is_legacy_target_absent:
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
            if operation.guard is not None and operation.guard.is_legacy_target_absent:
                action_evidence = dict(action_evidence or {})
                action_evidence.update({
                    "guarded": True, "branch": "target_present", "skipped": False,
                    "already_satisfied": False,
                    "guard_target_resolution": guard_probe_resolution,
                })
            elif branch_guard_evidence is not None:
                action_evidence = dict(action_evidence or {})
                branch_guard_evidence["primary_action_dispatched"] = bool(dispatch.ok)
                action_evidence["guard"] = branch_guard_evidence
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

        if action_ok and not guarded_skip and operation.webauthn is not None:
            webauthn_participation = backend.participate_webauthn(operation.webauthn)
            action_evidence = dict(action_evidence or {})
            action_evidence["webauthn"] = webauthn_participation

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

        verification_started = monotonic_ms()
        verification_completed = verification_started
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

        if action_ok and webauthn_participation is not None:
            status = webauthn_participation.get("status")
            if status == "rejected":
                verdict = Verdict.NOT_VERIFIED
                failure_kind = "webauthn_host_rejected"
                execution_status = "webauthn_rejected"
                execution_error = "host rejected WebAuthn participation"
            elif status in {"unsupported", "timed_out", "indeterminate"}:
                verdict = Verdict.INDETERMINATE
                failure_kind = f"webauthn_{status}"
                execution_status = f"webauthn_{status}"
                execution_error = "WebAuthn participation did not complete"
            elif status == "completed" and not active_expectations:
                # A host callback is not browser proof.  Only independently
                # declared post-action expectations may establish VERIFIED.
                verdict = Verdict.INDETERMINATE
                failure_kind = "webauthn_completion_not_browser_verification"
                execution_status = "webauthn_completed_unverified"

        if operation.guard is not None and operation.guard.is_legacy_target_absent:
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
            evidence=bounded_signals(collector.signals),
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
            expectation_evidence=[
                result.failure_evidence
                for result in expectation_results
                if result.failure_evidence is not None
            ],
            operation_timing=_operation_timing(
                started_at=started_at,
                finished_at=finished,
                action_started_at=action_started,
                action_completed_at=action_completed,
                verification_started_at=verification_started,
                verification_completed_at=verification_completed,
                target_resolution=target_resolution,
                action_type=operation.action.type,
                include_verification=bool(active_expectations and action_ok),
                startup_ms=(
                    _backend_startup_ms(backend, operation_started_at=started_at)
                    if owns_backend
                    else None
                ),
            ),
        )

        from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
        if operation.network_artifact is not None:
            network_artifact = backend.capture_network_artifact(
                operation_id=operation.operation_id,
                action_started_at_ms=action_started,
                request=operation.network_artifact,
            )
            receipt.artifacts = [network_artifact]
            receipt.action_evidence = dict(receipt.action_evidence or {})
            receipt.action_evidence.setdefault("artifact_ids", []).append(
                network_artifact["artifact_id"]
            )
        config = screenshot_config or operation.screenshot_config or ScreenshotConfig()
        policy = config.policy
        should_capture = policy in {ScreenshotPolicy.ALWAYS, ScreenshotPolicy.AFTER_SUCCESS} and verdict == Verdict.VERIFIED
        should_capture = should_capture or policy == ScreenshotPolicy.ON_FAILURE and verdict != Verdict.VERIFIED
        should_capture = should_capture or policy == ScreenshotPolicy.BEFORE_AND_AFTER
        if should_capture and config.max_per_operation > 0:
            shot = backend.capture_screenshot(plan_id=plan_id, step_id=step_id, operation_id=operation.operation_id, reason="after_success" if verdict == Verdict.VERIFIED else "failure", config=config)
            receipt.action_evidence = dict(receipt.action_evidence or {})
            artifact = _screenshot_artifact_reference(shot)
            receipt.artifacts = [*(receipt.artifacts or []), artifact]
            receipt.action_evidence.setdefault("artifact_ids", []).append(artifact["artifact_id"])
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
        receipt.action_evidence = sanitize_evidence_value(receipt.action_evidence)
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
    authentication: AuthenticationCapability | None = None,
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
            authentication=authentication,
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
            authentication=authentication,
            observation_reference=observation_reference,
        )
