"""Fresh Google Maps semantic-combobox POINTER_MOVE benchmark."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from PIL import Image

from dingdongditch import (
    Action, ActionType, BrowserChannel, BrowserConfig, BrowserEngine,
    BrowserProvider, ExecutionPlan, Expectation, ExpectationType, Locator,
    LocatorStrategy, NameMatchMode, Operation, PageCondition,
    PageConditionType, PagePrecondition, PointerMoveRequest, PointerOrigin,
    ScreenshotConfig, ScreenshotPolicy, WaitCondition, WaitConditionType,
    execute_plan, inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode

ROOT = Path(__file__).resolve().parent
RECEIPTS, SCREENSHOTS = ROOT / "receipts", ROOT / "screenshots"
INSPECTIONS, LOGS = ROOT / "inspections", ROOT / "logs"
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
SEARCH = Locator(
    strategy=LocatorStrategy.ROLE_NAME,
    role="combobox",
    name="Search Google Maps",
    name_match=NameMatchMode.EXACT,
)
ZOOM_IN = Locator(
    strategy=LocatorStrategy.CSS, value="button[aria-label='Zoom in']"
)
ZOOM_OUT = Locator(
    strategy=LocatorStrategy.CSS, value="button[aria-label='Zoom out']"
)
BODY = Locator(strategy=LocatorStrategy.CSS, value="body")
PRECONDITION = PagePrecondition(conditions=(
    PageCondition(
        condition_id="maps-origin", type=PageConditionType.ORIGIN_EQUALS,
        origin_value="https://www.google.com",
    ),
    PageCondition(
        condition_id="maps-path", type=PageConditionType.PATH_STARTS_WITH,
        path_value="/maps",
    ),
))
events: list[dict[str, object]] = []
readiness: list[dict[str, object]] = []
receipt_index = 0
inspection_index = 0


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **detail: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **detail})
    save(LOGS / "run_history.json", events)


def url_expectation() -> list[Expectation]:
    return [Expectation(
        type=ExpectationType.URL, url_value="google.com/maps",
        url_match=UrlMatchMode.CONTAINS,
    )]


def run(backend: PlaywrightBackend, plan_id: str, operation: Operation):
    global receipt_index
    receipt_index += 1
    result = execute_plan(
        ExecutionPlan(
            plan_id=plan_id, operations=[operation], browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS, artifact_root=str(SCREENSHOTS)
            ),
            initial_plan_timeout_ms=60_000, max_plan_timeout_ms=60_000,
        ),
        backend=backend,
    )
    artifact = RECEIPTS / f"{receipt_index:02d}_{plan_id}.json"
    save(artifact, result.to_dict())
    log(
        "plan", plan_id=plan_id, verdict=result.plan_verdict.value,
        completion=result.completion_status.value, receipt=str(artifact),
    )
    return result


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict:
    global inspection_index
    inspection_index += 1
    state = inspect_target(backend, locator)
    artifact = INSPECTIONS / f"{inspection_index:03d}_{label}.json"
    save(artifact, state)
    log(
        "inspection", label=label, match_count=state.get("match_count"),
        visible=state.get("visible"), artifact=str(artifact),
    )
    return state


def newest_screenshot() -> Path:
    return max(SCREENSHOTS.glob("*.png"), key=lambda path: path.stat().st_mtime_ns)


def frame_metrics(path: Path) -> dict[str, object]:
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
    result = run(
        backend, label,
        Operation(
            operation_id=label, url=URL, timeout_ms=30_000,
            action=Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE, locator=locator
                ),
                wait_timeout_ms=25_000,
            ),
            expectations=url_expectation(), page_precondition=PRECONDITION,
        ),
    )
    if result.plan_verdict.value != "VERIFIED":
        raise RuntimeError(f"{label} was not VERIFIED")


def observe(index: int) -> Operation:
    return Operation(
        operation_id=f"observe-{index}", url=URL,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_condition=WaitCondition(
                type=WaitConditionType.URL_MATCHES,
                url_value="google.com/maps",
                url_match=UrlMatchMode.CONTAINS,
            ),
            wait_timeout_ms=1_000,
        ),
        expectations=url_expectation(), page_precondition=PRECONDITION,
    )


def pointer(
    index: int,
    label: str,
    request: PointerMoveRequest,
    locator: Locator | None,
) -> Operation:
    return Operation(
        operation_id=f"pointer-{index}-{label}", url=URL,
        action=Action(
            type=ActionType.POINTER_MOVE, locator=locator,
            pointer_request=request,
        ),
        expectations=url_expectation(), page_precondition=PRECONDITION,
    )


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    status = "failed"
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        navigation = run(
            backend, "navigate_google_maps",
            Operation(
                operation_id="navigate-maps", url=URL,
                action=Action(type=ActionType.NAVIGATE),
                expectations=url_expectation(),
            ),
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("navigation was not VERIFIED")
        navigation_finished = time.monotonic()

        for label, locator in (
            ("wait_search_visible", SEARCH),
            ("wait_zoom_in_visible", ZOOM_IN),
            ("wait_zoom_out_visible", ZOOM_OUT),
        ):
            wait_visible(backend, label, locator)
            state = inspect(backend, label.replace("wait_", ""), locator)
            if state.get("match_count") != 1 or state.get("visible") is not True:
                raise RuntimeError(f"{label} target was not uniquely visible")

        previous = None
        ready_ms = None
        for index in range(1, 4):
            if previous is not None:
                time.sleep(2)
            frame = run(backend, f"readiness_{index}", observe(index))
            if frame.plan_verdict.value != "VERIFIED":
                raise RuntimeError("readiness observation was not VERIFIED")
            entry = {
                "index": index,
                "elapsed_since_navigation_ms": round(
                    (time.monotonic() - navigation_finished) * 1000
                ),
                **frame_metrics(newest_screenshot()),
            }
            loaded = (
                float(entry["map_nonwhite_ratio"]) >= 0.35
                and int(entry["quantized_color_count"]) >= 40
            )
            if loaded and previous is not None:
                gap = (
                    int(entry["elapsed_since_navigation_ms"])
                    - int(previous["elapsed_since_navigation_ms"])
                )
                entry["stable_gap_ms"] = gap
                if gap >= 2_000:
                    entry["ready"] = True
                    readiness.append(entry)
                    ready_ms = int(entry["elapsed_since_navigation_ms"])
                    save(LOGS / "readiness_observations.json", readiness)
                    break
            entry["ready"] = False
            readiness.append(entry)
            save(LOGS / "readiness_observations.json", readiness)
            previous = entry if loaded else None
        if ready_ms is None:
            raise RuntimeError("Google Maps tile readiness was not established")

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
            receipt = run(
                backend, f"move_{index}_{label}",
                pointer(index, label, request, locator),
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
                raise RuntimeError(f"pointer {label} position was not verified")
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

        fill = run(
            backend, "fill_mogadishu",
            Operation(
                operation_id="fill-search", url=URL,
                action=Action(type=ActionType.FILL, locator=SEARCH, text=QUERY),
                expectations=[Expectation(
                    type=ExpectationType.ATTRIBUTE, locator=SEARCH,
                    attribute_name="value", attribute_value=QUERY,
                )],
                page_precondition=PRECONDITION,
            ),
        )
        if fill.plan_verdict.value != "VERIFIED":
            raise RuntimeError("search fill was not VERIFIED")
        submit = run(
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
                page_precondition=PRECONDITION,
            ),
        )
        if submit.plan_verdict.value != "VERIFIED":
            raise RuntimeError("search submit was not VERIFIED")

        final = run(
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
                page_precondition=PRECONDITION,
            ),
        )
        if final.plan_verdict.value != "VERIFIED":
            raise RuntimeError("final Mogadishu result was not VERIFIED")
        body = inspect(backend, "final_mogadishu_body", BODY)
        search = inspect(backend, "final_search_combobox", SEARCH)
        text = body.get("text") or ""
        if "mogadishu" not in text.lower() or "somalia" not in text.lower():
            raise RuntimeError("visible final evidence lacked Mogadishu, Somalia")

        screenshot_paths = sorted(str(path) for path in SCREENSHOTS.glob("*.png"))
        save(ROOT / "run_result.json", {
            "verdict": "PASS",
            "google_maps_url": URL,
            "final_url": str(body["page"]["url"]),
            "navigation_verdict": navigation.plan_verdict.value,
            "interface_ready_ms": ready_ms,
            "readiness_evidence": readiness[-1],
            "pointer_move_count": len(pointers),
            "pointer_targets": [item["label"] for item in pointers],
            "pointer_results": pointers,
            "search_query": QUERY,
            "fill_verdict": fill.plan_verdict.value,
            "submit_verdict": submit.plan_verdict.value,
            "final_result_verdict": final.plan_verdict.value,
            "final_verified_location": "Mogadishu, Somalia",
            "final_visible_text_excerpt": text[:2_000],
            "final_search_inspection": search,
            "screenshot_count": len(screenshot_paths),
            "screenshots": screenshot_paths,
            "cursor_capture_note": (
                "Playwright page screenshots do not capture the OS cursor; "
                "typed receipts preserve pointer positions."
            ),
        })
        status = "completed"
        return 0
    except Exception as exc:
        save(ROOT / "run_result.json", {
            "verdict": "FAIL", "google_maps_url": URL,
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
