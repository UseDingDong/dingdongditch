"""Fresh final Google Maps pointer and Mogadishu benchmark."""
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
RECEIPTS, SCREENSHOTS = ROOT / "receipts", ROOT / "screenshots"
INSPECTIONS, LOGS = ROOT / "inspections", ROOT / "logs"
for folder in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS):
    folder.mkdir(parents=True, exist_ok=False)

URL, QUERY = "https://maps.google.com", "Mogadishu, Somalia"
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT, engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED, headless=False,
)
visible = (TargetConstraint(type=ConstraintType.VISIBLE, visible=True),)
SEARCH = Locator(
    strategy=LocatorStrategy.ROLE_NAME, role="combobox",
    name="Search Google Maps", name_match=NameMatchMode.EXACT,
)
ZOOM_IN = Locator(
    strategy=LocatorStrategy.CSS, value="button[aria-label='Zoom in']",
    constraints=visible,
)
ZOOM_OUT = Locator(
    strategy=LocatorStrategy.CSS, value="button[aria-label='Zoom out']",
    constraints=visible,
)
BODY = Locator(strategy=LocatorStrategy.CSS, value="body")
PRE = PagePrecondition(conditions=(
    PageCondition(
        condition_id="origin", type=PageConditionType.ORIGIN_EQUALS,
        origin_value="https://www.google.com",
    ),
    PageCondition(
        condition_id="path", type=PageConditionType.PATH_STARTS_WITH,
        path_value="/maps",
    ),
))
history: list[dict[str, object]] = []
ready_observations: list[dict[str, object]] = []
receipt_no = 0
inspection_no = 0


def write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **data: object) -> None:
    history.append({"at_unix_ms": int(time.time() * 1000), "event": event, **data})
    write(LOGS / "run_history.json", history)


def url_expected() -> list[Expectation]:
    return [Expectation(
        type=ExpectationType.URL, url_value="google.com/maps",
        url_match=UrlMatchMode.CONTAINS,
    )]


def execute(backend: PlaywrightBackend, plan_id: str, op: Operation):
    global receipt_no
    receipt_no += 1
    result = execute_plan(
        ExecutionPlan(
            plan_id=plan_id, operations=[op], browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS, artifact_root=str(SCREENSHOTS)
            ),
            initial_plan_timeout_ms=60_000, max_plan_timeout_ms=60_000,
        ),
        backend=backend,
    )
    path = RECEIPTS / f"{receipt_no:02d}_{plan_id}.json"
    write(path, result.to_dict())
    log(
        "plan", plan_id=plan_id, verdict=result.plan_verdict.value,
        completion=result.completion_status.value, receipt=str(path),
    )
    return result


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict:
    global inspection_no
    inspection_no += 1
    result = inspect_target(backend, locator)
    path = INSPECTIONS / f"{inspection_no:03d}_{label}.json"
    write(path, result)
    log(
        "inspection", label=label, match_count=result.get("match_count"),
        visible=result.get("visible"), artifact=str(path),
    )
    return result


def latest_frame() -> Path:
    return max(SCREENSHOTS.glob("*.png"), key=lambda path: path.stat().st_mtime_ns)


