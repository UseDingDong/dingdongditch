"""Fresh Google Earth exact-render-canvas POINTER_MOVE benchmark."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from dingdongditch import (
    Action, ActionType, BrowserChannel, BrowserConfig, BrowserEngine,
    BrowserProvider, ExecutionPlan, Expectation, ExpectationType, Locator,
    LocatorStrategy, Operation, PageCondition, PageConditionType,
    PagePrecondition, PointerMoveRequest, PointerOrigin, ScreenshotConfig,
    ScreenshotPolicy, WaitCondition, WaitConditionType, execute_plan,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import UrlMatchMode

ROOT = Path(__file__).resolve().parent
RECEIPTS, SCREENSHOTS = ROOT / "receipts", ROOT / "screenshots"
INSPECTIONS, LOGS = ROOT / "inspections", ROOT / "logs"
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS):
    directory.mkdir(parents=True, exist_ok=False)

URL = "https://earth.google.com/web/"
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
EARTH_CANVAS = Locator(strategy=LocatorStrategy.CSS, value="canvas#earth-canvas")
PRECONDITION = PagePrecondition(conditions=(
    PageCondition(
        condition_id="earth-origin", type=PageConditionType.ORIGIN_EQUALS,
        origin_value="https://earth.google.com",
    ),
    PageCondition(
        condition_id="earth-path", type=PageConditionType.PATH_STARTS_WITH,
        path_value="/web",
    ),
))
events: list[dict[str, object]] = []
observations: list[dict[str, object]] = []
receipt_index = 0
inspection_index = 0


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **detail: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **detail})
    save(LOGS / "run_history.json", events)


def expectation() -> list[Expectation]:
    return [Expectation(
        type=ExpectationType.URL, url_value="earth.google.com/web",
        url_match=UrlMatchMode.CONTAINS,
    )]


def execute(
    backend: PlaywrightBackend,
    plan_id: str,
    operation: Operation,
):
    global receipt_index
    receipt_index += 1
    receipt = execute_plan(
        ExecutionPlan(
            plan_id=plan_id, operations=[operation], browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS, artifact_root=str(SCREENSHOTS)
            ),
            initial_plan_timeout_ms=60_000, max_plan_timeout_ms=60_000,
        ),
        backend=backend,
    )
    path = RECEIPTS / f"{receipt_index:02d}_{plan_id}.json"
    save(path, receipt.to_dict())
    log(
        "plan", plan_id=plan_id, verdict=receipt.plan_verdict.value,
        completion=receipt.completion_status.value, receipt=str(path),
    )
    return receipt


def inspect_canvas(backend: PlaywrightBackend, label: str) -> dict:
    global inspection_index
    inspection_index += 1
    state = inspect_target(backend, EARTH_CANVAS)
    path = INSPECTIONS / f"{inspection_index:03d}_{label}.json"
    save(path, state)
    log(
        "inspection", label=label, match_count=state.get("match_count"),
        visible=state.get("visible"), artifact=str(path),
    )
    return state


def latest_screenshot() -> Path:
    return max(SCREENSHOTS.glob("*.png"), key=lambda path: path.stat().st_mtime_ns)


def metrics(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        band = image.crop((0, 0, image.width, min(82, image.height)))
        pixels = list(band.getdata())
        bright = sum(
            1 for r, g, b in pixels
            if (r * 299 + g * 587 + b * 114) / 1000 >= 180
        )
        return {
            "screenshot": str(path),
            "screenshot_width": image.width,
            "screenshot_height": image.height,
            "top_toolbar_bright_ratio": bright / len(pixels),
            "screenshot_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


def rendered_difference(first: Path, second: Path) -> float:
    with Image.open(first) as one, Image.open(second) as two:
        left, right = one.convert("RGB"), two.convert("RGB")
        box = (0, 82, left.width, left.height)
        difference = ImageChops.difference(left.crop(box), right.crop(box))
        return sum(ImageStat.Stat(difference).mean) / 3


def observation(index: int) -> Operation:
    return Operation(
        operation_id=f"observe-{index:02d}", url=URL,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_condition=WaitCondition(
                type=WaitConditionType.URL_MATCHES,
                url_value="earth.google.com/web",
                url_match=UrlMatchMode.CONTAINS,
            ),
            wait_timeout_ms=1_000,
        ),
        expectations=expectation(), page_precondition=PRECONDITION,
    )


def pointer(
    index: int,
    label: str,
    request: PointerMoveRequest,
    locator: Locator | None,
) -> Operation:
    return Operation(
        operation_id=f"pointer-{index:02d}-{label}", url=URL,
        action=Action(
            type=ActionType.POINTER_MOVE, locator=locator,
            pointer_request=request,
        ),
        expectations=expectation(), page_precondition=PRECONDITION,
    )


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    status = "failed"
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        navigation = execute(
            backend, "navigate_google_earth",
            Operation(
                operation_id="navigate-earth", url=URL,
                action=Action(type=ActionType.NAVIGATE),
                expectations=expectation(),
            ),
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("navigation was not VERIFIED")

        readiness_started = time.monotonic()
        loaded_previous = None
        ready_ms = None
        for index in range(1, 16):
            remaining = readiness_started + index * 2 - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            receipt = execute(backend, f"readiness_{index:02d}", observation(index))
            if receipt.plan_verdict.value != "VERIFIED":
                raise RuntimeError("readiness observation was not VERIFIED")
            canvas = inspect_canvas(backend, f"earth_canvas_{index:02d}")
            frame = latest_screenshot()
            visual = metrics(frame)
            entry: dict[str, object] = {
                "index": index,
                "elapsed_since_navigation_ms": round(
                    (time.monotonic() - readiness_started) * 1000
                ),
                "canvas_match_count": canvas.get("match_count"),
                "canvas_visible": canvas.get("visible"),
                **visual,
            }
            loaded = (
                canvas.get("match_count") == 1
                and canvas.get("visible") is True
                and float(visual["top_toolbar_bright_ratio"]) >= 0.55
            )
            if loaded and loaded_previous is not None:
                gap = (
                    int(entry["elapsed_since_navigation_ms"])
                    - int(loaded_previous["elapsed_since_navigation_ms"])
                )
                toolbar_delta = abs(
                    float(entry["top_toolbar_bright_ratio"])
                    - float(loaded_previous["top_toolbar_bright_ratio"])
                )
                frame_delta = rendered_difference(
                    Path(str(loaded_previous["screenshot"])), frame
                )
                entry.update({
                    "stable_gap_ms": gap,
                    "toolbar_ratio_delta": toolbar_delta,
                    "rendered_mean_pixel_delta": frame_delta,
                })
                if gap >= 2_000 and toolbar_delta <= 0.08 and frame_delta > 0.1:
                    entry["ready"] = True
                    observations.append(entry)
                    ready_ms = int(entry["elapsed_since_navigation_ms"])
                    save(LOGS / "readiness_observations.json", observations)
                    break
            entry["ready"] = False
            observations.append(entry)
            save(LOGS / "readiness_observations.json", observations)
            loaded_previous = entry if loaded else None
        if ready_ms is None:
            raise RuntimeError("rendered readiness was not established within 30 seconds")

        declarations = (
            ("globe_center", PointerMoveRequest(
                PointerOrigin.ELEMENT_CENTER, steps=12
            ), EARTH_CANVAS),
            ("upper_left", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=220, y=140, steps=10
            ), None),
            ("upper_right", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=1060, y=140, steps=14
            ), None),
            ("lower_right", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=1060, y=590, steps=13
            ), None),
            ("lower_left", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=220, y=590, steps=15
            ), None),
            ("center_return", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=640, y=360, steps=12
            ), None),
            ("upper_middle", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=700, y=180, steps=11
            ), None),
            ("right_middle", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=1120, y=390, steps=16
            ), None),
            ("left_middle", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=360, y=420, steps=14
            ), None),
        )
        results = []
        for index, (label, request, locator) in enumerate(declarations, 1):
            receipt = execute(
                backend, f"move_{index:02d}_{label}",
                pointer(index, label, request, locator),
            )
            step = receipt.steps[0].receipt
            evidence = step.action_evidence or {}
            required = {
                "requested", "resolved_position", "previous_position",
                "final_position", "steps", "viewport",
                "position_verification", "screenshots",
            }
            if receipt.plan_verdict.value != "VERIFIED":
                raise RuntimeError(f"{label} pointer plan was not VERIFIED")
            if not required.issubset(evidence):
                raise RuntimeError(f"{label} pointer evidence was incomplete")
            if evidence["position_verification"].get("verified") is not True:
                raise RuntimeError(f"{label} pointer position was not verified")
            results.append({
                "label": label,
                "requested": evidence["requested"],
                "resolved_position": evidence["resolved_position"],
                "previous_position": evidence["previous_position"],
                "final_position": evidence["final_position"],
                "steps": evidence["steps"],
                "viewport": evidence["viewport"],
                "verification": evidence["position_verification"],
                "canvas_bounding_box": evidence.get("bounding_box"),
                "screenshots": evidence["screenshots"],
            })

        distinct = {
            (item["final_position"]["x"], item["final_position"]["y"])
            for item in results
        }
        canvas_box = results[0]["canvas_bounding_box"]
        screenshot_paths = sorted(str(path) for path in SCREENSHOTS.glob("*.png"))
        save(ROOT / "run_result.json", {
            "verdict": "PASS",
            "google_earth_url": URL,
            "navigation_verdict": navigation.plan_verdict.value,
            "time_from_navigation_to_readiness_ms": ready_ms,
            "readiness_evidence": observations[-1],
            "canvas_dimensions": {
                "width": canvas_box["width"], "height": canvas_box["height"]
            },
            "rendering_evidence": {
                "frame_hash_progressed": (
                    observations[-1]["screenshot_sha256"]
                    != observations[-2]["screenshot_sha256"]
                ),
                "rendered_mean_pixel_delta": observations[-1][
                    "rendered_mean_pixel_delta"
                ],
            },
            "successful_pointer_moves": len(results),
            "distinct_pointer_positions": len(distinct),
            "pointer_results": results,
            "screenshot_count": len(screenshot_paths),
            "screenshots": screenshot_paths,
            "cursor_capture_note": (
                "Playwright page screenshots do not include the OS cursor; "
                "pointer locations are authoritative in typed receipts."
            ),
        })
        status = "completed"
        return 0
    except Exception as exc:
        save(ROOT / "run_result.json", {
            "verdict": "FAIL", "google_earth_url": URL,
            "error": f"{type(exc).__name__}: {exc}",
            "readiness_observations": observations,
        })
        log("benchmark_failed", error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        before = backend.browser_environment()
        backend.stop()
        after = backend.browser_environment()
        save(ROOT / "terminal_browser.json", {
            "status": status, "before_stop": before, "after_stop": after
        })
        log("browser_stopped", status=status, cleanup_errors=after["cleanup_errors"])


if __name__ == "__main__":
    raise SystemExit(main())
