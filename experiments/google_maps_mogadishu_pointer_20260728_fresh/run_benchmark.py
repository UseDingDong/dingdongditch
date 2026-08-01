"""Fresh Google Maps POINTER_MOVE and Mogadishu search benchmark."""
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

START_URL = "https://maps.google.com"
QUERY = "Mogadishu, Somalia"
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
SEARCH = Locator(strategy=LocatorStrategy.CSS, value="input#searchboxinput")
ZOOM_IN = Locator(
    strategy=LocatorStrategy.CSS, value="button[aria-label='Zoom in']"
)
ZOOM_OUT = Locator(
    strategy=LocatorStrategy.CSS, value="button[aria-label='Zoom out']"
)
BODY = Locator(strategy=LocatorStrategy.CSS, value="body")
MAP_PRECONDITION = PagePrecondition(conditions=(
    PageCondition(
        condition_id="maps-origin",
        type=PageConditionType.ORIGIN_EQUALS,
        origin_value="https://www.google.com",
    ),
    PageCondition(
        condition_id="maps-path",
        type=PageConditionType.PATH_STARTS_WITH,
        path_value="/maps",
    ),
))
events: list[dict[str, object]] = []
readiness_observations: list[dict[str, object]] = []
receipt_index = 0
inspection_index = 0


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **details: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **details})
    save(LOGS / "run_history.json", events)


def maps_url_expectation() -> list[Expectation]:
    return [Expectation(
        type=ExpectationType.URL,
        url_value="google.com/maps",
        url_match=UrlMatchMode.CONTAINS,
    )]


def run(
    backend: PlaywrightBackend,
    plan_id: str,
    operation: Operation,
    screenshot_policy: ScreenshotPolicy = ScreenshotPolicy.ALWAYS,
):
    global receipt_index
    receipt_index += 1
    receipt = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=[operation],
            browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=screenshot_policy, artifact_root=str(SCREENSHOTS)
            ),
            initial_plan_timeout_ms=60_000,
            max_plan_timeout_ms=60_000,
        ),
        backend=backend,
    )
    artifact = RECEIPTS / f"{receipt_index:02d}_{plan_id}.json"
    save(artifact, receipt.to_dict())
    log(
        "plan", plan_id=plan_id, verdict=receipt.plan_verdict.value,
        completion=receipt.completion_status.value, receipt=str(artifact),
    )
    return receipt


def inspect(
    backend: PlaywrightBackend, label: str, locator: Locator
) -> dict:
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


def latest_screenshot() -> Path:
    return max(SCREENSHOTS.glob("*.png"), key=lambda path: path.stat().st_mtime_ns)


def map_frame_metrics(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        crop = image.crop((0, 80, image.width, image.height))
        reduced = crop.resize((160, 80))
        pixels = list(reduced.getdata())
        nonwhite = sum(1 for r, g, b in pixels if min(r, g, b) < 235)
        quantized = {
            (r // 16, g // 16, b // 16) for r, g, b in pixels
        }
        return {
            "screenshot": str(path),
            "width": image.width,
            "height": image.height,
            "map_nonwhite_ratio": nonwhite / len(pixels),
            "map_quantized_color_count": len(quantized),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


def current_url(backend: PlaywrightBackend) -> str:
    return str(inspect(backend, "current_page_body", BODY)["page"]["url"])


def maybe_accept_consent(backend: PlaywrightBackend) -> None:
    body = inspect(backend, "initial_body", BODY)
    text = (body.get("text") or "").lower()
    if "accept all" not in text:
        return
    consent_url = str(body["page"]["url"])
    locator = Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Accept all",
        name_match=NameMatchMode.EXACT,
    )
    receipt = run(
        backend, "accept_cookie_consent",
        Operation(
            operation_id="accept-consent", url=consent_url,
            action=Action(type=ActionType.CLICK, locator=locator),
            expectations=[],
        ),
    )
    if not receipt.steps[0].receipt.action_executed_successfully:
        raise RuntimeError("cookie consent could not be accepted")


def wait_visible(
    backend: PlaywrightBackend,
    plan_id: str,
    locator: Locator,
) -> None:
    receipt = run(
        backend, plan_id,
        Operation(
            operation_id=plan_id, url=START_URL, timeout_ms=30_000,
            action=Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE, locator=locator
                ),
                wait_timeout_ms=25_000,
            ),
            expectations=maps_url_expectation(),
            page_precondition=MAP_PRECONDITION,
        ),
    )
    if receipt.plan_verdict.value != "VERIFIED":
        raise RuntimeError(f"{plan_id} was not VERIFIED")


