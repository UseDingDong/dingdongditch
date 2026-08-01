"""Fresh YouTube Shorts experiment using DingDongDitch exclusively.

Experiment-only YouTube layout adaptation:
- Probe several known current/legacy selectors through inspect_target().
- Choose only a unique, visible target; never use direct Playwright page methods.
- Dispatch every browser interaction as a DingDongDitch ExecutionPlan.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
)
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.modes import UrlMatchMode
from dingdongditch.contract.target import NameMatchMode
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.inspection import inspect_target, list_known_pages
from dingdongditch.runtime.plan_executor import execute_plan


ROOT = Path(__file__).resolve().parent / "run_05_search_seed_fresh"
RECEIPTS = ROOT / "receipts"
SCREENSHOTS = ROOT / "screenshots"
INSPECTIONS = ROOT / "inspections"
LOGS = ROOT / "logs"
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS):
    directory.mkdir(parents=True, exist_ok=False)

CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
SHOT_CONFIG = ScreenshotConfig(
    policy=ScreenshotPolicy.AFTER_SUCCESS,
    full_page=False,
    max_per_operation=2,
    max_per_plan=8,
    artifact_root=str(SCREENSHOTS),
)

events: list[dict[str, Any]] = []
receipt_index = 0
inspection_index = 0


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def log(event: str, **detail: Any) -> None:
    row = {"at_unix_ms": int(time.time() * 1000), "event": event, **detail}
    events.append(row)
    save_json(LOGS / "run_history.json", events)
    # Windows headed-run consoles can reject live emoji/non-BMP output.
    # Persisted JSON remains UTF-8; console output is safely escaped.
    try:
        print(json.dumps(row, ensure_ascii=True), flush=True)
    except OSError:
        # Evidence is already durably written above; a detached monitor may
        # close stdout without affecting the browser experiment.
        pass


def current_url(backend: PlaywrightBackend) -> str:
    active = [page for page in list_known_pages(backend) if page.get("active")]
    if len(active) != 1:
        raise RuntimeError(f"expected exactly one active DingDongDitch page, got {len(active)}")
    return str(active[0]["current_url"])


def run_plan(backend: PlaywrightBackend, plan_id: str, operations: list[Operation]):
    global receipt_index
    receipt_index += 1
    plan = ExecutionPlan(
        plan_id=plan_id,
        operations=operations,
        browser_config=CONFIG,
        screenshot_config=SHOT_CONFIG,
        initial_plan_timeout_ms=90_000,
    )
    receipt = execute_plan(plan, backend=backend)
    path = RECEIPTS / f"{receipt_index:02d}_{plan_id}.json"
    save_json(path, receipt.to_dict())
    log(
        "plan_complete",
        plan_id=plan_id,
        verdict=receipt.plan_verdict.value,
        completion=receipt.completion_status.value,
        receipt=str(path),
        session=receipt.browser_session_id,
        url=current_url(backend),
    )
    return receipt


def inspect(backend: PlaywrightBackend, label: str, selector: str) -> dict[str, Any]:
    global inspection_index
    inspection_index += 1
    locator = Locator(strategy=LocatorStrategy.CSS, value=selector)
    try:
        result = inspect_target(backend, locator)
    except Exception as exc:
        result = {"selector": selector, "inspection_error": f"{type(exc).__name__}: {exc}"}
    path = INSPECTIONS / f"{inspection_index:03d}_{label}.json"
    save_json(path, result)
    log(
        "inspection",
        label=label,
        selector=selector,
        match_count=result.get("match_count"),
        visible=result.get("visible"),
        text=(result.get("text") or "")[:300],
        artifact=str(path),
    )
    return result


def unique_visible(
    backend: PlaywrightBackend, label: str, selectors: list[str]
) -> tuple[str | None, dict[str, Any] | None]:
    for selector in selectors:
        result = inspect(backend, label, selector)
        if result.get("match_count") == 1 and (
            result.get("visible") is True or selector == "body"
        ):
            return selector, result
    return None, None


def main() -> int:
    backend = PlaywrightBackend(browser_config=CONFIG)
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())

        run_plan(
            backend,
            "navigate_youtube_home",
            [
                Operation(
                    operation_id="navigate-home",
                    url="https://www.youtube.com/",
                    action=Action(type=ActionType.NAVIGATE),
                    expectations=[
                        Expectation(
                            type=ExpectationType.URL,
                            url_value="youtube.com",
                            url_match=UrlMatchMode.CONTAINS,
                            expectation_id="youtube-url",
                        )
                    ],
                    timeout_ms=45_000,
                )
            ],
        )

        consent_selector, _ = unique_visible(
            backend,
            "consent_probe",
            [
                "button[aria-label*='Accept all']",
                "button[aria-label*='Reject all']",
                "form[action*='consent'] button",
            ],
        )
        if consent_selector:
            run_plan(
                backend,
                "minimal_consent",
                [
                    Operation(
                        operation_id="consent-click",
                        url=current_url(backend),
                        action=Action(
                            type=ActionType.CLICK,
                            locator=Locator(
                                strategy=LocatorStrategy.CSS, value=consent_selector
                            ),
                        ),
                        timeout_ms=20_000,
                    )
                ],
            )
        else:
            log("consent_not_present")

        shorts_selector, _ = unique_visible(
            backend,
            "shorts_navigation_probe",
            [
                "a[title='Shorts']",
                "ytd-guide-entry-renderer a[href='/shorts']",
                "a[href='/shorts']",
            ],
        )
        if shorts_selector:
            nav_receipt = run_plan(
                backend,
                "navigate_to_shorts_click",
                [
                    Operation(
                        operation_id="click-shorts",
                        url=current_url(backend),
                        action=Action(
                            type=ActionType.CLICK,
                            locator=Locator(
                                strategy=LocatorStrategy.CSS, value=shorts_selector
                            ),
                        ),
                        expectations=[
                            Expectation(
                                type=ExpectationType.URL,
                                url_value="/shorts",
                                url_match=UrlMatchMode.CONTAINS,
                                expectation_id="shorts-url-after-click",
                            )
                        ],
                        timeout_ms=30_000,
                    )
                ],
            )
            if "/shorts" not in current_url(backend):
                shorts_selector = None
        if not shorts_selector:
            log("layout_adjustment", adjustment="explicit /shorts navigation after no unique link")
            run_plan(
                backend,
                "navigate_to_shorts_url",
                [
                    Operation(
                        operation_id="navigate-shorts",
                        url="https://www.youtube.com/shorts",
                        action=Action(type=ActionType.NAVIGATE),
                        expectations=[
                            Expectation(
                                type=ExpectationType.URL,
                                url_value="/shorts",
                                url_match=UrlMatchMode.CONTAINS,
                                expectation_id="shorts-url",
                            )
                        ],
                        timeout_ms=45_000,
                    )
                ],
            )

        renderer_selectors = [
            "ytd-reel-video-renderer[is-active]",
            "ytd-reel-video-renderer[active]",
            "ytd-reel-video-renderer:has(video)",
            "body",
        ]
        _, initial_body = unique_visible(backend, "initial_shorts_body", ["body"])
        if initial_body and "Try searching to get started" in (initial_body.get("text") or ""):
            log(
                "layout_adjustment",
                adjustment="anonymous Shorts feed empty; seed via normal YouTube search",
            )
            run_plan(
                backend,
                "search_for_shorts_seed",
                [
                    Operation(
                        operation_id="navigate-search",
                        url="https://www.youtube.com/results?search_query=%23shorts",
                        action=Action(type=ActionType.NAVIGATE),
                        expectations=[
                            Expectation(
                                type=ExpectationType.URL,
                                url_value="search_query=",
                                url_match=UrlMatchMode.CONTAINS,
                                expectation_id="search-results-url",
                            )
                        ],
                        timeout_ms=45_000,
                    )
                ],
            )
            candidates = inspect(
                backend, "shorts_search_candidates", "a[href^='/shorts/']"
            ).get("target_resolution", {}).get("candidate_summaries", [])
            seeded = False
            for candidate in candidates:
                name = (candidate.get("nameGuess") or "").strip()
                if not name:
                    continue
                role_locator = Locator(
                    strategy=LocatorStrategy.ROLE_NAME,
                    role="link",
                    name=name,
                    name_match=NameMatchMode.EXACT,
                )
                try:
                    state = inspect_target(backend, role_locator)
                except Exception:
                    continue
                if state.get("match_count") != 1 or state.get("visible") is not True:
                    continue
                run_plan(
                    backend,
                    "open_search_seed_short",
                    [
                        Operation(
                            operation_id="click-seed-short",
                            url=current_url(backend),
                            action=Action(type=ActionType.CLICK, locator=role_locator),
                            expectations=[
                                Expectation(
                                    type=ExpectationType.URL,
                                    url_value="/shorts/",
                                    url_match=UrlMatchMode.CONTAINS,
                                    expectation_id="seed-short-url",
                                )
                            ],
                            timeout_ms=30_000,
                        )
                    ],
                )
                seeded = "/shorts/" in current_url(backend)
                log("search_seed_result", accessible_name=name, seeded=seeded)
                if seeded:
                    break
            if not seeded:
                log("search_seed_unavailable", candidates=len(candidates))

        observations: list[dict[str, Any]] = []
        seen_text: set[str] = set()
        attempts = 0
        while len(observations) < 5 and attempts < 9:
            attempts += 1
            selector, state = unique_visible(
                backend, f"short_{len(observations)+1}_renderer", renderer_selectors
            )
            if not selector or not state:
                log("shorts_interface_not_found", attempt=attempts)
                break
            text = (state.get("text") or "").strip()
            if text and text not in seen_text:
                seen_text.add(text)
                observation = {
                    "ordinal": len(observations) + 1,
                    "url": current_url(backend),
                    "selector": selector,
                    "visible_text": text,
                    "apparent_topic": "To be summarized from preserved visible text.",
                    "inspection_artifact": str(
                        sorted(INSPECTIONS.glob("*.json"))[-1]
                    ),
                }
                observations.append(observation)
                save_json(ROOT / "shorts_observations.json", observations)
                log("short_observed", ordinal=observation["ordinal"], text=text[:500])

            if len(observations) >= 5:
                break
            run_plan(
                backend,
                f"advance_short_{attempts}",
                [
                    Operation(
                        operation_id=f"arrow-down-{attempts}",
                        url=current_url(backend),
                        action=Action(
                            type=ActionType.PRESS_KEY,
                            key="ArrowDown",
                            key_scope=KeyPressScope.ACTIVE_PAGE,
                        ),
                        expectations=[
                            Expectation(
                                type=ExpectationType.URL,
                                url_value="/shorts",
                                url_match=UrlMatchMode.CONTAINS,
                                expectation_id=f"still-in-shorts-{attempts}",
                            )
                        ],
                        timeout_ms=15_000,
                    )
                ],
            )

        result = {
            "completed": len(observations) >= 5,
            "shorts_reviewed": len(observations),
            "browser": backend.browser_environment(),
            "observations": observations,
            "layout_adjustments": [
                "Probed current/legacy YouTube selectors through DingDongDitch inspect_target.",
                "Used explicit /shorts navigation only if no unique visible Shorts link was available.",
            ],
            "interaction_boundary": "All browser actions were DingDongDitch ExecutionPlans; all reads used DingDongDitch inspect_target.",
        }
        save_json(ROOT / "run_result.json", result)
        log("experiment_finished", completed=result["completed"], count=len(observations))
        return 0 if result["completed"] else 2
    except Exception as exc:
        save_json(
            ROOT / "external_limitation.json",
            {"error": f"{type(exc).__name__}: {exc}", "events": events},
        )
        log("experiment_exception", error=f"{type(exc).__name__}: {exc}")
        return 3
    finally:
        if backend.is_started:
            env = backend.browser_environment()
            backend.stop()
            save_json(ROOT / "terminal_browser.json", {"before_stop": env, "after_stop": backend.browser_environment()})


if __name__ == "__main__":
    raise SystemExit(main())
