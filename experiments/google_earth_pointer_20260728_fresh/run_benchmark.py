"""Fresh Google Earth POINTER_MOVE production benchmark."""
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
    NameMatchMode,
    Operation,
    PointerMoveRequest,
    PointerOrigin,
    ScreenshotConfig,
    ScreenshotPolicy,
    WaitCondition,
    WaitConditionType,
    execute_plan,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import UrlMatchMode

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
SEARCH = Locator(
    strategy=LocatorStrategy.ROLE_NAME,
    role="button",
    name="Search",
    name_match=NameMatchMode.EXACT,
)
CONTROL_CANDIDATES = (
    ("Voyager", Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Voyager",
        name_match=NameMatchMode.EXACT,
    )),
    ("Projects", Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Projects",
        name_match=NameMatchMode.EXACT,
    )),
    ("Map Style", Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Map Style",
        name_match=NameMatchMode.EXACT,
    )),
    ("Measure", Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Measure",
        name_match=NameMatchMode.EXACT,
    )),
)
events: list[dict[str, object]] = []
receipt_index = 0
inspection_index = 0


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **detail: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **detail})
    save(LOGS / "run_history.json", events)


def run_plan(
    backend: PlaywrightBackend,
    plan_id: str,
    operations: list[Operation],
    screenshot_policy: ScreenshotPolicy,
):
    global receipt_index
    receipt_index += 1
    receipt = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=operations,
            browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=screenshot_policy,
                artifact_root=str(SCREENSHOTS),
            ),
            initial_plan_timeout_ms=60_000,
            max_plan_timeout_ms=60_000,
        ),
        backend=backend,
    )
    path = RECEIPTS / f"{receipt_index:02d}_{plan_id}.json"
    save(path, receipt.to_dict())
    log(
        "plan",
        plan_id=plan_id,
        verdict=receipt.plan_verdict.value,
        completion=receipt.completion_status.value,
        receipt=str(path),
    )
    return receipt


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict:
    global inspection_index
    inspection_index += 1
    result = inspect_target(backend, locator)
    path = INSPECTIONS / f"{inspection_index:03d}_{label}.json"
    save(path, result)
    log(
        "inspection",
        label=label,
        locator=locator.describe(),
        match_count=result.get("match_count"),
        visible=result.get("visible"),
        artifact=str(path),
    )
    return result


def earth_url_expectation() -> list[Expectation]:
    return [
        Expectation(
            type=ExpectationType.URL,
            url_value="earth.google.com/web",
            url_match=UrlMatchMode.CONTAINS,
        )
    ]


