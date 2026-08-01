"""Single-video YouTube playback failure diagnostic."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

from dingdongditch import (
    Action, ActionType, BrowserConfig, BrowserProfile, ConstraintType,
    ExecutionPlan, Expectation, ExpectationType, Locator, LocatorStrategy,
    Operation, ScreenshotConfig, ScreenshotPolicy, TargetConstraint,
    WaitCondition, WaitConditionType, execute_plan, inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import UrlMatchMode

ROOT = Path(__file__).resolve().parent / "attempt-6"
RECEIPTS, INSPECTIONS, SCREENSHOTS = (
    ROOT / "receipts", ROOT / "inspections", ROOT / "screenshots"
)
for directory in (RECEIPTS, INSPECTIONS, SCREENSHOTS):
    directory.mkdir(parents=True, exist_ok=True)

HOME = "https://www.youtube.com/"
QUERY = "Somalia drone footage"
SEARCH_URL = f"https://www.youtube.com/results?search_query={quote_plus(QUERY)}"
LONG_SEARCH_URL = SEARCH_URL + "&sp=EgIYAg%253D%253D"
CONFIG = BrowserConfig(headless=False, profile=BrowserProfile.DINGDONG)
VISIBLE = (TargetConstraint(type=ConstraintType.VISIBLE, visible=True),)
SEARCH = Locator(strategy=LocatorStrategy.CSS, value="input[name='search_query']")
LONG_RESULT = Locator(
    strategy=LocatorStrategy.CSS,
    value="ytd-video-renderer:nth-of-type(4) a#thumbnail",
    constraints=VISIBLE,
)
LONG_RESULT_CARD = Locator(
    strategy=LocatorStrategy.CSS,
    value="ytd-video-renderer:nth-of-type(4)",
    constraints=VISIBLE,
)
LONG_RESULT_DURATION = Locator(
    strategy=LocatorStrategy.CSS,
    value=(
        "ytd-video-renderer:nth-of-type(4) "
        "ytd-thumbnail-overlay-time-status-renderer"
    ),
    constraints=VISIBLE,
)
FIRST_RESULT = Locator(
    strategy=LocatorStrategy.CSS,
    value="ytd-video-renderer:first-of-type a#thumbnail",
    constraints=VISIBLE,
)
VIDEO = Locator(
    strategy=LocatorStrategy.CSS, value="video.html5-main-video",
    constraints=VISIBLE,
)
PLAYER_ERROR = Locator(
    strategy=LocatorStrategy.CSS, value=".ytp-error-content-wrap",
    constraints=VISIBLE,
)

receipts: list[dict[str, Any]] = []
inspections: list[dict[str, Any]] = []
verification_latencies: list[float] = []
inspection_latencies: list[float] = []
console_errors: list[dict[str, Any]] = []
failed_requests: list[dict[str, Any]] = []
media_http_failures: list[dict[str, Any]] = []


def process_pids() -> set[tuple[str, int]]:
    text = subprocess.run(
        ["tasklist"], capture_output=True, text=True, check=False
    ).stdout
    result = set()
    for line in text.splitlines():
        match = re.match(r"(chrome|node|python|playwright)\.exe\s+(\d+)", line, re.I)
        if match:
            result.add((match.group(1).lower(), int(match.group(2))))
    return result


def operation(
    operation_id: str, url: str, action: Action,
    expectations: list[Expectation] | None = None, timeout_ms: int = 30_000,
) -> Operation:
    return Operation(
        operation_id=operation_id, url=url, action=action,
        expectations=expectations or [], timeout_ms=timeout_ms,
        locate_retry_ms=5_000,
    )


def run_plan(
    backend: PlaywrightBackend, plan_id: str, operations: list[Operation],
    *, require_verified: bool = True,
):
    receipt = execute_plan(
        ExecutionPlan(
            plan_id=plan_id, operations=operations, browser_config=CONFIG,
            initial_plan_timeout_ms=60_000,
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS, max_per_operation=1,
                max_per_plan=max(1, len(operations)),
                artifact_root=str(SCREENSHOTS),
            ),
        ),
        backend=backend,
    )
    data = receipt.to_dict()
    receipts.append(data)
    (RECEIPTS / f"{len(receipts):03d}_{plan_id}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    for step in receipt.steps:
        item = step.receipt
        if (
            item is not None
            and item.action_completed_at_ms is not None
            and item.verification_completed_at_ms is not None
        ):
            verification_latencies.append(
                item.verification_completed_at_ms - item.action_completed_at_ms
            )
    if require_verified and receipt.plan_verdict.value != "VERIFIED":
        raise RuntimeError(f"{plan_id}: {receipt.plan_verdict.value}")
    return receipt


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict[str, Any]:
    started = time.perf_counter()
    data = inspect_target(backend, locator)
    latency = (time.perf_counter() - started) * 1000
    inspection_latencies.append(latency)
    record = {"label": label, "latency_ms": latency, "data": data}
    inspections.append(record)
    (INSPECTIONS / f"{len(inspections):03d}_{label}.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    return data


def media_related(url: str) -> bool:
    lower = url.lower()
    return any(
        token in lower for token in
        ("googlevideo.com", "videoplayback", "youtubei/v1/player", "player")
    )


def main() -> int:
    before = process_pids()
    backend = PlaywrightBackend(CONFIG)
    total_started = time.perf_counter()
    launch_seconds = cleanup_seconds = 0.0
    outcome = "FAIL"
    cause = error_text = current_url = video_id = None
    media_state: dict[str, Any] = {}
    uninterrupted_seconds = 0.0
    redirects: list[dict[str, Any]] = []
    try:
        launch_started = time.perf_counter()
        backend.start()
        launch_seconds = time.perf_counter() - launch_started

        def on_console(message: Any) -> None:
            if message.type == "error":
                console_errors.append(
                    {"type": message.type, "text": message.text}
                )

        def on_request_failed(request: Any) -> None:
            if media_related(request.url):
                failed_requests.append(
                    {
                        "method": request.method, "url": request.url,
                        "failure": request.failure,
                    }
                )

        def on_response(response: Any) -> None:
            if response.status >= 400 and media_related(response.url):
                media_http_failures.append(
                    {"status": response.status, "url": response.url}
                )

        backend.page.on("console", on_console)
        backend.page.on("requestfailed", on_request_failed)
        backend.page.on("response", on_response)

        run_plan(
            backend, "open_youtube",
            [
                operation(
                    "navigate-youtube", HOME, Action(type=ActionType.NAVIGATE),
                    [Expectation(
                        type=ExpectationType.URL, url_value="youtube.com",
                        url_match=UrlMatchMode.CONTAINS,
                    )],
                    45_000,
                ),
                operation(
                    "wait-search", HOME,
                    Action(
                        type=ActionType.WAIT_FOR,
                        wait_condition=WaitCondition(
                            type=WaitConditionType.ELEMENT_VISIBLE, locator=SEARCH
                        ),
                        wait_timeout_ms=30_000,
                    ),
                ),
            ],
        )
        run_plan(
            backend, "search",
            [
                operation(
                    "fill-search", HOME,
                    Action(type=ActionType.FILL, locator=SEARCH, text=QUERY),
                    [Expectation(
                        type=ExpectationType.ATTRIBUTE, locator=SEARCH,
                        attribute_name="value", attribute_value=QUERY,
                    )],
                ),
                operation(
                    "submit-search", HOME,
                    Action(type=ActionType.PRESS_KEY, locator=SEARCH, key="Enter"),
                    [Expectation(
                        type=ExpectationType.URL, url_value="search_query=",
                        url_match=UrlMatchMode.CONTAINS,
                    )],
                    45_000,
                ),
                operation(
                    "wait-long-result", SEARCH_URL,
                    Action(
                        type=ActionType.WAIT_FOR,
                        wait_condition=WaitCondition(
                            type=WaitConditionType.ELEMENT_VISIBLE,
                            locator=FIRST_RESULT,
                        ),
                        wait_timeout_ms=30_000,
                    ),
                ),
            ],
        )
        run_plan(
            backend, "filter_long_videos",
            [
                operation(
                    "open-over-20-minute-results", LONG_SEARCH_URL,
                    Action(type=ActionType.NAVIGATE),
                    [Expectation(
                        type=ExpectationType.URL, url_value="search_query=",
                        url_match=UrlMatchMode.CONTAINS,
                    )],
                    45_000,
                ),
                operation(
                    "wait-filtered-result", LONG_SEARCH_URL,
                    Action(
                        type=ActionType.WAIT_FOR,
                        wait_condition=WaitCondition(
                            type=WaitConditionType.ELEMENT_VISIBLE,
                            locator=FIRST_RESULT,
                        ),
                        wait_timeout_ms=30_000,
                    ),
                ),
            ],
        )
        selected_result = None
        selected_card = None
        selected_duration = None
        for index in range(1, 13):
            duration_locator = Locator(
                strategy=LocatorStrategy.CSS,
                value=(
                    f"ytd-video-renderer:nth-of-type({index}) "
                    "ytd-thumbnail-overlay-time-status-renderer"
                ),
            )
            duration_state = inspect(
                backend, f"candidate_{index:02d}_duration", duration_locator
            )
            text = str(duration_state.get("text", "")).strip()
            parts = text.split(":")
            try:
                seconds = (
                    int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    if len(parts) == 3
                    else int(parts[0]) * 60 + int(parts[1])
                )
            except (ValueError, IndexError):
                continue
            if seconds > 600:
                selected_result = Locator(
                    strategy=LocatorStrategy.CSS,
                    value=f"ytd-video-renderer:nth-of-type({index}) a#thumbnail",
                )
                selected_card = Locator(
                    strategy=LocatorStrategy.CSS,
                    value=f"ytd-video-renderer:nth-of-type({index})",
                )
                selected_duration = text
                break
        if selected_result is None or selected_card is None:
            raise RuntimeError("no displayed result longer than ten minutes")

        run_plan(
            backend, "reveal_selected_long_result",
            [operation(
                "scroll-selected-long-result", LONG_SEARCH_URL,
                Action(
                    type=ActionType.SCROLL_TO_TARGET,
                    locator=selected_card,
                ),
                [Expectation(
                    type=ExpectationType.ELEMENT_IN_VIEWPORT,
                    locator=selected_card, in_viewport=True,
                )],
            )],
        )
        inspect(backend, "selected_long_result", selected_card)

        run_plan(
            backend, "open_long_video",
            [operation(
                "click-long-video", LONG_SEARCH_URL,
                Action(type=ActionType.CLICK, locator=selected_result),
                [Expectation(
                    type=ExpectationType.URL, url_value="/watch",
                    url_match=UrlMatchMode.CONTAINS,
                )],
                45_000,
            )],
        )
        video_page = inspect(backend, "opened_video", VIDEO)
        current_url = str(video_page["page"]["url"])
        video_id = parse_qs(urlparse(current_url).query).get("v", [None])[0]
        run_plan(
            backend, "confirm_playback_started",
            [operation(
                "wait-video-playing", current_url,
                Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.VIDEO_PLAYING, locator=VIDEO
                    ),
                    wait_timeout_ms=45_000,
                ),
                timeout_ms=50_000,
            )],
        )

        observed_started = time.perf_counter()
        for checkpoint in range(1, 25):
            time.sleep(5)
            receipt = run_plan(
                backend, f"playback_checkpoint_{checkpoint:02d}",
                [operation(
                    f"verify-playing-{checkpoint:02d}", current_url,
                    Action(
                        type=ActionType.WAIT_FOR,
                        wait_condition=WaitCondition(
                            type=WaitConditionType.VIDEO_PLAYING, locator=VIDEO
                        ),
                        wait_timeout_ms=1_000,
                    ),
                    timeout_ms=5_000,
                )],
                require_verified=False,
            )
            if receipt.plan_verdict.value != "VERIFIED":
                uninterrupted_seconds = time.perf_counter() - observed_started
                step_receipt = receipt.steps[0].receipt
                media_state = (
                    (step_receipt.action_evidence or {})
                    if step_receipt is not None else {}
                )
                error = inspect(backend, "first_player_error", PLAYER_ERROR)
                error_text = str(error.get("text", ""))
                cause = (
                    "Video unavailable"
                    if "video unavailable" in error_text.lower()
                    else "player stopped before two uninterrupted minutes"
                )
                break
        else:
            uninterrupted_seconds = time.perf_counter() - observed_started
            outcome = "PASS"
            cause = "two minutes of uninterrupted playback completed"

    except Exception as exc:
        cause = cause or f"{type(exc).__name__}: {exc}"
    finally:
        redirects = [
            {"status": item.status, "url": item.url}
            for item in backend._network
            if item.status is not None and 300 <= item.status < 400
        ]
        cleanup_started = time.perf_counter()
        backend.stop()
        cleanup_seconds = time.perf_counter() - cleanup_started

    remaining = sorted(process_pids() - before)
    if remaining:
        outcome = "FAIL"
        cause = f"{cause}; owned processes remain"
    report = {
        "status": outcome,
        "first_verified_cause": cause,
        "visible_player_error_text": error_text,
        "current_url": current_url,
        "video_id": video_id,
        "uninterrupted_playback_seconds": uninterrupted_seconds,
        "video_state_evidence": media_state,
        "console_errors": console_errors,
        "failed_media_requests": failed_requests,
        "media_http_failures": media_http_failures,
        "redirects": redirects,
        "browser_profile": CONFIG.profile.value,
        "total_execution_seconds": time.perf_counter() - total_started,
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
        "inspection_count": len(inspections),
        "screenshot_count": len(list(SCREENSHOTS.glob("*.png"))),
        "remaining_owned_processes": remaining,
    }
    (ROOT / "diagnostic_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
