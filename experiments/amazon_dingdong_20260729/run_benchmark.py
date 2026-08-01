"""Production Amazon browsing benchmark using only DingDongDitch plans."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from dingdongditch import (
    Action, ActionType, BrowserConfig, BrowserProfile, ConstraintType,
    ExecutionPlan, Expectation, ExpectationType, Locator, LocatorStrategy,
    Operation, ScreenshotConfig, ScreenshotPolicy, TargetConstraint,
    WaitCondition, WaitConditionType, execute_plan, inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import UrlMatchMode

ROOT = Path(__file__).resolve().parent / "run-3"
RECEIPTS, INSPECTIONS, SCREENSHOTS = (
    ROOT / "receipts", ROOT / "inspections", ROOT / "screenshots"
)
for directory in (RECEIPTS, INSPECTIONS, SCREENSHOTS):
    directory.mkdir(parents=True, exist_ok=True)

HOME = "https://www.amazon.com/"
QUERY = "wireless mechanical keyboard"
SEARCH_URL = f"https://www.amazon.com/s?k={quote_plus(QUERY)}"
CONFIG = BrowserConfig(headless=False, profile=BrowserProfile.DINGDONG)
VISIBLE = (TargetConstraint(type=ConstraintType.VISIBLE, visible=True),)

SEARCH = Locator(LocatorStrategy.CSS, "#twotabsearchtextbox", constraints=VISIBLE)
RESULTS = Locator(LocatorStrategy.CSS, "div.s-main-slot", constraints=VISIBLE)
FIRST = Locator(
    LocatorStrategy.CSS,
    "div[data-component-type='s-search-result'][data-index='3'] h2 a",
    constraints=VISIBLE,
)
SCROLL_RESULT = Locator(
    LocatorStrategy.CSS,
    "div[data-component-type='s-search-result'][data-index='6']",
    constraints=VISIBLE,
)
SECOND = Locator(
    LocatorStrategy.CSS,
    "div[data-component-type='s-search-result'][data-index='6'] h2 a",
    constraints=VISIBLE,
)
TITLE = Locator(LocatorStrategy.CSS, "#productTitle", constraints=VISIBLE)
PRICE = Locator(
    LocatorStrategy.CSS,
    "#corePrice_feature_div .a-offscreen, #apex_desktop .a-offscreen",
    constraints=VISIBLE,
)
RATING = Locator(
    LocatorStrategy.CSS, "#acrPopover, span[data-hook='rating-out-of-text']",
    constraints=VISIBLE,
)
AVAILABILITY = Locator(LocatorStrategy.CSS, "#availability", constraints=VISIBLE)
MAIN_IMAGE = Locator(LocatorStrategy.CSS, "#imgTagWrapperId", constraints=VISIBLE)
MODAL = Locator(
    LocatorStrategy.CSS, "#ivLargeImage, .ivImage, #imageBlock_feature_div",
    constraints=VISIBLE,
)

receipts: list[dict[str, Any]] = []
inspections: list[dict[str, Any]] = []
verification_ms: list[float] = []
inspection_ms: list[float] = []
redirects: list[dict[str, Any]] = []


def pids() -> set[tuple[str, int]]:
    output = subprocess.run(
        ["tasklist"], capture_output=True, text=True, check=False
    ).stdout
    found = set()
    for line in output.splitlines():
        match = re.match(r"(chrome|node|python|playwright)\.exe\s+(\d+)", line, re.I)
        if match:
            found.add((match.group(1).lower(), int(match.group(2))))
    return found


def op(
    oid: str, url: str, action: Action,
    expectations: list[Expectation] | None = None, timeout: int = 30_000,
) -> Operation:
    return Operation(
        operation_id=oid, url=url, action=action,
        expectations=expectations or [], timeout_ms=timeout, locate_retry_ms=5_000,
    )


def run(
    backend: PlaywrightBackend, plan_id: str, operations: list[Operation]
) -> Any:
    receipt = execute_plan(
        ExecutionPlan(
            plan_id=plan_id, operations=operations, browser_config=CONFIG,
            initial_plan_timeout_ms=60_000,
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS, full_page=False,
                max_per_operation=1, max_per_plan=max(1, len(operations)),
                artifact_root=str(SCREENSHOTS),
            ),
        ),
        backend=backend,
    )
    data = receipt.to_dict()
    receipts.append(data)
    (RECEIPTS / f"{len(receipts):03d}_{plan_id}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    for step in receipt.steps:
        item = step.receipt
        if item and item.action_completed_at_ms and item.verification_completed_at_ms:
            verification_ms.append(
                item.verification_completed_at_ms - item.action_completed_at_ms
            )
    if receipt.plan_verdict.value != "VERIFIED":
        raise RuntimeError(f"{plan_id}: {receipt.plan_verdict.value}")
    return receipt


def resulting_url(receipt: Any) -> str:
    item = receipt.steps[-1].receipt
    if item is None or item.post_action_observation is None:
        raise RuntimeError("verified operation did not expose its resulting URL")
    return item.post_action_observation.url


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict[str, Any]:
    started = time.perf_counter()
    data = inspect_target(backend, locator)
    latency = (time.perf_counter() - started) * 1000
    inspection_ms.append(latency)
    record = {"label": label, "latency_ms": latency, "data": data}
    inspections.append(record)
    (INSPECTIONS / f"{len(inspections):03d}_{label}.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    return data


def visible_text(data: dict[str, Any]) -> str:
    if data.get("text"):
        return str(data["text"]).strip()
    candidates = data.get("candidates") or data.get("matches") or []
    if not candidates:
        return ""
    item = candidates[0]
    return str(item.get("text") or item.get("inner_text") or "").strip()


def wait_visible(locator: Locator, seconds: int = 30) -> Action:
    return Action(
        type=ActionType.WAIT_FOR,
        wait_condition=WaitCondition(
            type=WaitConditionType.ELEMENT_VISIBLE, locator=locator
        ),
        wait_timeout_ms=seconds * 1000,
    )


def main() -> int:
    before = pids()
    backend = PlaywrightBackend(CONFIG)
    started = time.perf_counter()
    launch = cleanup = 0.0
    status = "FAIL"
    friction: list[str] = []
    product_one: dict[str, str] = {}
    product_two: dict[str, str] = {}
    final_url = None
    visible_prompt = None
    error = None
    try:
        launch_start = time.perf_counter()
        backend.start()
        launch = time.perf_counter() - launch_start

        def response_seen(response: Any) -> None:
            if 300 <= response.status < 400:
                redirects.append({"status": response.status, "url": response.url})

        backend.page.on("response", response_seen)
        run(backend, "open_amazon", [
            op("navigate", HOME, Action(ActionType.NAVIGATE), [
                Expectation(
                    type=ExpectationType.URL, url_value="amazon.",
                    url_match=UrlMatchMode.CONTAINS,
                )
            ], 45_000),
            op("wait-search", HOME, wait_visible(SEARCH, 30)),
        ])
        page_text = inspect(
            backend, "home_friction",
            Locator(LocatorStrategy.CSS, "body", constraints=VISIBLE),
        )
        body = visible_text(page_text).lower()
        for token in ("captcha", "verify you are human", "choose your location"):
            if token in body:
                friction.append(token)

        search_receipt = run(backend, "search", [
            op("fill-query", HOME, Action(ActionType.FILL, SEARCH, QUERY), [
                Expectation(
                    type=ExpectationType.ATTRIBUTE, locator=SEARCH,
                    attribute_name="value", attribute_value=QUERY,
                )
            ]),
            op("submit-query", HOME, Action(
                ActionType.PRESS_KEY, locator=SEARCH, key="Enter"
            ), [
                Expectation(
                    type=ExpectationType.URL, url_value="/s?",
                    url_match=UrlMatchMode.CONTAINS,
                )
            ], 45_000),
        ])
        actual_search_url = resulting_url(search_receipt)
        run(backend, "wait_search_results", [
            op("wait-results", actual_search_url, wait_visible(RESULTS, 30)),
        ])
        run(backend, "scroll_results", [
            op("scroll-sixth-result", actual_search_url, Action(
                ActionType.SCROLL_TO_TARGET, locator=SCROLL_RESULT
            ), [Expectation(
                type=ExpectationType.ELEMENT_VISIBLE, locator=SCROLL_RESULT,
                visible=True,
            )]),
            op("scroll-first-result", actual_search_url, Action(
                ActionType.SCROLL_TO_TARGET, locator=FIRST
            ), [Expectation(
                type=ExpectationType.ELEMENT_VISIBLE, locator=FIRST, visible=True,
            )]),
        ])
        first_open = run(backend, "open_first_product", [
            op("click-first", actual_search_url, Action(ActionType.CLICK, locator=FIRST), [
                Expectation(
                    type=ExpectationType.URL, url_value="/dp/",
                    url_match=UrlMatchMode.CONTAINS,
                )
            ], 45_000),
        ])
        first_product_url = resulting_url(first_open)
        run(backend, "wait_first_product", [
            op("wait-title", first_product_url, wait_visible(TITLE, 30)),
        ])
        for label, locator in (
            ("first_title", TITLE), ("first_price", PRICE),
            ("first_rating", RATING), ("first_availability", AVAILABILITY),
        ):
            product_one[label] = visible_text(inspect(backend, label, locator))
        if not all(product_one.values()):
            raise RuntimeError(f"incomplete first product data: {product_one}")

        run(backend, "open_gallery", [
            op("click-main-image", first_product_url, Action(ActionType.CLICK, locator=MAIN_IMAGE)),
            op("wait-gallery", first_product_url, wait_visible(MODAL, 20)),
        ])
        for number in (2, 3, 4):
            thumb = Locator(
                LocatorStrategy.CSS,
                f".ivThumb:nth-of-type({number}), #altImages li:nth-of-type({number}) input",
                constraints=VISIBLE,
            )
            run(backend, f"gallery_image_{number}", [
                op(
                    f"click-gallery-{number}", first_product_url,
                    Action(ActionType.CLICK, locator=thumb),
                    [Expectation(
                        type=ExpectationType.ELEMENT_VISIBLE, locator=MODAL,
                        visible=True,
                    )],
                )
            ])

        run(backend, "return_results", [
            op("navigate-results", SEARCH_URL, Action(ActionType.NAVIGATE), [
                Expectation(
                    type=ExpectationType.URL, url_value="/s?",
                    url_match=UrlMatchMode.CONTAINS,
                )
            ], 45_000),
            op("wait-second", SEARCH_URL, wait_visible(SECOND, 30)),
        ])
        second_open = run(backend, "open_second_product", [
            op("scroll-second", SEARCH_URL, Action(
                ActionType.SCROLL_TO_TARGET, locator=SECOND
            ), [Expectation(
                type=ExpectationType.ELEMENT_VISIBLE, locator=SECOND, visible=True,
            )]),
            op("click-second", SEARCH_URL, Action(ActionType.CLICK, locator=SECOND), [
                Expectation(
                    type=ExpectationType.URL, url_value="/dp/",
                    url_match=UrlMatchMode.CONTAINS,
                )
            ], 45_000),
        ])
        second_product_url = resulting_url(second_open)
        run(backend, "wait_second_product", [
            op("wait-second-title", second_product_url, wait_visible(TITLE, 30)),
        ])
        product_two["title"] = visible_text(inspect(backend, "second_title", TITLE))
        product_two["price"] = visible_text(inspect(backend, "second_price", PRICE))
        if not all(product_two.values()):
            raise RuntimeError(f"incomplete second product data: {product_two}")
        status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        try:
            challenge = inspect(
                backend, "terminal_page",
                Locator(LocatorStrategy.CSS, "body", constraints=VISIBLE),
            )
            final_url = (challenge.get("page") or {}).get("url")
            visible_prompt = visible_text(challenge)
            if final_url and "/errors/validateCaptcha" in final_url:
                friction.append("Amazon validation challenge")
        except Exception as inspection_exc:
            friction.append(
                f"terminal inspection unavailable: {type(inspection_exc).__name__}"
            )
    finally:
        cleanup_start = time.perf_counter()
        try:
            backend.stop()
        finally:
            cleanup = time.perf_counter() - cleanup_start

    remaining = sorted(pids() - before)
    if remaining:
        status = "FAIL"
        error = error or f"owned processes remain: {remaining}"
    report = {
        "status": status,
        "error": error,
        "browser_profile": BrowserProfile.DINGDONG.value,
        "total_execution_seconds": time.perf_counter() - started,
        "browser_launch_seconds": launch,
        "cleanup_seconds": cleanup,
        "average_verification_latency_ms": (
            sum(verification_ms) / len(verification_ms) if verification_ms else None
        ),
        "average_inspection_latency_ms": (
            sum(inspection_ms) / len(inspection_ms) if inspection_ms else None
        ),
        "receipt_count": len(receipts),
        "inspection_count": len(inspections),
        "screenshot_count": len(list(SCREENSHOTS.glob("*.png"))),
        "redirects": redirects,
        "final_url": final_url,
        "visible_prompt": visible_prompt,
        "friction": friction,
        "first_product": product_one,
        "second_product": product_two,
        "remaining_owned_processes": remaining,
    }
    (ROOT / "benchmark_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
