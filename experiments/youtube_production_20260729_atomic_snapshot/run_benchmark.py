"""Fresh production YouTube benchmark for the Atomic Snapshot runtime."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserChannel, BrowserConfig, BrowserEngine, BrowserProvider
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import UrlMatchMode
from dingdongditch.contract.operation import Action, ActionType, KeyPressScope, Locator, LocatorStrategy, Operation
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.pointer import PointerMoveRequest, PointerOrigin
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.contract.wait import LoadState, WaitCondition, WaitConditionType
from dingdongditch.inspection import inspect_target
from dingdongditch.runtime.plan_executor import execute_plan

HERE = Path(__file__).resolve().parent
RECEIPTS = HERE / "receipts"
INSPECTIONS = HERE / "inspections"
SCREENSHOTS = HERE / "screenshots"
QUERY = "Somalia drone footage"
HOME = "https://www.youtube.com/"
SEARCH_URL = f"https://www.youtube.com/results?search_query={quote_plus(QUERY)}"
VIDEO = Locator(strategy=LocatorStrategy.CSS, value="video.html5-main-video")

CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
SHOT_CONFIG = ScreenshotConfig(
    policy=ScreenshotPolicy.AFTER_SUCCESS,
    full_page=False,
    max_per_operation=1,
    max_per_plan=64,
    artifact_root=str(SCREENSHOTS),
    capture_timeout_ms=5_000,
)

receipts: list[dict[str, Any]] = []
inspections: list[dict[str, Any]] = []
timeline: list[dict[str, Any]] = []
unexpected_waits: list[dict[str, Any]] = []


def css(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.CSS, value=value)


def op(operation_id: str, url: str, action: Action, expectations: list[Expectation] | None = None,
       timeout_ms: int = 30_000) -> Operation:
    return Operation(
        operation_id=operation_id,
        url=url,
        action=action,
        expectations=expectations or [],
        timeout_ms=timeout_ms,
        locate_retry_ms=5_000,
    )


def snapshot_processes() -> list[dict[str, Any]]:
    cmd = [
        "powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process | Where-Object {$_.Name -match 'chrome|chromium|playwright'} "
        "| Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Depth 3",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        value = json.loads(result.stdout) if result.stdout.strip() else []
        return value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        return [{"snapshot_error": result.stderr or result.stdout}]


def inspect(backend: PlaywrightBackend, name: str, locator: Locator) -> dict[str, Any]:
    started = time.perf_counter_ns()
    data = inspect_target(backend, locator)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    record = {"name": name, "latency_ms": elapsed_ms, "data": data}
    inspections.append(record)
    (INSPECTIONS / f"{len(inspections):03d}_{name}.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    return record


def run_plan(backend: PlaywrightBackend, plan_id: str, operations: list[Operation]) -> dict[str, Any]:
    plan = ExecutionPlan(
        plan_id=plan_id,
        operations=operations,
        browser_config=CONFIG,
        initial_plan_timeout_ms=180_000,
        adaptive_timeout_enabled=False,
        screenshot_config=SHOT_CONFIG,
    )
    plan.validate()
    plan_doc = {
        "plan_id": plan_id,
        "browser_config": CONFIG.describe(),
        "operations": [
            {
                **item.to_public_dict(),
                "expectations": [expectation.describe() for expectation in item.expectations],
            }
            for item in operations
        ],
    }
    (RECEIPTS / f"{len(receipts)+1:03d}_{plan_id}_plan.json").write_text(
        json.dumps(plan_doc, indent=2), encoding="utf-8"
    )
    started = time.perf_counter_ns()
    receipt = execute_plan(plan, backend=backend)
    wall_ms = (time.perf_counter_ns() - started) / 1_000_000
    data = receipt.to_dict()
    data["_benchmark_wall_ms"] = wall_ms
    receipts.append(data)
    (RECEIPTS / f"{len(receipts):03d}_{plan_id}_receipt.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    timeline.append({"plan_id": plan_id, "wall_ms": wall_ms, "verdict": receipt.plan_verdict.value})
    if receipt.plan_verdict.value != "VERIFIED":
        raise RuntimeError(f"{plan_id} failed: {receipt.failure_kind}: {receipt.execution_error}")
    return data


def visible_first(backend: PlaywrightBackend, candidates: list[tuple[str, str]]) -> tuple[str, Locator] | None:
    for name, selector in candidates:
        locator = css(selector)
        result = inspect(backend, f"candidate_{name}", locator)
        data = result["data"]
        if data.get("match_count") == 1 and data.get("visible"):
            return name, locator
    return None


def pointer(backend: PlaywrightBackend, plan_id: str, url: str, locator: Locator) -> None:
    run_plan(backend, plan_id, [
        op(plan_id, url, Action(
            type=ActionType.POINTER_MOVE,
            locator=locator,
            pointer_request=PointerMoveRequest(
                origin=PointerOrigin.ELEMENT_CENTER, steps=12, verify_position=True
            ),
        ), [
            Expectation(type=ExpectationType.URL, url_value=url, url_match=UrlMatchMode.EXACT)
        ])
    ])


def dwell(seconds: float, label: str) -> None:
    started = time.perf_counter()
    time.sleep(seconds)
    actual = time.perf_counter() - started
    timeline.append({"host_wait": label, "requested_s": seconds, "actual_s": actual})
    if actual > seconds + 1.0:
        unexpected_waits.append({"label": label, "requested_s": seconds, "actual_s": actual})


def main() -> int:
    for directory in (HERE, RECEIPTS, INSPECTIONS, SCREENSHOTS):
        directory.mkdir(parents=True, exist_ok=True)
    benchmark_start = time.perf_counter_ns()
    before = snapshot_processes()
    (HERE / "processes_before.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
    backend = PlaywrightBackend(browser_config=CONFIG)
    launch_ms = cleanup_ms = 0.0
    status = "FAIL"
    error: str | None = None
    try:
        launch_start = time.perf_counter_ns()
        backend.start()
        launch_ms = (time.perf_counter_ns() - launch_start) / 1_000_000

        search_box = css("input[name='search_query']")
        run_plan(backend, "01_open_youtube", [
            op("navigate-youtube", HOME, Action(type=ActionType.NAVIGATE), [
                Expectation(type=ExpectationType.URL, url_value="youtube.com", url_match=UrlMatchMode.CONTAINS)
            ], 45_000),
            op("wait-youtube-ready", HOME, Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(type=WaitConditionType.LOAD_STATE, load_state=LoadState.DOMCONTENTLOADED),
                wait_timeout_ms=30_000,
            )),
        ])

        consent = visible_first(backend, [
            ("accept_all_button", "button[aria-label='Accept all']"),
            ("consent_accept", "form[action*='consent'] button:last-of-type"),
            ("agree_button", "button:has-text('I agree')"),
        ])
        if consent:
            _, consent_locator = consent
            current = backend.page.url
            run_plan(backend, "02_handle_consent", [
                op("click-consent", current, Action(type=ActionType.CLICK, locator=consent_locator), [
                    Expectation(type=ExpectationType.URL, url_value="youtube.com", url_match=UrlMatchMode.CONTAINS)
                ], timeout_ms=30_000),
                op("wait-after-consent", current, Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(type=WaitConditionType.ELEMENT_VISIBLE, locator=search_box),
                    wait_timeout_ms=30_000,
                )),
            ])

        current = backend.page.url
        inspect(backend, "search_box_ready", search_box)
        pointer(backend, "03_pointer_search", current, search_box)
        run_plan(backend, "04_search", [
            op("fill-search", current, Action(type=ActionType.FILL, locator=search_box, text=QUERY), [
                Expectation(type=ExpectationType.ATTRIBUTE, locator=search_box, attribute_name="value", attribute_value=QUERY)
            ]),
            op("submit-search", current, Action(type=ActionType.PRESS_KEY, locator=search_box, key="Enter"), [
                Expectation(type=ExpectationType.URL, url_value="search_query=", url_match=UrlMatchMode.CONTAINS)
            ], 45_000),
            op("wait-search-results", SEARCH_URL, Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(type=WaitConditionType.ELEMENT_VISIBLE, locator=css("ytd-video-renderer:first-of-type")),
                wait_timeout_ms=45_000,
            )),
        ])

        results_url = backend.page.url
        filters = css("yt-chip-cloud-chip-renderer:first-of-type")
        first_thumb = css("ytd-video-renderer:nth-of-type(1) a#thumbnail")
        second_thumb = css("ytd-video-renderer:nth-of-type(2) a#thumbnail")
        sidebar = css("ytd-guide-entry-renderer:first-of-type a")
        for name, locator in [
            ("filters", filters), ("first_thumbnail", first_thumb),
            ("second_thumbnail", second_thumb), ("sidebar", sidebar),
        ]:
            inspect(backend, name, locator)
            pointer(backend, f"pointer_{name}", results_url, locator)

        scroll_targets = [
            css("ytd-video-renderer:nth-of-type(4)"),
            css("ytd-video-renderer:nth-of-type(7)"),
            css("ytd-video-renderer:nth-of-type(10)"),
            css("ytd-video-renderer:nth-of-type(2)"),
        ]
        run_plan(backend, "05_scroll_results", [
            op(f"scroll-section-{index}", results_url, Action(type=ActionType.SCROLL_TO_TARGET, locator=target), [
                Expectation(type=ExpectationType.ELEMENT_IN_VIEWPORT, locator=target, in_viewport=True)
            ])
            for index, target in enumerate(scroll_targets, 1)
        ])

        run_plan(backend, "06_open_first_video", [
            op("click-first-video", results_url, Action(type=ActionType.CLICK, locator=first_thumb), [
                Expectation(type=ExpectationType.URL, url_value="/watch", url_match=UrlMatchMode.CONTAINS)
            ], 45_000),
        ])
        video1_url = backend.page.url
        run_plan(backend, "07_wait_first_playback", [
            op("wait-first-video-visible", video1_url, Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(type=WaitConditionType.ELEMENT_VISIBLE, locator=VIDEO),
                wait_timeout_ms=45_000,
            )),
            op("wait-first-playing", video1_url, Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(type=WaitConditionType.VIDEO_PLAYING, locator=VIDEO),
                wait_timeout_ms=45_000,
            )),
        ])
        controls = css(".ytp-play-button")
        inspect(backend, "first_player_controls", controls)
        pointer(backend, "pointer_first_player_controls", video1_url, controls)
        dwell(15.0, "first_video_playback")
        run_plan(backend, "08_pause_and_return", [
            op("pause-first-video", video1_url, Action(type=ActionType.CLICK, locator=controls), [
                Expectation(type=ExpectationType.URL, url_value=video1_url, url_match=UrlMatchMode.EXACT)
            ]),
            op("return-to-results", video1_url, Action(
                type=ActionType.PRESS_KEY, key="Alt+ArrowLeft", key_scope=KeyPressScope.ACTIVE_PAGE
            ), [
                Expectation(type=ExpectationType.URL, url_value="/results", url_match=UrlMatchMode.CONTAINS)
            ], 45_000),
            op("wait-returned-results", results_url, Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(type=WaitConditionType.ELEMENT_VISIBLE, locator=second_thumb),
                wait_timeout_ms=45_000,
            )),
        ])

        results_url2 = backend.page.url
        inspect(backend, "second_video_before_click", second_thumb)
        run_plan(backend, "09_open_second_video", [
            op("click-second-video", results_url2, Action(type=ActionType.CLICK, locator=second_thumb), [
                Expectation(type=ExpectationType.URL, url_value="/watch", url_match=UrlMatchMode.CONTAINS)
            ], 45_000),
        ])
        video2_url = backend.page.url
        run_plan(backend, "10_wait_second_playback", [
            op("wait-second-playing", video2_url, Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(type=WaitConditionType.VIDEO_PLAYING, locator=VIDEO),
                wait_timeout_ms=45_000,
            )),
        ])
        inspect(backend, "second_player_controls", controls)
        pointer(backend, "pointer_second_player_controls", video2_url, controls)
        dwell(15.0, "second_video_playback")
        run_plan(backend, "11_return_home", [
            op("navigate-home", HOME, Action(type=ActionType.NAVIGATE), [
                Expectation(type=ExpectationType.URL, url_value="youtube.com", url_match=UrlMatchMode.CONTAINS)
            ], 45_000),
            op("wait-home-ready", HOME, Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(type=WaitConditionType.ELEMENT_VISIBLE, locator=search_box),
                wait_timeout_ms=45_000,
            )),
        ])
        inspect(backend, "home_final", search_box)
        status = "PASS"
        return_code = 0
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        return_code = 1
    finally:
        cleanup_start = time.perf_counter_ns()
        try:
            backend.stop()
        except Exception as exc:
            cleanup_error = f"{type(exc).__name__}: {exc}"
            error = f"{error}; cleanup={cleanup_error}" if error else cleanup_error
            status = "FAIL"
            return_code = 1
        cleanup_ms = (time.perf_counter_ns() - cleanup_start) / 1_000_000
        time.sleep(1.0)
        after = snapshot_processes()
        (HERE / "processes_after.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
        before_pids = {item.get("ProcessId") for item in before}
        remaining = [item for item in after if item.get("ProcessId") not in before_pids]
        if remaining:
            status = "FAIL"
            return_code = 1
        total_ms = (time.perf_counter_ns() - benchmark_start) / 1_000_000

        steps = [step for receipt in receipts for step in receipt.get("steps", []) if step.get("attempted")]
        action_types: list[str] = []
        verification_latencies: list[float] = []
        screenshot_count = 0
        for step in steps:
            rec = step.get("receipt") or {}
            action = rec.get("action_type")
            if action:
                action_types.append(action)
            action_evidence = rec.get("action_evidence") or {}
            screenshot_count += len(action_evidence.get("screenshots") or [])
            completed = rec.get("action_completed_at_ms")
            verified = rec.get("verification_completed_at_ms")
            if completed is not None and verified is not None:
                verification_latencies.append(max(0.0, verified - completed))
        inspection_latencies = [item["latency_ms"] for item in inspections]
        metrics = {
            "status": status,
            "error": error,
            "production_code_modified": False,
            "fresh_benchmark": True,
            "query": QUERY,
            "total_execution_time_ms": total_ms,
            "browser_launch_time_ms": launch_ms,
            "cleanup_time_ms": cleanup_ms,
            "navigation_latency_ms": next(
                (item["wall_ms"] for item in timeline if item.get("plan_id") == "01_open_youtube"), None
            ),
            "search_latency_ms": next(
                (item["wall_ms"] for item in timeline if item.get("plan_id") == "04_search"), None
            ),
            "total_browser_actions": len(action_types),
            "action_counts": {kind: action_types.count(kind) for kind in sorted(set(action_types))},
            "pointer_operations": action_types.count("pointer_move"),
            "click_operations": action_types.count("click"),
            "scroll_operations": action_types.count("scroll_to_target"),
            "receipt_count": len(receipts),
            "screenshot_count": screenshot_count,
            "inspection_count": len(inspections),
            "average_verification_latency_ms": (
                sum(verification_latencies) / len(verification_latencies) if verification_latencies else None
            ),
            "average_inspection_latency_ms": (
                sum(inspection_latencies) / len(inspection_latencies) if inspection_latencies else None
            ),
            "remaining_owned_processes": remaining,
            "unexpected_waits": unexpected_waits,
            "timeline": timeline,
            "evidence_locations": {
                "root": str(HERE), "receipts": str(RECEIPTS),
                "inspections": str(INSPECTIONS), "screenshots": str(SCREENSHOTS),
            },
        }
        (HERE / "benchmark_report.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
