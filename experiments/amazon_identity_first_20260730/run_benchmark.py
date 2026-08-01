"""Amazon identity-first benchmark: ExecutionPlans are the only interaction path."""
from __future__ import annotations

import csv
import io
import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserConfig, BrowserProfile
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import UrlMatchMode
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.page_precondition import (
    PageCondition,
    PageConditionType,
    PagePrecondition,
)
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.inspection import inspect_target
from dingdongditch.runtime.plan_executor import execute_plan

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "benchmark_run3"
AMAZON = "https://www.amazon.com/"
ORIGIN = "https://www.amazon.com"
QUERY = "wireless mechanical keyboard"
FIRST_NAME = "AULA F75 Pro Wireless Mechanical Keyboard"
SECOND_NAME = "Logitech MX Mechanical Wireless Illuminated Keyboard"


def css(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.CSS, value=value)


def link_name(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.ROLE_NAME, role="link", name=value)


def visible(cid: str, locator: Locator) -> PageCondition:
    return PageCondition(
        condition_id=cid,
        type=PageConditionType.ELEMENT_VISIBLE,
        locator=locator,
    )


def home(*extra: PageCondition) -> PagePrecondition:
    return PagePrecondition(
        (
            PageCondition(
                condition_id="home",
                type=PageConditionType.EXACT_URL,
                url_value=AMAZON,
            ),
            *extra,
        )
    )


def search_page(*extra: PageCondition) -> PagePrecondition:
    return PagePrecondition(
        (
            PageCondition(
                condition_id="origin",
                type=PageConditionType.ORIGIN_EQUALS,
                origin_value=ORIGIN,
            ),
            PageCondition(
                condition_id="path",
                type=PageConditionType.PATH_EQUALS,
                path_value="/s",
            ),
            PageCondition(
                condition_id="query",
                type=PageConditionType.QUERY_PARAM_EQUALS,
                query_name="k",
                query_value=QUERY,
            ),
            *extra,
        )
    )


def product_page(*extra: PageCondition) -> PagePrecondition:
    return PagePrecondition(
        (
            PageCondition(
                condition_id="origin",
                type=PageConditionType.ORIGIN_EQUALS,
                origin_value=ORIGIN,
            ),
            *extra,
        )
    )


def proc_snapshot() -> dict[int, str]:
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    found: dict[int, str] = {}
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) >= 2:
            try:
                found[int(row[1])] = row[0]
            except ValueError:
                pass
    return found


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def inspect(name: str, backend: PlaywrightBackend, locator: Locator) -> dict[str, Any]:
    try:
        value = inspect_target(backend, locator)
    except Exception as exc:
        value = {"error": f"{type(exc).__name__}: {exc}"}
    write_json(RUN / "inspections" / f"{name}.json", value)
    return value


def save_receipt(name: str, receipt: Any) -> None:
    write_json(RUN / "receipts" / f"{name}.json", receipt.to_dict())
    for step in receipt.steps:
        if step.receipt is not None:
            write_json(
                RUN / "receipts" / f"{name}_{step.step_index:02d}_{step.operation_id}.json",
                step.receipt.to_dict(),
            )


def screenshot_config() -> ScreenshotConfig:
    return ScreenshotConfig(
        policy=ScreenshotPolicy.ALWAYS,
        full_page=True,
        max_per_operation=2,
        max_per_plan=20,
        artifact_root=str(RUN / "screenshots"),
        capture_timeout_ms=10_000,
    )


def plan(name: str, config: BrowserConfig, operations: list[Operation]) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id=name,
        browser_config=config,
        screenshot_config=screenshot_config(),
        operations=operations,
        initial_plan_timeout_ms=150_000,
    )


