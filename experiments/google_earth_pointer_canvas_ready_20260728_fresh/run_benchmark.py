"""Fresh Google Earth canvas-readiness and POINTER_MOVE benchmark."""
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
CANVAS = Locator(strategy=LocatorStrategy.CSS, value="canvas")
PRECONDITION = PagePrecondition(conditions=(
    PageCondition(
        condition_id="earth-origin",
        type=PageConditionType.ORIGIN_EQUALS,
        origin_value="https://earth.google.com",
    ),
    PageCondition(
        condition_id="earth-path",
        type=PageConditionType.PATH_STARTS_WITH,
        path_value="/web",
    ),
))
events: list[dict[str, object]] = []
readiness: list[dict[str, object]] = []
receipt_number = 0
inspection_number = 0


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **details: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **details})
    save(LOGS / "run_history.json", events)


def url_expectation() -> list[Expectation]:
    return [Expectation(
        type=ExpectationType.URL,
        url_value="earth.google.com/web",
        url_match=UrlMatchMode.CONTAINS,
    )]


def run(
    backend: PlaywrightBackend,
    plan_id: str,
    operation: Operation,
    screenshots: ScreenshotPolicy,
):
    global receipt_number
    receipt_number += 1
    result = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=[operation],
            browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=screenshots, artifact_root=str(SCREENSHOTS)
            ),
            initial_plan_timeout_ms=60_000,
            max_plan_timeout_ms=60_000,
        ),
        backend=backend,
    )
    artifact = RECEIPTS / f"{receipt_number:02d}_{plan_id}.json"
    save(artifact, result.to_dict())
    log(
        "plan", plan_id=plan_id, verdict=result.plan_verdict.value,
        completion=result.completion_status.value, receipt=str(artifact),
    )
    return result


def inspect_canvas(backend: PlaywrightBackend, label: str) -> dict:
    global inspection_number
    inspection_number += 1
    result = inspect_target(backend, CANVAS)
    artifact = INSPECTIONS / f"{inspection_number:03d}_{label}.json"
    save(artifact, result)
    log(
        "inspection", label=label, match_count=result.get("match_count"),
        visible=result.get("visible"), artifact=str(artifact),
    )
    return result


def newest_screenshot() -> Path:
    return max(SCREENSHOTS.glob("*.png"), key=lambda item: item.stat().st_mtime_ns)


def frame_metrics(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        top = image.crop((0, 0, width, min(82, height)))
        pixels = list(top.getdata())
        bright = sum(
            1 for red, green, blue in pixels
            if (red * 299 + green * 587 + blue * 114) / 1000 >= 180
        )
        return {
            "width": width,
            "height": height,
            "top_bright_ratio": bright / len(pixels),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "path": str(path),
        }


def mean_image_difference(left: Path, right: Path) -> float:
    with Image.open(left) as left_source, Image.open(right) as right_source:
        a = left_source.convert("RGB")
        b = right_source.convert("RGB")
        crop_box = (0, 82, a.width, a.height)
        difference = ImageChops.difference(a.crop(crop_box), b.crop(crop_box))
        return sum(ImageStat.Stat(difference).mean) / 3


def observation_operation(index: int) -> Operation:
    return Operation(
        operation_id=f"observe-render-{index:02d}",
        url=URL,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_condition=WaitCondition(
                type=WaitConditionType.URL_MATCHES,
                url_value="earth.google.com/web",
                url_match=UrlMatchMode.CONTAINS,
            ),
            wait_timeout_ms=1_000,
        ),
        expectations=url_expectation(),
        page_precondition=PRECONDITION,
    )


