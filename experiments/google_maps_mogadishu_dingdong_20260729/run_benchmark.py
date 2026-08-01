"""Production Google Maps benchmark using only DingDongDitch plans."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from dingdongditch import (
    Action, ActionType, BrowserConfig, BrowserProfile, ConstraintType,
    ExecutionPlan, Expectation, ExpectationType, KeyPressScope, Locator,
    LocatorStrategy, NameMatchMode, Operation, ScreenshotConfig,
    ScreenshotPolicy, TargetConstraint, WaitCondition, WaitConditionType,
    PageCondition, PageConditionType, PagePrecondition, execute_plan,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode

ROOT = Path(__file__).resolve().parent / "attempt-9"
RECEIPTS, SCREENSHOTS, INSPECTIONS = (
    ROOT / "receipts", ROOT / "screenshots", ROOT / "inspections"
)
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS):
    directory.mkdir(parents=True, exist_ok=True)

ENTRY_URL = "https://maps.google.com"
URL = "https://www.google.com/maps"
CONFIG = BrowserConfig(headless=False, profile=BrowserProfile.DINGDONG)
VISIBLE = (TargetConstraint(type=ConstraintType.VISIBLE, visible=True),)
SEARCH = Locator(
    strategy=LocatorStrategy.ROLE_NAME, role="combobox",
    name="Search Google Maps", name_match=NameMatchMode.EXACT,
)
POPULATED_SEARCH = Locator(
    strategy=LocatorStrategy.CSS, value="input", constraints=VISIBLE
)
ZOOM_OUT = Locator(
    strategy=LocatorStrategy.CSS, value="button[aria-label='Zoom out']",
    constraints=VISIBLE,
)
ZOOM_IN = Locator(
    strategy=LocatorStrategy.CSS, value="button[aria-label='Zoom in']",
    constraints=VISIBLE,
)
MAP = Locator(
    strategy=LocatorStrategy.CSS, value="div.widget-scene",
    constraints=VISIBLE,
)
BODY = Locator(strategy=LocatorStrategy.CSS, value="body")
MAP_PRECONDITION = PagePrecondition(
    conditions=(
        PageCondition(
            condition_id="maps-origin",
            type=PageConditionType.ORIGIN_EQUALS,
            origin_value="https://www.google.com",
        ),
        PageCondition(
            condition_id="maps-path",
            type=PageConditionType.PATH_STARTS_WITH,
            path_value="/maps",
        ),
    )
)

receipts: list[dict[str, Any]] = []
inspection_latencies: list[float] = []
verification_latencies: list[float] = []


def task_pids() -> set[tuple[str, int]]:
    output = subprocess.run(
        ["tasklist"], capture_output=True, text=True, check=False
    ).stdout
    found = set()
    for line in output.splitlines():
        match = re.match(r"(chrome|node|python|playwright)\.exe\s+(\d+)", line, re.I)
        if match:
            found.add((match.group(1).lower(), int(match.group(2))))
    return found


def url_expectation() -> Expectation:
    return Expectation(
        type=ExpectationType.URL, url_value="google.com/maps",
        url_match=UrlMatchMode.CONTAINS,
    )


def run_plan(backend: PlaywrightBackend, plan_id: str, operation: Operation):
    if operation.action.type != ActionType.NAVIGATE:
        operation.page_precondition = MAP_PRECONDITION
    result = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=[operation],
            browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS,
                artifact_root=str(SCREENSHOTS),
                max_per_plan=1,
            ),
            initial_plan_timeout_ms=45_000,
            max_plan_timeout_ms=45_000,
        ),
        backend=backend,
    )
    data = result.to_dict()
    receipts.append(data)
    (RECEIPTS / f"{len(receipts):02d}_{plan_id}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    for step in result.steps:
        item = step.receipt
        if (
            item is not None
            and item.action_completed_at_ms is not None
            and item.verification_completed_at_ms is not None
        ):
            verification_latencies.append(
                item.verification_completed_at_ms - item.action_completed_at_ms
            )
    if result.plan_verdict.value != "VERIFIED":
        raise RuntimeError(f"{plan_id} was {result.plan_verdict.value}")
    return result


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict[str, Any]:
    started = time.perf_counter()
    result = inspect_target(backend, locator)
    inspection_latencies.append((time.perf_counter() - started) * 1000)
    (INSPECTIONS / f"{len(inspection_latencies):02d}_{label}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def wait_visible(backend: PlaywrightBackend, label: str, locator: Locator) -> None:
    run_plan(
        backend, label,
        Operation(
            operation_id=label, url=URL, timeout_ms=35_000,
            action=Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE, locator=locator
                ),
                wait_timeout_ms=30_000,
            ),
            expectations=[url_expectation()],
        ),
    )
    state = inspect(backend, label, locator)
    if state.get("match_count") != 1 or state.get("visible") is not True:
        raise RuntimeError(f"{label} did not resolve to one visible target")


def click(backend: PlaywrightBackend, plan_id: str, locator: Locator) -> None:
    run_plan(
        backend, plan_id,
        Operation(
            operation_id=plan_id, url=URL,
            action=Action(type=ActionType.CLICK, locator=locator),
            expectations=[url_expectation()],
        ),
    )


def press(backend: PlaywrightBackend, plan_id: str, key: str) -> None:
    run_plan(
        backend, plan_id,
        Operation(
            operation_id=plan_id, url=URL,
            action=Action(
                type=ActionType.PRESS_KEY, key=key,
                key_scope=KeyPressScope.ACTIVE_PAGE,
            ),
            expectations=[url_expectation()],
        ),
    )


def search(backend: PlaywrightBackend, label: str, query: str) -> None:
    run_plan(
        backend, f"fill_{label}",
        Operation(
            operation_id=f"fill-{label}", url=URL,
            action=Action(
                type=ActionType.FILL, locator=POPULATED_SEARCH, text=query
            ),
            expectations=[url_expectation()],
        ),
    )
    run_plan(
        backend, f"submit_{label}",
        Operation(
            operation_id=f"submit-{label}", url=URL,
            action=Action(
                type=ActionType.PRESS_KEY, locator=POPULATED_SEARCH, key="Enter"
            ),
            expectations=[url_expectation()],
        ),
    )


def main() -> int:
    before_pids = task_pids()
    backend = PlaywrightBackend(CONFIG)
    total_started = time.perf_counter()
    launch_seconds = cleanup_seconds = 0.0
    status, error = "FAIL", None
    redirects: list[dict[str, Any]] = []
    friction: list[str] = []
    final_url = ""
    try:
        launched = time.perf_counter()
        backend.start()
        launch_seconds = time.perf_counter() - launched
        run_plan(
            backend, "open_google_maps",
            Operation(
                operation_id="open-google-maps", url=ENTRY_URL,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[url_expectation()],
            ),
        )
        wait_visible(backend, "wait_search_ready", SEARCH)
        wait_visible(backend, "wait_zoom_out_ready", ZOOM_OUT)

        for index in range(4):
            click(backend, f"zoom_out_{index + 1}", ZOOM_OUT)

        search(backend, "africa", "Africa")
        search(backend, "somalia", "Somalia")
        wait_visible(backend, "wait_zoom_in_somalia", ZOOM_IN)
        for index in range(3):
            click(backend, f"zoom_into_somalia_{index + 1}", ZOOM_IN)

        search(backend, "mogadishu", "Mogadishu, Somalia")
        search(backend, "mogadishu_coordinates", "2.0372133, 45.3379172")
        run_plan(
            backend, "verify_mogadishu",
            Operation(
                operation_id="verify-mogadishu", url=URL, timeout_ms=35_000,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.TEXT_PRESENT, locator=BODY,
                        text_value="Mogadishu", text_match=TextMatchMode.CONTAINS,
                    ),
                    wait_timeout_ms=30_000,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.TEXT, locator=BODY,
                        text_value="Somalia", text_match=TextMatchMode.CONTAINS,
                    )
                ],
            ),
        )
        final = inspect(backend, "final_mogadishu", BODY)
        final_text = str(final.get("text", ""))
        if "mogadishu" not in final_text.lower() or "somalia" not in final_text.lower():
            raise RuntimeError("final inspection did not show Mogadishu, Somalia")
        final_url = str(final["page"]["url"])
        if "sign in" in final_text.lower():
            friction.append("Google Maps displayed its optional sign-in request")
        status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        redirects = [
            {"status": item.status, "url": item.url}
            for item in backend._network
            if item.status is not None and 300 <= item.status < 400
        ]
        cleanup_started = time.perf_counter()
        backend.stop()
        cleanup_seconds = time.perf_counter() - cleanup_started

    total_seconds = time.perf_counter() - total_started
    after_pids = task_pids()
    remaining = sorted(after_pids - before_pids)
    if remaining:
        status = "FAIL"
        error = error or f"new relevant processes remain: {remaining}"
    report = {
        "status": status,
        "error": error,
        "browser_profile": CONFIG.profile.value,
        "final_url": final_url,
        "total_execution_seconds": total_seconds,
        "browser_launch_seconds": launch_seconds,
        "cleanup_seconds": cleanup_seconds,
        "average_verification_latency_ms": (
            sum(verification_latencies) / len(verification_latencies)
            if verification_latencies else None
        ),
        "average_inspection_latency_ms": (
            sum(inspection_latencies) / len(inspection_latencies)
            if inspection_latencies else None
        ),
        "receipt_count": len(receipts),
        "screenshot_count": len(list(SCREENSHOTS.glob("*.png"))),
        "inspection_count": len(inspection_latencies),
        "redirect_count": len(redirects),
        "redirects": redirects,
        "friction": friction,
        "dingdong_owned_processes_remaining": len(remaining),
        "remaining_processes": remaining,
    }
    (ROOT / "benchmark_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