def pointer_operation(
    operation_id: str,
    request: PointerMoveRequest,
    locator: Locator | None = None,
) -> Operation:
    return Operation(
        operation_id=operation_id,
        url=EARTH_URL,
        action=Action(
            type=ActionType.POINTER_MOVE,
            locator=locator,
            pointer_request=request,
        ),
        expectations=earth_url_expectation(),
    )


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    status = "failed"
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        navigation = run_plan(
            backend,
            "navigate_google_earth",
            [
                Operation(
                    operation_id="navigate-earth",
                    url=EARTH_URL,
                    action=Action(type=ActionType.NAVIGATE),
                    expectations=earth_url_expectation(),
                )
            ],
            ScreenshotPolicy.AFTER_SUCCESS,
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Google Earth navigation was not VERIFIED")

        ready = run_plan(
            backend,
            "wait_for_google_earth_interface",
            [
                Operation(
                    operation_id="wait-search-visible",
                    url=EARTH_URL,
                    timeout_ms=45_000,
                    action=Action(
                        type=ActionType.WAIT_FOR,
                        wait_condition=WaitCondition(
                            type=WaitConditionType.ELEMENT_VISIBLE,
                            locator=SEARCH,
                        ),
                        wait_timeout_ms=40_000,
                    ),
                    expectations=earth_url_expectation(),
                )
            ],
            ScreenshotPolicy.AFTER_SUCCESS,
        )
        if ready.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Google Earth main interface did not become ready")
        search_state = inspect(backend, "visible_search_button", SEARCH)
        if (
            search_state.get("match_count") != 1
            or search_state.get("visible") is not True
        ):
            raise RuntimeError("visible Search control was not uniquely verified")

        other_label = None
        other_control = None
        for label, locator in CONTROL_CANDIDATES:
            state = inspect(backend, f"candidate_{label.lower().replace(' ', '_')}", locator)
            if state.get("match_count") == 1 and state.get("visible") is True:
                other_label = label
                other_control = locator
                break
        if other_control is None or other_label is None:
            raise RuntimeError("no second visible Google Earth control was verified")

        moves = [
            (
                "viewport_center",
                PointerMoveRequest(PointerOrigin.VIEWPORT, x=640, y=360, steps=12),
                None,
            ),
            (
                "search_button",
                PointerMoveRequest(PointerOrigin.ELEMENT_CENTER, steps=10),
                SEARCH,
            ),
            (
                f"{other_label.lower().replace(' ', '_')}_control",
                PointerMoveRequest(PointerOrigin.ELEMENT_CENTER, steps=9),
                other_control,
            ),
            (
                "open_globe_space",
                PointerMoveRequest(PointerOrigin.VIEWPORT, x=840, y=330, steps=14),
                None,
            ),
            (
                "upper_globe_region",
                PointerMoveRequest(PointerOrigin.VIEWPORT, x=740, y=150, steps=11),
                None,
            ),
            (
                "right_globe_region",
                PointerMoveRequest(PointerOrigin.VIEWPORT, x=1080, y=300, steps=15),
                None,
            ),
            (
                "lower_globe_region",
                PointerMoveRequest(PointerOrigin.VIEWPORT, x=760, y=600, steps=13),
                None,
            ),
            (
                "left_globe_region",
                PointerMoveRequest(PointerOrigin.VIEWPORT, x=340, y=400, steps=16),
                None,
            ),
        ]
        pointer_results: list[dict[str, object]] = []
        for index, (label, request, locator) in enumerate(moves, start=1):
            receipt = run_plan(
                backend,
                f"pointer_{index:02d}_{label}",
                [pointer_operation(f"move-{index:02d}-{label}", request, locator)],
                ScreenshotPolicy.ALWAYS,
            )
            step = receipt.steps[0].receipt
            evidence = step.action_evidence or {}
            required = (
                "requested",
                "resolved_position",
                "viewport",
                "previous_position",
                "final_position",
                "position_verification",
            )
            if receipt.plan_verdict.value != "VERIFIED":
                raise RuntimeError(f"pointer move {label} was not VERIFIED")
            if any(field not in evidence for field in required):
                raise RuntimeError(f"pointer move {label} has incomplete evidence")
            verification = evidence["position_verification"]
            if not isinstance(verification, dict) or verification.get("verified") is not True:
                raise RuntimeError(f"pointer move {label} was not position-verified")
            pointer_results.append(
                {
                    "label": label,
                    "requested": evidence["requested"],
                    "resolved_position": evidence["resolved_position"],
                    "viewport": evidence["viewport"],
                    "previous_position": evidence["previous_position"],
                    "final_position": evidence["final_position"],
                    "position_verification": verification,
                }
            )

        screenshots = sorted(str(path) for path in SCREENSHOTS.glob("*.png"))
        save(
            ROOT / "run_result.json",
            {
                "verdict": "PASS",
                "google_earth_url": EARTH_URL,
                "interface_ready": True,
                "interface_ready_evidence": (
                    "unique visible Search button and second visible "
                    f"{other_label} control"
                ),
                "successful_pointer_moves": len(pointer_results),
                "pointer_targets": [item["label"] for item in pointer_results],
                "pointer_results": pointer_results,
                "screenshot_count": len(screenshots),
                "screenshots": screenshots,
                "browser": backend.browser_environment(),
            },
        )
        status = "completed"
        return 0
    except Exception as exc:
        save(
            ROOT / "run_result.json",
            {
                "verdict": "FAIL",
                "google_earth_url": EARTH_URL,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        log("benchmark_failed", error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        before = backend.browser_environment()
        backend.stop()
        after = backend.browser_environment()
        save(
            ROOT / "terminal_browser.json",
            {"status": status, "before_stop": before, "after_stop": after},
        )
        log("browser_stopped", status=status, cleanup_errors=after["cleanup_errors"])


if __name__ == "__main__":
    raise SystemExit(main())