def pointer_operation(
    index: int,
    label: str,
    request: PointerMoveRequest,
    locator: Locator | None = None,
) -> Operation:
    return Operation(
        operation_id=f"pointer-{index:02d}-{label}",
        url=URL,
        action=Action(
            type=ActionType.POINTER_MOVE,
            locator=locator,
            pointer_request=request,
        ),
        expectations=url_expectation(),
        page_precondition=PRECONDITION,
    )


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    status = "failed"
    navigation_started = time.monotonic()
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        navigation = run(
            backend, "navigate_google_earth",
            Operation(
                operation_id="navigate-earth", url=URL,
                action=Action(type=ActionType.NAVIGATE),
                expectations=url_expectation(),
            ),
            ScreenshotPolicy.ALWAYS,
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("navigation was not VERIFIED")

        ready_at_ms = None
        previous_loaded = None
        for index in range(1, 16):
            target = navigation_started + index * 2
            remaining = target - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            observation = run(
                backend, f"readiness_{index:02d}",
                observation_operation(index), ScreenshotPolicy.ALWAYS,
            )
            if observation.plan_verdict.value != "VERIFIED":
                raise RuntimeError("readiness observation plan was not VERIFIED")
            canvas = inspect_canvas(backend, f"canvas_{index:02d}")
            screenshot = newest_screenshot()
            metrics = frame_metrics(screenshot)
            item: dict[str, object] = {
                "index": index,
                "elapsed_ms": round((time.monotonic() - navigation_started) * 1000),
                "canvas_match_count": canvas.get("match_count"),
                "canvas_visible": canvas.get("visible"),
                **metrics,
            }
            loaded_visual = (
                canvas.get("match_count") == 1
                and canvas.get("visible") is True
                and float(metrics["top_bright_ratio"]) >= 0.55
            )
            if loaded_visual and previous_loaded is not None:
                elapsed_gap = int(item["elapsed_ms"]) - int(
                    previous_loaded["elapsed_ms"]
                )
                bright_delta = abs(
                    float(item["top_bright_ratio"])
                    - float(previous_loaded["top_bright_ratio"])
                )
                frame_delta = mean_image_difference(
                    Path(str(previous_loaded["path"])), screenshot
                )
                item.update({
                    "stable_loaded_gap_ms": elapsed_gap,
                    "toolbar_bright_ratio_delta": bright_delta,
                    "rendered_region_mean_pixel_delta": frame_delta,
                })
                if (
                    elapsed_gap >= 2_000
                    and bright_delta <= 0.08
                    and frame_delta > 0.1
                ):
                    ready_at_ms = int(item["elapsed_ms"])
                    item["ready"] = True
                    readiness.append(item)
                    save(LOGS / "readiness_observations.json", readiness)
                    break
            item["ready"] = False
            readiness.append(item)
            save(LOGS / "readiness_observations.json", readiness)
            previous_loaded = item if loaded_visual else None

        if ready_at_ms is None:
            raise RuntimeError("canvas/WebGL readiness was not established in 30 seconds")

        positions = (
            ("canvas_center", PointerMoveRequest(
                PointerOrigin.ELEMENT_CENTER, steps=12
            ), CANVAS),
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
        pointer_results = []
        for index, (label, request, locator) in enumerate(positions, 1):
            receipt = run(
                backend, f"move_{index:02d}_{label}",
                pointer_operation(index, label, request, locator),
                ScreenshotPolicy.ALWAYS,
            )
            step = receipt.steps[0].receipt
            evidence = step.action_evidence or {}
            required = {
                "requested", "resolved_position", "viewport", "previous_position",
                "final_position", "steps", "position_verification", "screenshots",
            }
            if receipt.plan_verdict.value != "VERIFIED":
                raise RuntimeError(f"pointer move {label} was not VERIFIED")
            if not required.issubset(evidence):
                raise RuntimeError(f"pointer move {label} evidence was incomplete")
            if evidence["position_verification"].get("verified") is not True:
                raise RuntimeError(f"pointer move {label} was not position-verified")
            pointer_results.append({
                "label": label,
                "requested": evidence["requested"],
                "resolved_position": evidence["resolved_position"],
                "previous_position": evidence["previous_position"],
                "final_position": evidence["final_position"],
                "steps": evidence["steps"],
                "viewport": evidence["viewport"],
                "verification": evidence["position_verification"],
                "bounding_box": evidence.get("bounding_box"),
                "screenshots": evidence["screenshots"],
            })

        distinct = {
            (item["final_position"]["x"], item["final_position"]["y"])
            for item in pointer_results
        }
        screenshots = sorted(str(item) for item in SCREENSHOTS.glob("*.png"))
        canvas_box = pointer_results[0]["bounding_box"]
        save(ROOT / "run_result.json", {
            "verdict": "PASS",
            "google_earth_url": URL,
            "navigation_verdict": navigation.plan_verdict.value,
            "rendered_ready_ms": ready_at_ms,
            "readiness_evidence": readiness[-1],
            "canvas_dimensions": (
                {"width": canvas_box["width"], "height": canvas_box["height"]}
                if canvas_box else None
            ),
            "rendering_evidence": {
                "rendered_region_mean_pixel_delta": readiness[-1].get(
                    "rendered_region_mean_pixel_delta"
                ),
                "frame_hash_progression": (
                    readiness[-1]["sha256"] != readiness[-2]["sha256"]
                ),
            },
            "successful_pointer_moves": len(pointer_results),
            "distinct_pointer_positions": len(distinct),
            "pointer_results": pointer_results,
            "screenshot_count": len(screenshots),
            "screenshots": screenshots,
        })
        status = "completed"
        return 0
    except Exception as exc:
        save(ROOT / "run_result.json", {
            "verdict": "FAIL", "google_earth_url": URL,
            "error": f"{type(exc).__name__}: {exc}",
            "readiness_observations": readiness,
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
