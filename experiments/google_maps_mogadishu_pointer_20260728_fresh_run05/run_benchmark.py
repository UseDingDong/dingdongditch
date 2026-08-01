"""Fresh Google Maps pointer benchmark; production DingDongDitch only."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from PIL import Image

from dingdongditch import (
    Action, ActionType, BrowserChannel, BrowserConfig, BrowserEngine,
    BrowserProvider, ConstraintType, ExecutionPlan, Expectation,
    ExpectationType, Locator, LocatorStrategy, NameMatchMode, Operation,
    PageCondition, PageConditionType, PagePrecondition, PointerMoveRequest,
    PointerOrigin, ScreenshotConfig, ScreenshotPolicy, TargetConstraint,
    WaitCondition, WaitConditionType, execute_plan, inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode

ROOT = Path(__file__).resolve().parent
RECEIPTS = ROOT / "receipts"
SCREENSHOTS = ROOT / "screenshots"
INSPECTIONS = ROOT / "inspections"
LOGS = ROOT / "logs"
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS):
    directory.mkdir(parents=True, exist_ok=False)

URL = "https://maps.google.com"
QUERY = "Mogadishu, Somalia"
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
VISIBLE = (TargetConstraint(type=ConstraintType.VISIBLE, visible=True),)
SEARCH = Locator(
    strategy=LocatorStrategy.ROLE_NAME,
    role="combobox",
    name="Search Google Maps",
    name_match=NameMatchMode.EXACT,
)
POPULATED_SEARCH = Locator(
    strategy=LocatorStrategy.CSS,
    value="input",
    constraints=VISIBLE,
)
ZOOM_IN = Locator(
    strategy=LocatorStrategy.CSS,
    value="button[aria-label='Zoom in']",
    constraints=VISIBLE,
)
ZOOM_OUT = Locator(
    strategy=LocatorStrategy.CSS,
    value="button[aria-label='Zoom out']",
    constraints=VISIBLE,
)
BODY = Locator(strategy=LocatorStrategy.CSS, value="body")
PRE = PagePrecondition(
    conditions=(
        PageCondition(
            condition_id="origin",
            type=PageConditionType.ORIGIN_EQUALS,
            origin_value="https://www.google.com",
        ),
        PageCondition(
            condition_id="path",
            type=PageConditionType.PATH_STARTS_WITH,
            path_value="/maps",
        ),
    )
)

history: list[dict[str, object]] = []
readiness: list[dict[str, object]] = []
receipt_index = 0
inspection_index = 0


def write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def log(event: str, **values: object) -> None:
    history.append(
        {"at_unix_ms": int(time.time() * 1000), "event": event, **values}
    )
    write(LOGS / "run_history.json", history)


def url_expectation() -> list[Expectation]:
    return [
        Expectation(
            type=ExpectationType.URL,
            url_value="google.com/maps",
            url_match=UrlMatchMode.CONTAINS,
        )
    ]


def execute(backend: PlaywrightBackend, plan_id: str, operation: Operation):
    global receipt_index
    receipt_index += 1
    result = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=[operation],
            browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS,
                artifact_root=str(SCREENSHOTS),
            ),
            initial_plan_timeout_ms=60_000,
            max_plan_timeout_ms=60_000,
        ),
        backend=backend,
    )
    receipt = RECEIPTS / f"{receipt_index:02d}_{plan_id}.json"
    write(receipt, result.to_dict())
    log(
        "plan",
        plan_id=plan_id,
        verdict=result.plan_verdict.value,
        completion=result.completion_status.value,
        receipt=str(receipt),
    )
    return result


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict:
    global inspection_index
    inspection_index += 1
    result = inspect_target(backend, locator)
    artifact = INSPECTIONS / f"{inspection_index:03d}_{label}.json"
    write(artifact, result)
    log(
        "inspection",
        label=label,
        match_count=result.get("match_count"),
        visible=result.get("visible"),
        artifact=str(artifact),
    )
    return result


def latest_screenshot() -> Path:
    return max(
        SCREENSHOTS.glob("*.png"), key=lambda path: path.stat().st_mtime_ns
    )


def frame_evidence(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        sample = image.crop((0, 80, image.width, image.height)).resize((160, 80))
        pixels = list(sample.getdata())
        nonwhite = sum(1 for r, g, b in pixels if min(r, g, b) < 235)
        colors = {(r // 16, g // 16, b // 16) for r, g, b in pixels}
        return {
            "screenshot": str(path),
            "width": image.width,
            "height": image.height,
            "map_nonwhite_ratio": nonwhite / len(pixels),
            "quantized_color_count": len(colors),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


def wait_visible(
    backend: PlaywrightBackend, label: str, locator: Locator
) -> None:
    result = execute(
        backend,
        f"wait_{label}",
        Operation(
            operation_id=f"wait-{label}",
            url=URL,
            timeout_ms=30_000,
            action=Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE, locator=locator
                ),
                wait_timeout_ms=25_000,
            ),
            expectations=url_expectation(),
            page_precondition=PRE,
        ),
    )
    state = inspect(backend, f"{label}_ready", locator)
    if (
        result.plan_verdict.value != "VERIFIED"
        or state.get("match_count") != 1
        or state.get("visible") is not True
    ):
        raise RuntimeError(f"{label} readiness was not verified")


def observation(index: int) -> Operation:
    return Operation(
        operation_id=f"readiness-{index}",
        url=URL,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_condition=WaitCondition(
                type=WaitConditionType.URL_MATCHES,
                url_value="google.com/maps",
                url_match=UrlMatchMode.CONTAINS,
            ),
            wait_timeout_ms=1_000,
        ),
        expectations=url_expectation(),
        page_precondition=PRE,
    )


def pointer_operation(
    index: int,
    label: str,
    request: PointerMoveRequest,
    locator: Locator | None,
) -> Operation:
    return Operation(
        operation_id=f"pointer-{index}-{label}",
        url=URL,
        action=Action(
            type=ActionType.POINTER_MOVE,
            locator=locator,
            pointer_request=request,
        ),
        expectations=url_expectation(),
        page_precondition=PRE,
    )


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    status = "failed"
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        navigation = execute(
            backend,
            "navigate_google_maps",
            Operation(
                operation_id="navigate-maps",
                url=URL,
                action=Action(type=ActionType.NAVIGATE),
                expectations=url_expectation(),
            ),
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("navigation was not verified")
        navigation_finished = time.monotonic()

        for label, locator in (
            ("search", SEARCH),
            ("zoom_in", ZOOM_IN),
            ("zoom_out", ZOOM_OUT),
        ):
            wait_visible(backend, label, locator)

        for index in (1, 2):
            result = execute(
                backend, f"readiness_frame_{index}", observation(index)
            )
            if result.plan_verdict.value != "VERIFIED":
                raise RuntimeError(f"readiness frame {index} was not verified")
            evidence = {
                "index": index,
                "elapsed_since_navigation_ms": round(
                    (time.monotonic() - navigation_finished) * 1000
                ),
                **frame_evidence(latest_screenshot()),
            }
            readiness.append(evidence)
            write(LOGS / "readiness_observations.json", readiness)
            if index == 1:
                time.sleep(2)
        readiness[1]["stable_gap_ms"] = (
            int(readiness[1]["elapsed_since_navigation_ms"])
            - int(readiness[0]["elapsed_since_navigation_ms"])
        )
        readiness[1]["ready"] = bool(
            float(readiness[0]["map_nonwhite_ratio"]) >= 0.30
            and float(readiness[1]["map_nonwhite_ratio"]) >= 0.30
            and int(readiness[0]["quantized_color_count"]) >= 40
            and int(readiness[1]["quantized_color_count"]) >= 40
            and int(readiness[1]["stable_gap_ms"]) >= 2_000
        )
        write(LOGS / "readiness_observations.json", readiness)
        if readiness[1]["ready"] is not True:
            raise RuntimeError("map-tile readiness was not established")

        declarations = (
            (
                "viewport_center",
                PointerMoveRequest(
                    PointerOrigin.VIEWPORT, x=640, y=360, steps=12
                ),
                None,
            ),
            (
                "search_box",
                PointerMoveRequest(PointerOrigin.ELEMENT_CENTER, steps=10),
                SEARCH,
            ),
            (
                "map_area",
                PointerMoveRequest(
                    PointerOrigin.VIEWPORT, x=760, y=390, steps=14
                ),
                None,
            ),
            (
                "zoom_in",
                PointerMoveRequest(PointerOrigin.ELEMENT_CENTER, steps=9),
                ZOOM_IN,
            ),
            (
                "zoom_out",
                PointerMoveRequest(PointerOrigin.ELEMENT_CENTER, steps=9),
                ZOOM_OUT,
            ),
            (
                "map_center_return",
                PointerMoveRequest(
                    PointerOrigin.VIEWPORT, x=640, y=360, steps=13
                ),
                None,
            ),
        )
        pointer_results = []
        required = {
            "requested",
            "resolved_position",
            "previous_position",
            "final_position",
            "steps",
            "viewport",
            "position_verification",
            "screenshots",
        }
        for index, (label, request, locator) in enumerate(declarations, 1):
            result = execute(
                backend,
                f"move_{index}_{label}",
                pointer_operation(index, label, request, locator),
            )
            evidence = result.steps[0].receipt.action_evidence or {}
            if result.plan_verdict.value != "VERIFIED":
                raise RuntimeError(f"pointer {label} was not verified")
            if not required.issubset(evidence):
                raise RuntimeError(f"pointer {label} evidence was incomplete")
            if evidence["position_verification"].get("verified") is not True:
                raise RuntimeError(f"pointer {label} position was not verified")
            pointer_results.append(
                {
                    "label": label,
                    "requested": evidence["requested"],
                    "resolved_position": evidence["resolved_position"],
                    "previous_position": evidence["previous_position"],
                    "final_position": evidence["final_position"],
                    "steps": evidence["steps"],
                    "viewport": evidence["viewport"],
                    "verification": evidence["position_verification"],
                    "screenshots": evidence["screenshots"],
                }
            )

        fill = execute(
            backend,
            "fill_mogadishu",
            Operation(
                operation_id="fill-search",
                url=URL,
                action=Action(
                    type=ActionType.FILL, locator=SEARCH, text=QUERY
                ),
                expectations=url_expectation(),
                page_precondition=PRE,
            ),
        )
        if fill.plan_verdict.value != "VERIFIED":
            raise RuntimeError("search fill was not verified")
        populated = inspect(backend, "populated_search", POPULATED_SEARCH)
        if populated.get("match_count") != 1:
            raise RuntimeError("populated search input was not unique")

        submit = execute(
            backend,
            "submit_mogadishu",
            Operation(
                operation_id="submit-search",
                url=URL,
                action=Action(
                    type=ActionType.PRESS_KEY,
                    locator=POPULATED_SEARCH,
                    key="Enter",
                ),
                expectations=url_expectation(),
                page_precondition=PRE,
            ),
        )
        if submit.plan_verdict.value != "VERIFIED":
            raise RuntimeError("search submit was not verified")

        final = execute(
            backend,
            "wait_mogadishu_result",
            Operation(
                operation_id="wait-result",
                url=URL,
                timeout_ms=30_000,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.TEXT_PRESENT,
                        locator=BODY,
                        text_value="Mogadishu",
                        text_match=TextMatchMode.CONTAINS,
                    ),
                    wait_timeout_ms=25_000,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.TEXT,
                        locator=BODY,
                        text_value="Somalia",
                        text_match=TextMatchMode.CONTAINS,
                    )
                ],
                page_precondition=PRE,
            ),
        )
        if final.plan_verdict.value != "VERIFIED":
            raise RuntimeError("final result was not verified")
        body = inspect(backend, "final_mogadishu_body", BODY)
        visible_text = body.get("text") or ""
        if (
            "mogadishu" not in visible_text.lower()
            or "somalia" not in visible_text.lower()
        ):
            raise RuntimeError("visible evidence lacked Mogadishu, Somalia")

        screenshots = sorted(str(path) for path in SCREENSHOTS.glob("*.png"))
        write(
            ROOT / "run_result.json",
            {
                "verdict": "PASS",
                "google_maps_url": URL,
                "final_url": body["page"]["url"],
                "navigation_verdict": navigation.plan_verdict.value,
                "interface_ready_ms": readiness[1][
                    "elapsed_since_navigation_ms"
                ],
                "readiness_evidence": readiness[1],
                "pointer_move_count": len(pointer_results),
                "pointer_targets": [
                    item["label"] for item in pointer_results
                ],
                "pointer_results": pointer_results,
                "search_query": QUERY,
                "fill_verdict": fill.plan_verdict.value,
                "submit_verdict": submit.plan_verdict.value,
                "final_result_verdict": final.plan_verdict.value,
                "final_verified_location": QUERY,
                "final_visible_text_excerpt": visible_text[:2000],
                "screenshot_count": len(screenshots),
                "screenshots": screenshots,
                "cursor_capture_note": (
                    "Page screenshots do not capture the OS cursor; typed "
                    "receipts preserve requested and verified positions."
                ),
            },
        )
        status = "completed"
        return 0
    except Exception as exc:
        write(
            ROOT / "run_result.json",
            {
                "verdict": "FAIL",
                "google_maps_url": URL,
                "error": f"{type(exc).__name__}: {exc}",
                "readiness_observations": readiness,
            },
        )
        log("benchmark_failed", error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        before = backend.browser_environment()
        backend.stop()
        after = backend.browser_environment()
        write(
            ROOT / "terminal_browser.json",
            {"status": status, "before_stop": before, "after_stop": after},
        )
        log(
            "browser_stopped",
            status=status,
            cleanup_errors=after["cleanup_errors"],
        )


if __name__ == "__main__":
    raise SystemExit(main())
