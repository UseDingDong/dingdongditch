"""Non-invasive, high-resolution latency audit for DingDongDitch.

The benchmark monkey-patches call boundaries only for timing. It does not alter
arguments, return values, ordering, retry policy, evidence, or cleanup.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from playwright.sync_api import Page

from dingdongditch import (
    Action, ActionType, BrowserConfig, DownloadRequest, Expectation,
    ExpectationType, Locator, LocatorStrategy, Operation, PointerMoveRequest,
    PointerOrigin, ScreenshotConfig, ScreenshotPolicy, TrustedDownloadConfig,
    Verdict, WaitCondition, WaitConditionType, execute_operation, inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.operation import Operation as OperationContract
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.runtime import verifier
from dingdongditch.contract.modes import UrlMatchMode
FIXTURE_MODULE_DIR = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "local_test_app"
)
sys.path.insert(0, str(FIXTURE_MODULE_DIR))
from server import start_fixture_server  # noqa: E402

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "benchmark_results.json"
SAMPLES: dict[str, list[dict[str, Any]]] = defaultdict(list)
CURRENT = {"activity": "lifecycle", "operation_id": None}


def ns() -> int:
    return time.perf_counter_ns()


def record(stage: str, elapsed_ns: int, **detail: Any) -> None:
    SAMPLES[stage].append(
        {
            "duration_ns": elapsed_ns,
            "activity": CURRENT["activity"],
            "operation_id": CURRENT["operation_id"],
            **detail,
        }
    )


def timed(stage: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = ns()
        try:
            return fn(*args, **kwargs)
        finally:
            record(stage, ns() - started)
    return wrapper


def timed_wait(fn: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(self: Any, timeout: float, *args: Any, **kwargs: Any) -> Any:
        started = ns()
        try:
            return fn(self, timeout, *args, **kwargs)
        finally:
            record("wait_strategies", ns() - started, requested_ms=float(timeout))
    return wrapper


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def summary(total_ns: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for stage, rows in sorted(SAMPLES.items()):
        values = [row["duration_ns"] / 1_000_000 for row in rows]
        result[stage] = {
            "count": len(values),
            "average_ms": statistics.fmean(values),
            "median_ms": statistics.median(values),
            "p95_ms": percentile(values, 0.95),
            "p99_ms": percentile(values, 0.99),
            "maximum_ms": max(values),
            "aggregate_ms": sum(values),
            "percent_of_wall_runtime_inclusive": (
                sum(row["duration_ns"] for row in rows) / total_ns * 100
            ),
        }
    return result


def test_id(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def expectation_attr(target: str, name: str, value: str) -> list[Expectation]:
    return [
        Expectation(
            type=ExpectationType.ATTRIBUTE,
            locator=test_id(target),
            attribute_name=name,
            attribute_value=value,
        )
    ]


def measure_external(stage: str, fn: Callable[[], Any]) -> Any:
    started = ns()
    try:
        return fn()
    finally:
        record(stage, ns() - started)


def run_local(repetitions: int, artifact_root: Path) -> dict[str, Any]:
    server, url = start_fixture_server()
    config = BrowserConfig(headless=True)
    backend = PlaywrightBackend(
        config,
        trusted_download_config=TrustedDownloadConfig(
            artifact_root=str(artifact_root / "downloads")
        ),
    )
    receipts: list[ExecutionReceipt] = []
    activities: list[tuple[str, Callable[[int], Operation]]] = [
        (
            "navigation",
            lambda i: Operation(
                operation_id=f"nav-{i}", url=url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="index.html",
                        url_match=UrlMatchMode.CONTAINS,
                    )
                ],
            ),
        ),
        (
            "clicking",
            lambda i: Operation(
                operation_id=f"click-{i}", url=url,
                action=Action(type=ActionType.CLICK, locator=test_id("target-control")),
                expectations=expectation_attr("target-control", "data-state", "active"),
            ),
        ),
        (
            "typing",
            lambda i: Operation(
                operation_id=f"type-{i}", url=url,
                action=Action(
                    type=ActionType.FILL, locator=test_id("text-input"),
                    text=f"audit-{i}",
                ),
                expectations=expectation_attr("text-input", "value", f"audit-{i}"),
            ),
        ),
        (
            "pointer_movement",
            lambda i: Operation(
                operation_id=f"pointer-{i}", url=url,
                action=Action(
                    type=ActionType.POINTER_MOVE,
                    pointer_request=PointerMoveRequest(
                        origin=PointerOrigin.VIEWPORT,
                        x=100 + (i % 10), y=100 + (i % 10), steps=3,
                    ),
                ),
            ),
        ),
        (
            "scrolling",
            lambda i: Operation(
                operation_id=f"scroll-{i}", url=url,
                action=Action(
                    type=ActionType.SCROLL_TO_TARGET, locator=test_id("below-fold")
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ELEMENT_IN_VIEWPORT,
                        locator=test_id("below-fold"), in_viewport=True,
                    )
                ],
            ),
        ),
        (
            "wait_strategy",
            lambda i: Operation(
                operation_id=f"wait-{i}", url=url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.ELEMENT_VISIBLE,
                        locator=test_id("already-visible"),
                    ),
                    wait_timeout_ms=1_000,
                ),
            ),
        ),
        (
            "downloads",
            lambda i: Operation(
                operation_id=f"download-{i}", url=url,
                action=Action(
                    type=ActionType.DOWNLOAD,
                    locator=Locator(strategy=LocatorStrategy.CSS, value="#download-text"),
                    download_request=DownloadRequest(
                        preferred_filename=f"audit-{i}.txt",
                        allowed_extensions=(".txt",), minimum_bytes=1,
                    ),
                ),
            ),
        ),
    ]
    try:
        backend.start()
        for activity, factory in activities:
            for i in range(repetitions):
                # Navigation resets click and scroll state without introducing a
                # different code path inside the measured operation.
                if activity not in {"navigation", "downloads"}:
                    CURRENT.update(
                        activity="setup_reset",
                        operation_id=f"reset-{activity}-{i}",
                    )
                    execute_operation(
                        Operation(
                            operation_id=f"reset-{activity}-{i}", url=url,
                            action=Action(type=ActionType.NAVIGATE),
                        ),
                        backend=backend,
                        screenshot_config=ScreenshotConfig(
                            policy=ScreenshotPolicy.NEVER
                        ),
                    )
                op = factory(i)
                CURRENT.update(activity=activity, operation_id=op.operation_id)
                started = ns()
                receipt = execute_operation(
                    op,
                    backend=backend,
                    screenshot_config=ScreenshotConfig(
                        policy=ScreenshotPolicy.ALWAYS,
                        artifact_root=str(artifact_root / "screenshots"),
                    ),
                    plan_id="runtime-latency-audit",
                    step_id=f"{activity}-{i}",
                )
                record("total_operation", ns() - started)
                receipts.append(receipt)
                if not receipt.action_executed_successfully:
                    raise RuntimeError(
                        f"{activity} sample failed: {receipt.failure_kind}: "
                        f"{receipt.execution_error}"
                    )

                CURRENT.update(activity=activity, operation_id=op.operation_id)
                inspection = measure_external(
                    "inspection_generation",
                    lambda: inspect_target(backend, test_id("already-visible")),
                )
                encoded = measure_external(
                    "json_serialization",
                    lambda: json.dumps(receipt.to_dict(), sort_keys=True),
                )
                out = artifact_root / "receipts" / f"{activity}-{i}.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                measure_external(
                    "disk_io",
                    lambda: out.write_text(encoded, encoding="utf-8"),
                )
                assert inspection["match_count"] == 1
    finally:
        CURRENT.update(activity="cleanup", operation_id=None)
        backend.stop()
        server.shutdown()
        server.server_close()
    return {
        "url": url,
        "receipt_count": len(receipts),
        "verified_count": sum(r.verdict == Verdict.VERIFIED for r in receipts),
        "successful_action_count": sum(r.action_executed_successfully for r in receipts),
        "atomic_snapshot_count": backend._atomic_snapshot_count,
        "atomic_snapshot_fallback_count": backend._atomic_snapshot_fallback_count,
    }


def run_lifecycle(repetitions: int) -> None:
    for i in range(repetitions):
        CURRENT.update(activity="lifecycle", operation_id=f"lifecycle-{i}")
        backend = PlaywrightBackend(BrowserConfig(headless=True))
        backend.start()
        backend.stop()


def run_complex_app(
    url: str, repetitions: int, artifact_root: Path
) -> dict[str, Any]:
    if repetitions <= 0:
        return {"url": url, "repetitions": 0, "successful_action_count": 0}
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    successes = 0
    try:
        backend.start()
        for i in range(repetitions):
            operations = [
                (
                    "complex_app_navigation",
                    Operation(
                        operation_id=f"maps-nav-{i}",
                        url=url,
                        timeout_ms=30_000,
                        action=Action(type=ActionType.NAVIGATE),
                        expectations=[
                            Expectation(
                                type=ExpectationType.URL,
                                url_value="google.",
                                url_match=UrlMatchMode.CONTAINS,
                            )
                        ],
                    ),
                ),
            ]
            for activity, operation in operations:
                CURRENT.update(
                    activity=activity, operation_id=operation.operation_id
                )
                started = ns()
                receipt = execute_operation(
                    operation,
                    backend=backend,
                    screenshot_config=ScreenshotConfig(
                        policy=ScreenshotPolicy.ALWAYS,
                        artifact_root=str(artifact_root / "complex_screenshots"),
                    ),
                    plan_id="runtime-latency-audit-complex",
                    step_id=f"{activity}-{i}",
                )
                record("total_operation", ns() - started)
                if receipt.action_executed_successfully:
                    successes += 1
                encoded = measure_external(
                    "json_serialization",
                    lambda: json.dumps(receipt.to_dict(), sort_keys=True),
                )
                path = artifact_root / "complex_receipts" / f"{activity}-{i}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                measure_external(
                    "disk_io", lambda: path.write_text(encoded, encoding="utf-8")
                )
            pointer = Operation(
                operation_id=f"maps-pointer-{i}",
                url=backend.page.url,
                action=Action(
                    type=ActionType.POINTER_MOVE,
                    pointer_request=PointerMoveRequest(
                        origin=PointerOrigin.VIEWPORT,
                        x=640, y=360, steps=8,
                    ),
                ),
            )
            CURRENT.update(
                activity="complex_app_pointer", operation_id=pointer.operation_id
            )
            started = ns()
            pointer_receipt = execute_operation(pointer, backend=backend)
            record("total_operation", ns() - started)
            if pointer_receipt.action_executed_successfully:
                successes += 1
            CURRENT.update(activity="complex_app_inspection", operation_id=f"maps-inspect-{i}")
            measure_external(
                "inspection_generation",
                lambda: inspect_target(
                    backend, Locator(strategy=LocatorStrategy.CSS, value="body")
                ),
            )
    finally:
        CURRENT.update(activity="cleanup", operation_id=None)
        backend.stop()
    return {
        "url": url,
        "repetitions": repetitions,
        "successful_action_count": successes,
        "atomic_snapshot_count": backend._atomic_snapshot_count,
        "atomic_snapshot_fallback_count": backend._atomic_snapshot_fallback_count,
    }


def run_validation(repetitions: int) -> None:
    for i in range(repetitions * 10):
        CURRENT.update(activity="validation", operation_id=f"validate-{i}")
        ExecutionPlan(
            plan_id=f"validation-{i}",
            browser_config=BrowserConfig(headless=True),
            operations=[
                Operation(
                    operation_id=f"operation-{i}",
                    url="https://example.invalid/",
                    action=Action(type=ActionType.NAVIGATE),
                )
            ],
        ).validate()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--complex-repetitions", type=int, default=0)
    parser.add_argument(
        "--complex-url", default="https://maps.google.com/",
    )
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    started = ns()
    with tempfile.TemporaryDirectory(prefix="ddd-latency-audit-") as temp:
        artifacts = Path(temp)
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    ExecutionPlan, "validate",
                    timed("execution_plan_validation", ExecutionPlan.validate),
                )
            )
            stack.enter_context(
                patch.object(
                    OperationContract, "validate",
                    timed("operation_validation", OperationContract.validate),
                )
            )
            stack.enter_context(
                patch.object(
                    PlaywrightBackend, "dispatch",
                    timed("action_dispatch", PlaywrightBackend.dispatch),
                )
            )
            stack.enter_context(
                patch.object(
                    PlaywrightBackend, "_dispatch_core",
                    timed("backend_execution", PlaywrightBackend._dispatch_core),
                )
            )
            stack.enter_context(
                patch.object(
                    PlaywrightBackend, "_resolve_scoped_target",
                    timed(
                        "target_resolution",
                        PlaywrightBackend._resolve_scoped_target,
                    ),
                )
            )
            stack.enter_context(
                patch.object(
                    PlaywrightBackend, "observe",
                    timed("evidence_observation", PlaywrightBackend.observe),
                )
            )
            stack.enter_context(
                patch.object(
                    PlaywrightBackend, "capture_screenshot",
                    timed(
                        "screenshot_capture",
                        PlaywrightBackend.capture_screenshot,
                    ),
                )
            )
            stack.enter_context(
                patch.object(
                    PlaywrightBackend, "start",
                    timed("browser_startup", PlaywrightBackend.start),
                )
            )
            stack.enter_context(
                patch.object(
                    PlaywrightBackend, "stop",
                    timed("cleanup", PlaywrightBackend.stop),
                )
            )
            stack.enter_context(
                patch.object(
                    Page, "wait_for_timeout",
                    timed_wait(Page.wait_for_timeout),
                )
            )
            stack.enter_context(
                patch.object(
                    verifier, "evaluate_expectations",
                    timed(
                        "verification_evaluation",
                        verifier.evaluate_expectations,
                    ),
                )
            )
            # executor imported the verifier function directly.
            import dingdongditch.runtime.executor as executor
            real_receipt = executor.ExecutionReceipt
            stack.enter_context(
                patch.object(
                    executor, "ExecutionReceipt",
                    timed("receipt_generation", real_receipt),
                )
            )
            stack.enter_context(
                patch.object(
                    executor, "evaluate_expectations",
                    timed(
                        "verification",
                        executor.evaluate_expectations,
                    ),
                )
            )
            local = run_local(args.repetitions, artifacts)
            complex_app = run_complex_app(
                args.complex_url, args.complex_repetitions, artifacts
            )
            run_lifecycle(max(5, args.repetitions // 2))
            run_validation(args.repetitions)

    total_ns = ns() - started
    payload = {
        "schema_version": 1,
        "timer": "time.perf_counter_ns",
        "repetitions_per_activity": args.repetitions,
        "wall_runtime_ms": total_ns / 1_000_000,
        "local_benchmark": local,
        "complex_app_benchmark": complex_app,
        "summary": summary(total_ns),
        "samples": SAMPLES,
        "notes": [
            "Stage percentages are inclusive and can overlap for nested call boundaries.",
            "Reset navigation is excluded from total_operation samples but included in wall runtime.",
            "All screenshots, receipts, inspections, verification, and cleanup remain enabled.",
        ],
    }
    RAW.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"result": str(RAW), "wall_runtime_ms": payload["wall_runtime_ms"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
