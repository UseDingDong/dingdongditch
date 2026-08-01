"""Visible Amazon benchmark; every interaction is a one-step ExecutionPlan."""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserConfig, BrowserProfile
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import UrlMatchMode
from dingdongditch.contract.operation import Action, ActionType, Operation
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.inspection import inspect_target
from dingdongditch.runtime.plan_executor import execute_plan

from run_benchmark import (
    AMAZON,
    FIRST_NAME,
    ORIGIN,
    QUERY,
    SECOND_NAME,
    css,
    home,
    link_name,
    proc_snapshot,
    product_page,
    search_page,
    visible,
    write_json,
)

ROOT = Path(__file__).resolve().parent / "headed_benchmark_run4"


def inspect(name: str, backend: PlaywrightBackend, locator: Any) -> dict[str, Any]:
    try:
        value = inspect_target(backend, locator)
    except Exception as exc:
        value = {"error": f"{type(exc).__name__}: {exc}"}
    write_json(ROOT / "inspections" / f"{name}.json", value)
    return value


def main() -> int:
    for name in ("screenshots", "receipts", "inspections"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    before = proc_snapshot()
    write_json(ROOT / "processes_before.json", before)
    started = time.monotonic()
    config = BrowserConfig(profile=BrowserProfile.DINGDONG, headless=False)
    screenshot = ScreenshotConfig(
        policy=ScreenshotPolicy.ALWAYS,
        full_page=True,
        max_per_operation=2,
        max_per_plan=2,
        artifact_root=str(ROOT / "screenshots"),
        capture_timeout_ms=10_000,
    )
    backend = PlaywrightBackend(browser_config=config)
    summary: dict[str, Any] = {
        "result": "FAIL",
        "profile": config.profile.value,
        "configured_headless": config.headless,
        "visible_window_required": True,
        "pause_after_success_seconds": 1,
        "steps": [],
        "captcha_friction": False,
        "checkout_attempted": False,
        "direct_playwright_input": False,
        "javascript_injection": False,
    }

    search = css("#twotabsearchtextbox")
    results = css("div.s-main-slot")
    first = css(
        "div[data-asin='B0D14N2QZF'] "
        "a.a-link-normal.s-line-clamp-2[href*='/dp/B0D14N2QZF']"
    )
    second = link_name(SECOND_NAME)
    footer = css("#navFooter")
    title = css("span#productTitle")
    price = css("#corePrice_feature_div .a-offscreen")
    rating = css("#averageCustomerReviews_feature_div #acrPopover")
    availability = css("#availability")
    captcha = css(
        "form[action*='validateCaptcha'], #captchacharacters, "
        "input[name='cvf_captcha_input']"
    )
    step_number = 0

    def run_step(operation: Operation) -> Any:
        nonlocal step_number
        step_number += 1
        plan = __import__(
            "dingdongditch.contract.plan", fromlist=["ExecutionPlan"]
        ).ExecutionPlan(
            plan_id=f"amazon-headed-{step_number:02d}-{operation.operation_id}",
            browser_config=config,
            screenshot_config=screenshot,
            initial_plan_timeout_ms=90_000,
            operations=[operation],
        )
        receipt = execute_plan(plan, backend=backend)
        write_json(
            ROOT / "receipts" / f"{step_number:02d}_{operation.operation_id}.json",
            receipt.to_dict(),
        )
        record = {
            "step": step_number,
            "operation_id": operation.operation_id,
            "verdict": receipt.plan_verdict.value,
            "started_at_ms": receipt.started_at_ms,
            "finished_at_ms": receipt.finished_at_ms,
            "pause_after_success_seconds": 0,
        }
        if receipt.plan_verdict.value == "VERIFIED":
            time.sleep(1)
            record["pause_after_success_seconds"] = 1
        summary["steps"].append(record)
        return receipt

    try:
        backend.start()
        effective = backend.browser_environment()
        summary["effective_browser"] = effective
        print(
            "EFFECTIVE_BROWSER_MODE "
            f"profile={effective.get('profile', config.profile.value)} "
            f"engine={effective.get('engine')} "
            f"headless={str(effective.get('headless')).lower()} "
            "window=visible-headed"
        )
        if effective.get("headless") is not False:
            summary["boundary"] = "effective_browser_was_not_headed"
            return 1

        steps = [
            Operation(
                operation_id="open-amazon",
                url=AMAZON,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="amazon.com",
                        url_match=UrlMatchMode.CONTAINS,
                    ),
                    Expectation(
                        type=ExpectationType.ELEMENT_VISIBLE,
                        locator=search,
                        visible=True,
                    ),
                ],
                timeout_ms=35_000,
            ),
            Operation(
                operation_id="fill-search",
                url=AMAZON,
                page_precondition=home(visible("search", search)),
                action=Action(type=ActionType.FILL, locator=search, text=QUERY),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=search,
                        attribute_name="value",
                        attribute_value=QUERY,
                    )
                ],
                timeout_ms=20_000,
            ),
            Operation(
                operation_id="submit-search",
                url=AMAZON,
                page_precondition=home(visible("search", search)),
                action=Action(type=ActionType.PRESS_KEY, locator=search, key="Enter"),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="/s?",
                        url_match=UrlMatchMode.CONTAINS,
                    ),
                    Expectation(
                        type=ExpectationType.ELEMENT_VISIBLE,
                        locator=results,
                        visible=True,
                    ),
                ],
                timeout_ms=40_000,
            ),
        ]
        for operation in steps:
            if run_step(operation).plan_verdict.value != "VERIFIED":
                summary["boundary"] = operation.operation_id
                return 1
        summary["search_results_url"] = backend.page.url

        inspect("01_visible_dp_links", backend, css("a[href*='/dp/']"))
        first_state = inspect("02_first_identity_initial", backend, first)
        second_state = inspect("03_second_identity_initial", backend, second)
        captcha_state = inspect("04_captcha_after_search", backend, captcha)
        summary["captcha_friction"] = bool(captcha_state.get("exists"))
        if summary["captcha_friction"]:
            summary["boundary"] = "captcha_after_search"
            return 1
        if first_state.get("match_count") != 1 or second_state.get("match_count") != 1:
            summary["boundary"] = "stable_identity_not_unique"
            return 1

        scroll = Operation(
            operation_id="scroll-results-far-away",
            url=AMAZON,
            page_precondition=search_page(visible("results", results)),
            action=Action(type=ActionType.SCROLL_TO_TARGET, locator=footer),
            expectations=[
                Expectation(
                    type=ExpectationType.ELEMENT_IN_VIEWPORT,
                    locator=footer,
                    in_viewport=True,
                ),
                Expectation(
                    type=ExpectationType.ELEMENT_IN_VIEWPORT,
                    locator=first,
                    in_viewport=False,
                ),
            ],
            timeout_ms=25_000,
        )
        if run_step(scroll).plan_verdict.value != "VERIFIED":
            summary["boundary"] = scroll.operation_id
            return 1

        open_first = Operation(
            operation_id="relocate-prepare-open-first",
            url=AMAZON,
            page_precondition=search_page(visible("results", results)),
            action=Action(type=ActionType.CLICK, locator=first),
            expectations=[
                Expectation(
                    type=ExpectationType.URL,
                    url_value="/dp/",
                    url_match=UrlMatchMode.CONTAINS,
                ),
                Expectation(
                    type=ExpectationType.ELEMENT_VISIBLE,
                    locator=title,
                    visible=True,
                ),
                Expectation(
                    type=ExpectationType.ELEMENT_VISIBLE,
                    locator=price,
                    visible=True,
                ),
                Expectation(
                    type=ExpectationType.ELEMENT_VISIBLE,
                    locator=rating,
                    visible=True,
                ),
                Expectation(
                    type=ExpectationType.ELEMENT_VISIBLE,
                    locator=availability,
                    visible=True,
                ),
            ],
            timeout_ms=45_000,
        )
        if run_step(open_first).plan_verdict.value != "VERIFIED":
            summary["boundary"] = open_first.operation_id
            return 1
        summary["first_product_url"] = backend.page.url
        inspect("05_first_title", backend, title)
        inspect("06_first_price", backend, price)
        inspect("07_first_rating", backend, rating)
        inspect("08_first_availability", backend, availability)
        if inspect("09_captcha_first_product", backend, captcha).get("exists"):
            summary["captcha_friction"] = True
            summary["boundary"] = "captcha_first_product"
            return 1

        refill = Operation(
            operation_id="refill-search-on-product",
            url=AMAZON,
            page_precondition=product_page(visible("title", title)),
            action=Action(type=ActionType.FILL, locator=search, text=QUERY),
            expectations=[
                Expectation(
                    type=ExpectationType.ATTRIBUTE,
                    locator=search,
                    attribute_name="value",
                    attribute_value=QUERY,
                )
            ],
            timeout_ms=20_000,
        )
        if run_step(refill).plan_verdict.value != "VERIFIED":
            summary["boundary"] = refill.operation_id
            return 1

        back = Operation(
            operation_id="return-to-results",
            url=AMAZON,
            page_precondition=product_page(visible("title", title)),
            action=Action(type=ActionType.PRESS_KEY, locator=search, key="Enter"),
            expectations=[
                Expectation(
                    type=ExpectationType.URL,
                    url_value="/s?",
                    url_match=UrlMatchMode.CONTAINS,
                ),
                Expectation(
                    type=ExpectationType.ELEMENT_VISIBLE,
                    locator=second,
                    visible=True,
                ),
            ],
            timeout_ms=40_000,
        )
        if run_step(back).plan_verdict.value != "VERIFIED":
            summary["boundary"] = back.operation_id
            return 1

        open_second = Operation(
            operation_id="open-second-by-identity",
            url=AMAZON,
            page_precondition=search_page(visible("results", results)),
            action=Action(type=ActionType.CLICK, locator=second),
            expectations=[
                Expectation(
                    type=ExpectationType.URL,
                    url_value="/dp/",
                    url_match=UrlMatchMode.CONTAINS,
                ),
                Expectation(
                    type=ExpectationType.ELEMENT_VISIBLE,
                    locator=title,
                    visible=True,
                ),
                Expectation(
                    type=ExpectationType.ELEMENT_VISIBLE,
                    locator=price,
                    visible=True,
                ),
            ],
            timeout_ms=45_000,
        )
        if run_step(open_second).plan_verdict.value != "VERIFIED":
            summary["boundary"] = open_second.operation_id
            return 1
        summary["second_product_url"] = backend.page.url
        inspect("10_second_title", backend, title)
        inspect("11_second_price", backend, price)
        if inspect("12_captcha_second_product", backend, captcha).get("exists"):
            summary["captcha_friction"] = True
            summary["boundary"] = "captcha_second_product"
            return 1
        summary["result"] = "PASS"
        return 0
    except Exception as exc:
        summary["harness_error"] = f"{type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
        return 2
    finally:
        summary["final_url_before_cleanup"] = (
            backend.page.url if backend.is_started else None
        )
        try:
            backend.stop()
        except Exception as exc:
            summary["cleanup_exception"] = f"{type(exc).__name__}: {exc}"
        owned_names = {"chrome.exe", "chromium.exe", "node.exe", "playwright.exe"}
        after = proc_snapshot()
        for _ in range(10):
            remaining = [
                {"pid": pid, "image": image}
                for pid, image in after.items()
                if pid not in before and image.lower() in owned_names
            ]
            if not remaining:
                break
            time.sleep(0.5)
            after = proc_snapshot()
        summary["remaining_owned_processes"] = remaining
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        summary["cleanup_errors"] = list(backend.cleanup_errors)
        summary["terminal_session_identity"] = backend.terminal_session_identity
        write_json(ROOT / "processes_after.json", after)
        write_json(ROOT / "summary.json", summary)


if __name__ == "__main__":
    raise SystemExit(main())