def main() -> int:
    for name in ("screenshots", "receipts", "inspections"):
        (RUN / name).mkdir(parents=True, exist_ok=True)
    before = proc_snapshot()
    write_json(RUN / "processes_before.json", before)
    started = time.monotonic()
    config = BrowserConfig(profile=BrowserProfile.DINGDONG, headless=True)
    backend = PlaywrightBackend(browser_config=config)
    summary: dict[str, Any] = {
        "profile": BrowserProfile.DINGDONG.value,
        "query": QUERY,
        "plans": [],
        "captcha_friction": False,
        "checkout_attempted": False,
        "direct_playwright_input": False,
        "javascript_injection": False,
    }
    search = css("#twotabsearchtextbox")
    results = css("div.s-main-slot")
    first = link_name(FIRST_NAME)
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
    exit_code = 1
    try:
        backend.start()
        search_receipt = execute_plan(
            plan(
                "amazon-benchmark-search",
                config,
                [
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
                        action=Action(
                            type=ActionType.PRESS_KEY, locator=search, key="Enter"
                        ),
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
                ],
            ),
            backend=backend,
        )
        save_receipt("01_search", search_receipt)
        summary["plans"].append(search_receipt.to_dict())
        inspect("01_visible_dp_links", backend, css("a[href*='/dp/']"))
        first_initial = inspect("02_first_identity_initial", backend, first)
        second_initial = inspect("03_second_identity_initial", backend, second)
        captcha_state = inspect("04_captcha_after_search", backend, captcha)
        summary["captcha_friction"] = bool(captcha_state.get("exists"))
        if search_receipt.plan_verdict.value != "VERIFIED" or summary["captcha_friction"]:
            summary["boundary"] = "search_or_captcha"
            return 1
        if first_initial.get("match_count") != 1 or second_initial.get("match_count") != 1:
            summary["boundary"] = "stable_product_identity_not_unique"
            return 1

        first_receipt = execute_plan(
            plan(
                "amazon-benchmark-first-product",
                config,
                [
                    Operation(
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
                    ),
                    Operation(
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
                    ),
                ],
            ),
            backend=backend,
        )
        save_receipt("02_first_product", first_receipt)
        summary["plans"].append(first_receipt.to_dict())
        summary["first_product_url"] = backend.page.url
        inspect("05_first_title", backend, title)
        inspect("06_first_price", backend, price)
        inspect("07_first_rating", backend, rating)
        inspect("08_first_availability", backend, availability)
        inspect("09_captcha_first_product", backend, captcha)
        if first_receipt.plan_verdict.value != "VERIFIED":
            summary["boundary"] = "first_product_verification"
            return 1

        second_receipt = execute_plan(
            plan(
                "amazon-benchmark-second-product",
                config,
                [
                    Operation(
                        operation_id="return-to-results",
                        url=f"{AMAZON}s?k=wireless+mechanical+keyboard",
                        action=Action(type=ActionType.NAVIGATE),
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
                    ),
                    Operation(
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
                    ),
                ],
            ),
            backend=backend,
        )
        save_receipt("03_second_product", second_receipt)
        summary["plans"].append(second_receipt.to_dict())
        summary["second_product_url"] = backend.page.url
        inspect("10_second_title", backend, title)
        inspect("11_second_price", backend, price)
        inspect("12_captcha_second_product", backend, captcha)
        if second_receipt.plan_verdict.value != "VERIFIED":
            summary["boundary"] = "second_product_verification"
            return 1
        summary["result"] = "PASS"
        exit_code = 0
        return exit_code
    except Exception as exc:
        summary["harness_error"] = f"{type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
        return 2
    finally:
        summary["final_url_before_cleanup"] = backend.page.url if backend.is_started else None
        try:
            backend.stop()
        except Exception as exc:
            summary["cleanup_exception"] = f"{type(exc).__name__}: {exc}"
        after = proc_snapshot()
        owned_names = {"chrome.exe", "chromium.exe", "node.exe", "playwright.exe"}
        remaining = [
            {"pid": pid, "image": image}
            for pid, image in after.items()
            if pid not in before and image.lower() in owned_names
        ]
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        summary["cleanup_errors"] = list(backend.cleanup_errors)
        summary["terminal_session_identity"] = backend.terminal_session_identity
        summary["remaining_owned_processes"] = remaining
        summary.setdefault("result", "FAIL")
        write_json(RUN / "processes_after.json", after)
        write_json(RUN / "summary.json", summary)


if __name__ == "__main__":
    raise SystemExit(main())
