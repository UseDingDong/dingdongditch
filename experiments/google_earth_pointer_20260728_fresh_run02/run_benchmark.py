"""Fresh Google Earth POINTER_MOVE benchmark with dynamic-URL preconditions."""
from __future__ import annotations

import json
import time
from pathlib import Path

from dingdongditch import (
    Action, ActionType, BrowserChannel, BrowserConfig, BrowserEngine,
    BrowserProvider, ExecutionPlan, Expectation, ExpectationType, Locator,
    LocatorStrategy, NameMatchMode, Operation, PageCondition,
    PageConditionType, PagePrecondition, PointerMoveRequest, PointerOrigin,
    ScreenshotConfig, ScreenshotPolicy, WaitCondition, WaitConditionType,
    execute_plan, inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import UrlMatchMode

ROOT = Path(__file__).resolve().parent
RECEIPTS, SCREENSHOTS = ROOT / "receipts", ROOT / "screenshots"
INSPECTIONS, LOGS = ROOT / "inspections", ROOT / "logs"
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS):
    directory.mkdir(parents=True, exist_ok=False)

EARTH_URL = "https://earth.google.com/web/"
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
SEARCH = Locator(
    strategy=LocatorStrategy.ROLE_NAME, role="button", name="Search",
    name_match=NameMatchMode.EXACT,
)
OTHER_CONTROLS = (
    ("Voyager", Locator(
        strategy=LocatorStrategy.ROLE_NAME, role="button", name="Voyager",
        name_match=NameMatchMode.EXACT,
    )),
    ("Projects", Locator(
        strategy=LocatorStrategy.ROLE_NAME, role="button", name="Projects",
        name_match=NameMatchMode.EXACT,
    )),
    ("Map Style", Locator(
        strategy=LocatorStrategy.ROLE_NAME, role="button", name="Map Style",
        name_match=NameMatchMode.EXACT,
    )),
    ("Measure", Locator(
        strategy=LocatorStrategy.ROLE_NAME, role="button", name="Measure",
        name_match=NameMatchMode.EXACT,
    )),
)
EARTH_PRECONDITION = PagePrecondition(conditions=(
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
receipt_number = 0
inspection_number = 0


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **details: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **details})
    write(LOGS / "run_history.json", events)


def url_expectation() -> list[Expectation]:
    return [Expectation(
        type=ExpectationType.URL,
        url_value="earth.google.com/web",
        url_match=UrlMatchMode.CONTAINS,
    )]