def observation_operation(index: int) -> Operation:
    return Operation(
        operation_id=f"observe-maps-{index}", url=START_URL,
        action=Action(
            type=ActionType.WAIT_FOR,
            wait_condition=WaitCondition(
                type=WaitConditionType.URL_MATCHES,
                url_value="google.com/maps",
                url_match=UrlMatchMode.CONTAINS,
            ),
            wait_timeout_ms=1_000,
        ),
        expectations=maps_url_expectation(),
        page_precondition=MAP_PRECONDITION,
    )


def pointer_operation(
    index: int,
    label: str,
    request: PointerMoveRequest,
    locator: Locator | None,
) -> Operation:
    return Operation(
        operation_id=f"pointer-{index}-{label}", url=START_URL,
        action=Action(
            type=ActionType.POINTER_MOVE,
            locator=locator,
            pointer_request=request,
        ),
        expectations=maps_url_expectation(),
        page_precondition=MAP_PRECONDITION,
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
                operation_id="navigate-maps", url=START_URL,
                action=Action(type=ActionType.NAVIGATE),
                expectations=maps_url_expectation(),
            ),
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Google Maps navigation was not VERIFIED")
        navigation_completed = time.monotonic()
        maybe_accept_consent(backend)

        wait_visible(backend, "wait_search_visible", SEARCH)
        wait_visible(backend, "wait_zoom_in_visible", ZOOM_IN)
        wait_visible(backend, "wait_zoom_out_visible", ZOOM_OUT)
        for label, locator in (
            ("search_ready", SEARCH), ("zoom_in_ready", ZOOM_IN),
            ("zoom_out_ready", ZOOM_OUT),
        ):
            state = inspect(backend, label, locator)
            if state.get("match_count") != 1 or state.get("visible") is not True:
                raise RuntimeError(f"{label} was not uniquely visible")

        previous = None
        ready_ms = None
        for index in range(1, 6):
            if previous is not None:
                time.sleep(2)
            receipt = run(
                backend, f"readiness_frame_{index}",
                observation_operation(index),
            )
            if receipt.plan_verdict.value != "VERIFIED":
                raise RuntimeError("readiness frame plan was not VERIFIED")
            metrics = map_frame_metrics(latest_screenshot())
            entry = {
                "index": index,
                "elapsed_since_navigation_ms": round(
                    (time.monotonic() - navigation_completed) * 1000
                ),
                **metrics,
            }
            rich_map = (
                float(metrics["map_nonwhite_ratio"]) >= 0.35
                and int(metrics["map_quantized_color_count"]) >= 40
            )
            if rich_map and previous is not None:
                gap = (
                    int(entry["elapsed_since_navigation_ms"])
                    - int(previous["elapsed_since_navigation_ms"])
                )
                entry["stable_gap_ms"] = gap
                if gap >= 2_000:
                    entry["ready"] = True
                    readiness_observations.append(entry)
                    ready_ms = int(entry["elapsed_since_navigation_ms"])
                    save(
                        LOGS / "readiness_observations.json",
                        readiness_observations,
                    )
                    break
            entry["ready"] = False
            readiness_observations.append(entry)
            save(LOGS / "readiness_observations.json", readiness_observations)
            previous = entry if rich_map else None
        if ready_ms is None:
            raise RuntimeError("Google Maps tile readiness was not established")

        moves = (
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
        pointer_results = []
        for index, (label, request, locator) in enumerate(moves, 1):
            receipt = run(
                backend, f"move_{index}_{label}",
                pointer_operation(index, label, request, locator),
            )
            evidence = receipt.steps[0].receipt.action_evidence or {}
            if receipt.plan_verdict.value != "VERIFIED":
                raise RuntimeError(f"pointer plan {label} was not VERIFIED")
            if evidence.get("position_verification", {}).get("verified") is not True:
                raise RuntimeError(f"pointer plan {label} was not verified")
            pointer_results.append({
                "label": label,
                "requested": evidence.get("requested"),
                "resolved_position": evidence.get("resolved_position"),
                "previous_position": evidence.get("previous_position"),
                "final_position": evidence.get("final_position"),
                "steps": evidence.get("steps"),
                "viewport": evidence.get("viewport"),
                "verification": evidence.get("position_verification"),
                "screenshots": evidence.get("screenshots"),
            })

        fill = run(
            backend, "fill_mogadishu_search",
            Operation(
                operation_id="fill-search", url=START_URL,
                action=Action(
                    type=ActionType.FILL, locator=SEARCH, text=QUERY
                ),
                expectations=[Expectation(
                    type=ExpectationType.ATTRIBUTE,
                    locator=SEARCH,
                    attribute_name="value",
                    attribute_value=QUERY,
                )],
                page_precondition=MAP_PRECONDITION,
            ),
        )
        if fill.plan_verdict.value != "VERIFIED":
            raise RuntimeError("search fill was not VERIFIED")

        submit = run(
            backend, "submit_mogadishu_search",
            Operation(
                operation_id="submit-search", url=START_URL,
                action=Action(
                    type=ActionType.PRESS_KEY, locator=SEARCH, key="Enter"
                ),
                expectations=[Expectation(
                    type=ExpectationType.ATTRIBUTE,
                    locator=SEARCH,
                    attribute_name="value",
                    attribute_value=QUERY,
                )],
                page_precondition=MAP_PRECONDITION,
            ),
        )
        if submit.plan_verdict.value != "VERIFIED":
            raise RuntimeError("search submit was not VERIFIED")

        final_wait = run(
            backend, "wait_for_mogadishu_result",
            Operation(
                operation_id="wait-mogadishu", url=START_URL,
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
                expectations=[Expectation(
                    type=ExpectationType.TEXT,
                    locator=BODY,
                    text_value="Somalia",
                    text_match=TextMatchMode.CONTAINS,
                )],
                page_precondition=MAP_PRECONDITION,
            ),
        )
        if final_wait.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Mogadishu result was not VERIFIED")

        final_body = inspect(backend, "final_mogadishu_body", BODY)
        final_search = inspect(backend, "final_search_field", SEARCH)
        final_text = final_body.get("text") or ""
        if "mogadishu" not in final_text.lower() or "somalia" not in final_text.lower():
            raise RuntimeError("final visible text lacked Mogadishu, Somalia")

        screenshots = sorted(str(path) for path in SCREENSHOTS.glob("*.png"))
        save(ROOT / "run_result.json", {
            "verdict": "PASS",
            "google_maps_url": START_URL,
            "final_url": str(final_body["page"]["url"]),
            "navigation_verdict": navigation.plan_verdict.value,
            "interface_ready_ms": ready_ms,
            "readiness_evidence": readiness_observations[-1],
            "pointer_move_count": len(pointer_results),
            "pointer_targets": [item["label"] for item in pointer_results],
            "pointer_results": pointer_results,
            "search_query": QUERY,
            "fill_verdict": fill.plan_verdict.value,
            "submit_verdict": submit.plan_verdict.value,
            "final_verdict": final_wait.plan_verdict.value,
            "final_verified_location": "Mogadishu, Somalia",
            "final_visible_text_excerpt": final_text[:2_000],
            "final_search_inspection": final_search,
            "screenshot_count": len(screenshots),
            "screenshots": screenshots,
            "cursor_capture_note": (
                "Playwright page screenshots do not include the OS cursor; "
                "typed receipts preserve authoritative pointer positions."
            ),
        })
        status = "completed"
        return 0
    except Exception as exc:
        save(ROOT / "run_result.json", {
            "verdict": "FAIL", "google_maps_url": START_URL,
            "error": f"{type(exc).__name__}: {exc}",
            "readiness_observations": readiness_observations,
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
