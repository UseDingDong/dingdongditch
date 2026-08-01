"""Fresh headed Monkeytype benchmark through DingDongDitch only."""
from __future__ import annotations

import json
import re
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
    KeyPressScope,
    Locator,
    LocatorStrategy,
    NameMatchMode,
    Operation,
    ScreenshotConfig,
    ScreenshotPolicy,
    Verdict,
    execute_plan,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


ROOT = Path(__file__).resolve().parent
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
events: list[dict] = []
receipt_index = 0
inspection_index = 0


def save(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **detail: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **detail})
    save(LOGS / "run_history.json", events)


def run_plan(
    backend: PlaywrightBackend,
    plan_id: str,
    operations: list[Operation],
    *,
    screenshots: bool = False,
    timeout_ms: int = 120_000,
):
    global receipt_index
    receipt_index += 1
    plan = ExecutionPlan(
        plan_id=plan_id,
        operations=operations,
        browser_config=CONFIG,
        screenshot_config=ScreenshotConfig(
            policy=(
                ScreenshotPolicy.ALWAYS
                if screenshots else ScreenshotPolicy.ON_FAILURE
            ),
            artifact_root=str(SCREENSHOTS),
        ),
        initial_plan_timeout_ms=timeout_ms,
        max_plan_timeout_ms=timeout_ms,
    )
    receipt = execute_plan(plan, backend=backend)
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


def inspect(backend: PlaywrightBackend, label: str, selector: str) -> dict:
    global inspection_index
    inspection_index += 1
    result = inspect_target(
        backend, Locator(strategy=LocatorStrategy.CSS, value=selector)
    )
    path = INSPECTIONS / f"{inspection_index:03d}_{label}.json"
    save(path, result)
    log(
        "inspection",
        label=label,
        selector=selector,
        matches=result.get("match_count"),
        text=(result.get("text") or "")[:500],
        artifact=str(path),
    )
    return result


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    final_status = "runtime_failure"
    try:
        backend.start()
        log("browser_started", browser=backend.browser_environment())
        nav = run_plan(
            backend,
            "navigate_monkeytype",
            [
                Operation(
                    operation_id="navigate",
                    url="https://monkeytype.com/",
                    action=Action(type=ActionType.NAVIGATE),
                    expectations=[
                        Expectation(
                            type=ExpectationType.URL,
                            url_value="https://monkeytype.com/",
                        )
                    ],
                )
            ],
            screenshots=True,
        )
        if nav.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Monkeytype navigation was not verified")

        body = inspect(backend, "initial_body", "body")
        body_text = body.get("text") or ""
        if "accept all" in body_text.lower():
            consent = run_plan(
                backend,
                "accept_cookie_consent",
                [
                    Operation(
                        operation_id="accept-consent",
                        url="https://monkeytype.com/",
                        action=Action(
                            type=ActionType.CLICK,
                            locator=Locator(
                                strategy=LocatorStrategy.ROLE_NAME,
                                role="button",
                                name="accept all",
                                name_match=NameMatchMode.EXACT,
                            ),
                        ),
                    )
                ],
            )
            if not consent.steps[0].receipt.action_executed_successfully:
                raise RuntimeError("cookie consent could not be dismissed")

        choose = run_plan(
            backend,
            "select_60_seconds",
            [
                Operation(
                    operation_id="select-60",
                    url="https://monkeytype.com/",
                    action=Action(
                        type=ActionType.CLICK,
                        locator=Locator(
                            strategy=LocatorStrategy.ROLE_NAME,
                            role="button",
                            name="60",
                            name_match=NameMatchMode.EXACT,
                        ),
                    ),
                )
            ],
            screenshots=True,
        )
        if not choose.steps[0].receipt.action_executed_successfully:
            raise RuntimeError("visible 60-second control was not selected")

        words_state = inspect(backend, "rendered_words", "#words")
        words = re.findall(r"[A-Za-z]+", words_state.get("text") or "")
        if len(words) < 30:
            raise RuntimeError(f"insufficient rendered English words: {len(words)}")
        operations: list[Operation] = []
        ordinal = 0
        for word in words:
            for character in word:
                ordinal += 1
                operations.append(
                    Operation(
                        operation_id=f"key-{ordinal:04d}",
                        url="https://monkeytype.com/",
                        action=Action(
                            type=ActionType.PRESS_KEY,
                            key=character.lower(),
                            key_scope=KeyPressScope.ACTIVE_PAGE,
                        ),
                        expectations=[
                            Expectation(
                                type=ExpectationType.URL,
                                url_value="https://monkeytype.com/",
                            )
                        ],
                        timeout_ms=5_000,
                    )
                )
            ordinal += 1
            operations.append(
                Operation(
                    operation_id=f"key-{ordinal:04d}",
                    url="https://monkeytype.com/",
                    action=Action(
                        type=ActionType.PRESS_KEY,
                        key="Space",
                        key_scope=KeyPressScope.ACTIVE_PAGE,
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.URL,
                            url_value="https://monkeytype.com/",
                        )
                    ],
                    timeout_ms=5_000,
                )
            )
        log("typing_plan_built", rendered_words=len(words), declared_keys=len(operations))
        typing = run_plan(
            backend,
            "type_rendered_english_words",
            operations,
            timeout_ms=180_000,
        )
        log(
            "typing_plan_finished",
            verdict=typing.plan_verdict.value,
            completion=typing.completion_status.value,
        )

        result_wait = run_plan(
            backend,
            "wait_for_official_result",
            [
                Operation(
                    operation_id="wait-result",
                    url="https://monkeytype.com/",
                    action=Action(
                        type=ActionType.WAIT_FOR,
                        wait_timeout_ms=60_000,
                        wait_condition=__import__(
                            "dingdongditch.contract.wait", fromlist=["WaitCondition"]
                        ).WaitCondition(
                            type=__import__(
                                "dingdongditch.contract.wait",
                                fromlist=["WaitConditionType"],
                            ).WaitConditionType.ELEMENT_VISIBLE,
                            locator=Locator(
                                strategy=LocatorStrategy.CSS, value="#result"
                            ),
                        ),
                    ),
                    timeout_ms=60_000,
                )
            ],
            screenshots=True,
            timeout_ms=65_000,
        )
        if result_wait.plan_verdict.value != "VERIFIED":
            raise RuntimeError("official result UI did not become visible")
        result = inspect(backend, "official_result", "#result")
        body_result = inspect(backend, "result_body", "body")
        save(
            ROOT / "run_result.json",
            {
                "status": "completed",
                "rendered_words": len(words),
                "declared_keys": len(operations),
                "official_result_text": result.get("text"),
                "body_text": body_result.get("text"),
                "browser": backend.browser_environment(),
            },
        )
        final_status = "completed"
        return 0
    except Exception as exc:
        log("benchmark_error", error=f"{type(exc).__name__}: {exc}")
        save(ROOT / "run_result.json", {"status": final_status, "error": str(exc)})
        return 1
    finally:
        before = backend.browser_environment()
        backend.stop()
        after = backend.browser_environment()
        save(
            ROOT / "terminal_browser.json",
            {"status": final_status, "before_stop": before, "after_stop": after},
        )
        log("browser_stopped", status=final_status, cleanup_errors=after.get("cleanup_errors"))


if __name__ == "__main__":
    raise SystemExit(main())