def execute(
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
    write(artifact, result.to_dict())
    log(
        "plan", plan_id=plan_id, verdict=result.plan_verdict.value,
        completion=result.completion_status.value, receipt=str(artifact),
    )
    return result


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict:
    global inspection_number
    inspection_number += 1
    result = inspect_target(backend, locator)
    artifact = INSPECTIONS / f"{inspection_number:03d}_{label}.json"
    write(artifact, result)
    log(
        "inspection", label=label, match_count=result.get("match_count"),
        visible=result.get("visible"), artifact=str(artifact),
    )
    return result


def pointer_op(
    operation_id: str,
    request: PointerMoveRequest,
    locator: Locator | None,
) -> Operation:
    return Operation(
        operation_id=operation_id,
        url=EARTH_URL,
        action=Action(
            type=ActionType.POINTER_MOVE,
            locator=locator,
            pointer_request=request,
        ),
        expectations=url_expectation(),
        page_precondition=EARTH_PRECONDITION,
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
                operation_id="navigate-earth", url=EARTH_URL,
                action=Action(type=ActionType.NAVIGATE),
                expectations=url_expectation(),
            ),
            ScreenshotPolicy.AFTER_SUCCESS,
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("navigation was not VERIFIED")

        ready = execute(
            backend, "wait_for_ready_interface",
            Operation(
                operation_id="wait-search-visible", url=EARTH_URL,
                timeout_ms=45_000,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.ELEMENT_VISIBLE, locator=SEARCH
                    ),
                    wait_timeout_ms=40_000,
                ),
                expectations=url_expectation(),
                page_precondition=EARTH_PRECONDITION,
            ),
            ScreenshotPolicy.AFTER_SUCCESS,
        )
        if ready.plan_verdict.value != "VERIFIED":
            raise RuntimeError("main interface was not visibly ready")

        search_state = inspect(backend, "search_button", SEARCH)
        if search_state.get("match_count") != 1 or search_state.get("visible") is not True:
            raise RuntimeError("Search was not uniquely visible")
        secondary_label = None
        secondary_locator = None
        for label, locator in OTHER_CONTROLS:
            state = inspect(backend, label.lower().replace(" ", "_"), locator)
            if state.get("match_count") == 1 and state.get("visible") is True:
                secondary_label, secondary_locator = label, locator
                break
        if secondary_locator is None:
            raise RuntimeError("second visible control was not found")

        moves = (
            ("viewport_center", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=640, y=360, steps=12
            ), None),
            ("search_button", PointerMoveRequest(
                PointerOrigin.ELEMENT_CENTER, steps=10
            ), SEARCH),
            (secondary_label.lower().replace(" ", "_"), PointerMoveRequest(
                PointerOrigin.ELEMENT_CENTER, steps=9
            ), secondary_locator),
            ("open_globe", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=840, y=330, steps=14
            ), None),
            ("upper_region", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=740, y=150, steps=11
            ), None),
            ("right_region", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=1080, y=300, steps=15
            ), None),
            ("lower_region", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=760, y=600, steps=13
            ), None),
            ("left_region", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=340, y=400, steps=16
            ), None),
        )
        pointer_results = []
        for index, (label, request, locator) in enumerate(moves, 1):
            receipt = execute(
                backend, f"pointer_{index:02d}_{label}",
                pointer_op(f"move-{index:02d}-{label}", request, locator),
                ScreenshotPolicy.ALWAYS,
            )
            step = receipt.steps[0].receipt
            evidence = step.action_evidence or {}
            required = {
                "requested", "resolved_position", "viewport", "previous_position",
                "final_position", "position_verification",
            }
            if receipt.plan_verdict.value != "VERIFIED":
                raise RuntimeError(f"{label} pointer plan was not VERIFIED")
            if not required.issubset(evidence):
                raise RuntimeError(f"{label} pointer evidence was incomplete")
            if evidence["position_verification"].get("verified") is not True:
                raise RuntimeError(f"{label} position was not verified")
            pointer_results.append({
                key: evidence[key] for key in (
                    "requested", "resolved_position", "viewport",
                    "previous_position", "final_position", "position_verification"
                )
            } | {"label": label})

        screenshot_paths = sorted(str(item) for item in SCREENSHOTS.glob("*.png"))
        write(ROOT / "run_result.json", {
            "verdict": "PASS",
            "google_earth_url": EARTH_URL,
            "interface_ready": True,
            "interface_ready_evidence": (
                f"unique visible Search and {secondary_label} controls"
            ),
            "successful_pointer_moves": len(pointer_results),
            "pointer_targets": [item["label"] for item in pointer_results],
            "pointer_results": pointer_results,
            "screenshot_count": len(screenshot_paths),
            "screenshots": screenshot_paths,
        })
        status = "completed"
        return 0
    except Exception as exc:
        write(ROOT / "run_result.json", {
            "verdict": "FAIL", "google_earth_url": EARTH_URL,
            "error": f"{type(exc).__name__}: {exc}",
        })
        log("benchmark_failed", error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        before = backend.browser_environment()
        backend.stop()
        after = backend.browser_environment()
        write(ROOT / "terminal_browser.json", {
            "status": status, "before_stop": before, "after_stop": after
        })
        log("browser_stopped", status=status, cleanup_errors=after["cleanup_errors"])


if __name__ == "__main__":
    raise SystemExit(main())
