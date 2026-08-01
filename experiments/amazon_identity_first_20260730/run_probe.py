"""Fresh Amazon reconnaissance using DingDongDitch ExecutionPlans only."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserConfig, BrowserProfile
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import UrlMatchMode
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.contract.wait import LoadState, WaitCondition, WaitConditionType
from dingdongditch.inspection import inspect_target
from dingdongditch.runtime.plan_executor import execute_plan

ROOT = Path(__file__).resolve().parent
AMAZON = "https://www.amazon.com/"
QUERY = "wireless mechanical keyboard"


def css(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.CSS, value=value)


def snapshot_processes(path: Path) -> None:
    result = subprocess.run(["tasklist"], capture_output=True, text=True, check=False)
    path.write_text(result.stdout + result.stderr, encoding="utf-8")


def main() -> int:
    for name in ("screenshots", "receipts", "inspections"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    snapshot_processes(ROOT / "processes_before.txt")
    config = BrowserConfig(profile=BrowserProfile.DINGDONG, headless=True)
    screenshot = ScreenshotConfig(
        policy=ScreenshotPolicy.ALWAYS,
        full_page=True,
        max_per_operation=2,
        max_per_plan=12,
        artifact_root=str(ROOT / "screenshots"),
        capture_timeout_ms=10_000,
    )
    search = css("#twotabsearchtextbox")
    results = css("div.s-main-slot")
    plan = ExecutionPlan(
        plan_id="amazon-dingdong-reconnaissance-20260730",
        browser_config=config,
        screenshot_config=screenshot,
        initial_plan_timeout_ms=120_000,
        operations=[
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
                operation_id="fill-query",
                url=AMAZON,
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
                operation_id="submit-query",
                url=AMAZON,
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
            Operation(
                operation_id="wait-results-network-idle",
                url=AMAZON,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.LOAD_STATE,
                        load_state=LoadState.LOAD,
                    ),
                    wait_timeout_ms=20_000,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="/s?",
                        url_match=UrlMatchMode.CONTAINS,
                    )
                ],
                timeout_ms=25_000,
            ),
        ],
    )
    started = time.monotonic()
    backend = PlaywrightBackend(browser_config=config)
    outcome: dict[str, object] = {}
    try:
        backend.start()
        receipt = execute_plan(plan, backend=backend)
        (ROOT / "receipts" / "probe.json").write_text(
            json.dumps(receipt.to_dict(), indent=2), encoding="utf-8"
        )
        selectors = {
            "search": search,
            "results": results,
            "captcha": css(
                "form[action*='validateCaptcha'], #captchacharacters, "
                "input[name='cvf_captcha_input']"
            ),
            "waf": css("text=/sorry|robot|captcha|challenge/i"),
            "product_links": css(
                "a[href*='/dp/']"
            ),
        }
        for name, locator in selectors.items():
            try:
                data = inspect_target(backend, locator)
            except Exception as exc:
                data = {"error": f"{type(exc).__name__}: {exc}"}
            (ROOT / "inspections" / f"{name}.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        outcome = {
            "verdict": receipt.plan_verdict.value,
            "completion": receipt.completion_status.value,
            "decisive_operation": receipt.decisive_operation_id,
            "failure_kind": receipt.failure_kind,
            "final_url": backend.page.url,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        return 0 if receipt.plan_verdict.value == "VERIFIED" else 1
    finally:
        try:
            backend.stop()
        finally:
            outcome["cleanup_errors"] = list(backend.cleanup_errors)
            outcome["terminal_session_identity"] = backend.terminal_session_identity
            (ROOT / "probe_summary.json").write_text(
                json.dumps(outcome, indent=2), encoding="utf-8"
            )
            snapshot_processes(ROOT / "processes_after.txt")


if __name__ == "__main__":
    raise SystemExit(main())
