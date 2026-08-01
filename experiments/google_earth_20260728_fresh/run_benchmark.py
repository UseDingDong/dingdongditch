"""Fresh Google Earth capability benchmark through DingDongDitch only."""
from __future__ import annotations

import json
import time
from pathlib import Path

from dingdongditch import (
    Action,
    ActionType,
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
    ExecutionPlan,
    Expectation,
    ExpectationType,
    Locator,
    LocatorStrategy,
    Operation,
    ScreenshotConfig,
    ScreenshotPolicy,
    execute_plan,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend

ROOT = Path(__file__).resolve().parent
RECEIPTS = ROOT / "receipts"
SCREENSHOTS = ROOT / "screenshots"
INSPECTIONS = ROOT / "inspections"
LOGS = ROOT / "logs"
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS):
    directory.mkdir(parents=True, exist_ok=False)

EARTH_URL = "https://earth.google.com/web/"
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
events: list[dict[str, object]] = []


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **detail: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **detail})
    save(LOGS / "run_history.json", events)


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    status = "failed"
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        receipt = execute_plan(
            ExecutionPlan(
                plan_id="navigate_google_earth",
                operations=[
                    Operation(
                        operation_id="navigate-earth-web",
                        url=EARTH_URL,
                        action=Action(type=ActionType.NAVIGATE),
                        expectations=[
                            Expectation(type=ExpectationType.URL, url_value=EARTH_URL)
                        ],
                    )
                ],
                browser_config=CONFIG,
                screenshot_config=ScreenshotConfig(
                    policy=ScreenshotPolicy.AFTER_SUCCESS,
                    artifact_root=str(SCREENSHOTS),
                ),
                initial_plan_timeout_ms=60_000,
                max_plan_timeout_ms=60_000,
            ),
            backend=backend,
        )
        receipt_path = RECEIPTS / "01_navigate_google_earth.json"
        save(receipt_path, receipt.to_dict())
        log(
            "plan",
            plan_id="navigate_google_earth",
            verdict=receipt.plan_verdict.value,
            completion=receipt.completion_status.value,
            receipt=str(receipt_path),
        )

        body = inspect_target(
            backend, Locator(strategy=LocatorStrategy.CSS, value="body")
        )
        inspection_path = INSPECTIONS / "001_google_earth_body.json"
        save(inspection_path, body)
        log(
            "inspection",
            label="google_earth_body",
            match_count=body.get("match_count"),
            text=body.get("text"),
            artifact=str(inspection_path),
        )

        available_actions = tuple(item.value for item in ActionType)
        drag_supported = any(
            name in available_actions
            for name in ("drag", "pointer_drag", "mouse_drag")
        )
        if drag_supported:
            raise RuntimeError("unexpected drag capability; harness requires review")

        save(
            ROOT / "run_result.json",
            {
                "verdict": "FAIL",
                "google_earth_url": EARTH_URL,
                "navigation_verdict": receipt.plan_verdict.value,
                "navigation_completion": receipt.completion_status.value,
                "interface_inspection_text": body.get("text"),
                "verified_rotation_drags": 0,
                "total_rotation_duration_seconds": 0,
                "distinct_globe_positions_evidenced": 0,
                "search_query_used": None,
                "final_verified_location": None,
                "failure_kind": "UNSUPPORTED_TYPED_ACTION",
                "failure": (
                    "DingDongDitch has no typed pointer drag action; the required "
                    "eight genuine pointer drags cannot be expressed as ExecutionPlans."
                ),
                "available_action_types": list(available_actions),
            },
        )
        log(
            "benchmark_stopped_at_capability_boundary",
            failure_kind="UNSUPPORTED_TYPED_ACTION",
            verified_rotation_drags=0,
        )
        return 1
    except Exception as exc:
        save(
            ROOT / "run_result.json",
            {
                "verdict": "FAIL",
                "google_earth_url": EARTH_URL,
                "failure_kind": "EXECUTION_ERROR",
                "failure": f"{type(exc).__name__}: {exc}",
            },
        )
        log("benchmark_execution_error", error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        before = backend.browser_environment()
        backend.stop()
        after = backend.browser_environment()
        save(
            ROOT / "terminal_browser.json",
            {"status": status, "before_stop": before, "after_stop": after},
        )
        log("browser_stopped", cleanup_errors=after["cleanup_errors"])


if __name__ == "__main__":
    raise SystemExit(main())