def image_evidence(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        sample = image.crop((0, 80, image.width, image.height)).resize((160, 80))
        pixels = list(sample.getdata())
        dark_enough = sum(1 for r, g, b in pixels if min(r, g, b) < 235)
        colors = {(r // 16, g // 16, b // 16) for r, g, b in pixels}
        return {
            "screenshot": str(path), "width": image.width, "height": image.height,
            "map_nonwhite_ratio": dark_enough / len(pixels),
            "quantized_color_count": len(colors),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


def wait_visible(backend: PlaywrightBackend, name: str, locator: Locator) -> None:
    result = execute(
        backend, f"wait_{name}",
        Operation(
            operation_id=f"wait-{name}", url=URL, timeout_ms=30_000,
            action=Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE, locator=locator
                ),
                wait_timeout_ms=25_000,
            ),
            expectations=url_expected(), page_precondition=PRE,
        ),
    )
    if result.plan_verdict.value != "VERIFIED":
        raise RuntimeError(f"{name} readiness was not VERIFIED")
    state = inspect(backend, f"{name}_ready", locator)
    if state.get("match_count") != 1 or state.get("visible") is not True:
        raise RuntimeError(f"{name} was not uniquely visible")


def no_op_observation(index: int) -> Operation:
    return Operation(
        operation_id=f"observe-{index}", url=URL,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_condition=WaitCondition(
                type=WaitConditionType.URL_MATCHES,
                url_value="google.com/maps", url_match=UrlMatchMode.CONTAINS,
            ),
            wait_timeout_ms=1_000,
        ),
        expectations=url_expected(), page_precondition=PRE,
    )


def pointer_op(
    index: int, label: str, request: PointerMoveRequest,
    locator: Locator | None,
) -> Operation:
    return Operation(
        operation_id=f"pointer-{index}-{label}", url=URL,
        action=Action(
            type=ActionType.POINTER_MOVE, locator=locator,
            pointer_request=request,
        ),
        expectations=url_expected(), page_precondition=PRE,
    )


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    status = "failed"
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        navigation = execute(
            backend, "navigate_google_maps",
            Operation(
                operation_id="navigate-maps", url=URL,
                action=Action(type=ActionType.NAVIGATE),
                expectations=url_expected(),
            ),
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("navigation was not VERIFIED")
        nav_finished = time.monotonic()
        for name, locator in (
            ("search_visible", SEARCH), ("zoom_in_visible", ZOOM_IN),
            ("zoom_out_visible", ZOOM_OUT),
        ):
            wait_visible(backend, name, locator)

        first = execute(backend, "readiness_frame_1", no_op_observation(1))
        if first.plan_verdict.value != "VERIFIED":
            raise RuntimeError("first readiness frame was not VERIFIED")
        first_evidence = {
            "index": 1,
            "elapsed_since_navigation_ms": round(
                (time.monotonic() - nav_finished) * 1000
            ),
            **image_evidence(latest_frame()),
        }
        ready_observations.append(first_evidence)
        write(LOGS / "readiness_observations.json", ready_observations)
        time.sleep(2)
        second = execute(backend, "readiness_frame_2", no_op_observation(2))
        if second.plan_verdict.value != "VERIFIED":
            raise RuntimeError("second readiness frame was not VERIFIED")
        second_evidence = {
            "index": 2,
            "elapsed_since_navigation_ms": round(
                (time.monotonic() - nav_finished) * 1000
            ),
            **image_evidence(latest_frame()),
        }
        second_evidence["stable_gap_ms"] = (
            int(second_evidence["elapsed_since_navigation_ms"])
            - int(first_evidence["elapsed_since_navigation_ms"])
        )
        second_evidence["ready"] = bool(
            float(first_evidence["map_nonwhite_ratio"]) >= 0.30
            and float(second_evidence["map_nonwhite_ratio"]) >= 0.30
            and int(first_evidence["quantized_color_count"]) >= 40
            and int(second_evidence["quantized_color_count"]) >= 40
            and int(second_evidence["stable_gap_ms"]) >= 2_000
        )
        ready_observations.append(second_evidence)
        write(LOGS / "readiness_observations.json", ready_observations)
        if second_evidence["ready"] is not True:
            raise RuntimeError("stable map tile readiness was not established")
        ready_ms = int(second_evidence["elapsed_since_navigation_ms"])

        declarations = (
            ("viewport_center", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=640, y=360, steps=12
            ), None),
            ("search_box", PointerMoveRequest(
                PointerOrigin.ELEMENT_CENTER, steps=10
            ), SEARCH),
            ("map_area", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=760, y=390, steps=14
            ), None),
            ("zoom_in", PointerMoveRequest(
                PointerOrigin.ELEMENT_CENTER, steps=9
            ), ZOOM_IN),
            ("zoom_out", PointerMoveRequest(
                PointerOrigin.ELEMENT_CENTER, steps=9
            ), ZOOM_OUT),
            ("map_center_return", PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=640, y=360, steps=13
            ), None),
        )
        pointers = []
        for index, (label, request, locator) in enumerate(declarations, 1):
            receipt = execute(
                backend, f"move_{index}_{label}",
                pointer_op(index, label, request, locator),
            )
            evidence = receipt.steps[0].receipt.action_evidence or {}
            required = {
                "requested", "resolved_position", "previous_position",
                "final_position", "steps", "viewport",
                "position_verification", "screenshots",
            }
            if receipt.plan_verdict.value != "VERIFIED":
                raise RuntimeError(f"pointer {label} was not VERIFIED")
            if not required.issubset(evidence):
                raise RuntimeError(f"pointer {label} evidence was incomplete")
            if evidence["position_verification"].get("verified") is not True:
                raise RuntimeError(f"pointer {label} was not verified")
            pointers.append({
                "label": label,
                "requested": evidence["requested"],
                "resolved_position": evidence["resolved_position"],
                "previous_position": evidence["previous_position"],
                "final_position": evidence["final_position"],
                "steps": evidence["steps"],
                "viewport": evidence["viewport"],
                "verification": evidence["position_verification"],
                "screenshots": evidence["screenshots"],
            })

        fill = execute(
            backend, "fill_mogadishu",
            Operation(
                operation_id="fill-search", url=URL,
                action=Action(type=ActionType.FILL, locator=SEARCH, text=QUERY),
                expectations=[Expectation(
                    type=ExpectationType.ATTRIBUTE, locator=SEARCH,
                    attribute_name="value", attribute_value=QUERY,
                )],
                page_precondition=PRE,
            ),
        )
        if fill.plan_verdict.value != "VERIFIED":
            raise RuntimeError("search fill was not VERIFIED")
        submit = execute(
            backend, "submit_mogadishu",
            Operation(
                operation_id="submit-search", url=URL,
                action=Action(
                    type=ActionType.PRESS_KEY, locator=SEARCH, key="Enter"
                ),
                expectations=[Expectation(
                    type=ExpectationType.ATTRIBUTE, locator=SEARCH,
                    attribute_name="value", attribute_value=QUERY,
                )],
                page_precondition=PRE,
            ),
        )
        if submit.plan_verdict.value != "VERIFIED":
            raise RuntimeError("search submit was not VERIFIED")

        final = execute(
            backend, "wait_mogadishu_result",
            Operation(
                operation_id="wait-result", url=URL, timeout_ms=30_000,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.TEXT_PRESENT, locator=BODY,
                        text_value="Mogadishu",
                        text_match=TextMatchMode.CONTAINS,
                    ),
                    wait_timeout_ms=25_000,
                ),
                expectations=[Expectation(
                    type=ExpectationType.TEXT, locator=BODY,
                    text_value="Somalia", text_match=TextMatchMode.CONTAINS,
                )],
                page_precondition=PRE,
            ),
        )
        if final.plan_verdict.value != "VERIFIED":
            raise RuntimeError("final result was not VERIFIED")
        body = inspect(backend, "final_mogadishu_body", BODY)
        search = inspect(backend, "final_search_combobox", SEARCH)
        visible_text = body.get("text") or ""
        if (
            "mogadishu" not in visible_text.lower()
            or "somalia" not in visible_text.lower()
        ):
            raise RuntimeError("visible final evidence lacked Mogadishu, Somalia")

        screenshots = sorted(str(path) for path in SCREENSHOTS.glob("*.png"))
        write(ROOT / "run_result.json", {
            "verdict": "PASS",
            "google_maps_url": URL,
            "final_url": str(body["page"]["url"]),
            "navigation_verdict": navigation.plan_verdict.value,
            "interface_ready_ms": ready_ms,
            "readiness_evidence": second_evidence,
            "pointer_move_count": len(pointers),
            "pointer_targets": [item["label"] for item in pointers],
            "pointer_results": pointers,
            "search_query": QUERY,
            "fill_verdict": fill.plan_verdict.value,
            "submit_verdict": submit.plan_verdict.value,
            "final_result_verdict": final.plan_verdict.value,
            "final_verified_location": "Mogadishu, Somalia",
            "final_visible_text_excerpt": visible_text[:2_000],
            "final_search_inspection": search,
            "screenshot_count": len(screenshots),
            "screenshots": screenshots,
            "cursor_capture_note": (
                "Playwright page screenshots do not include the OS cursor; "
                "typed receipts preserve pointer positions."
            ),
        })
        status = "completed"
        return 0
    except Exception as exc:
        write(ROOT / "run_result.json", {
            "verdict": "FAIL", "google_maps_url": URL,
            "error": f"{type(exc).__name__}: {exc}",
            "readiness_observations": ready_observations,
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
