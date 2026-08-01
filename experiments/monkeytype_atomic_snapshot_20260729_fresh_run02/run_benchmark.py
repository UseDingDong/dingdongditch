"""Single fresh production Monkeytype benchmark through DingDongDitch only."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

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
    Operation,
    ScreenshotConfig,
    ScreenshotPolicy,
    WaitCondition,
    WaitConditionType,
    execute_plan,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.modes import UrlMatchMode


ROOT = Path(__file__).resolve().parent
RECEIPTS = ROOT / "receipts"
SCREENSHOTS = ROOT / "screenshots"
INSPECTIONS = ROOT / "inspections"
LOGS = ROOT / "logs"
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS):
    directory.mkdir(parents=True, exist_ok=False)

MONKEYTYPE_URL = "https://monkeytype.com/"
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
SCREENSHOT = ScreenshotConfig(
    policy=ScreenshotPolicy.ALWAYS,
    artifact_root=str(SCREENSHOTS),
)
NO_SUCCESS_SCREENSHOT = ScreenshotConfig(
    policy=ScreenshotPolicy.ON_FAILURE,
    artifact_root=str(SCREENSHOTS),
)

events: list[dict[str, Any]] = []
receipt_index = 0
inspection_index = 0
verified_key_presses = 0
incorrect_dispatched_keys = 0
backspaces_dispatched = 0


def save(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def log(event: str, **detail: Any) -> None:
    events.append(
        {"at_unix_ms": int(time.time() * 1000), "event": event, **detail}
    )
    save(LOGS / "run_history.json", events)


def url_expectation() -> list[Expectation]:
    return [
        Expectation(
            type=ExpectationType.URL,
            url_value="monkeytype.com",
            url_match=UrlMatchMode.CONTAINS,
        )
    ]


def run_plan(
    backend: PlaywrightBackend,
    plan_id: str,
    operations: list[Operation],
    *,
    screenshot: bool = False,
):
    global receipt_index
    receipt_index += 1
    started = time.perf_counter_ns()
    result = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=operations,
            browser_config=CONFIG,
            screenshot_config=SCREENSHOT if screenshot else NO_SUCCESS_SCREENSHOT,
            initial_plan_timeout_ms=30_000,
            max_plan_timeout_ms=30_000,
        ),
        backend=backend,
    )
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    path = RECEIPTS / f"{receipt_index:04d}_{plan_id}.json"
    save(path, result.to_dict())
    log(
        "plan",
        plan_id=plan_id,
        verdict=result.plan_verdict.value,
        completion=result.completion_status.value,
        duration_ms=duration_ms,
        receipt=str(path),
    )
    return result


def inspect(
    backend: PlaywrightBackend, label: str, locator: Locator
) -> dict[str, Any]:
    global inspection_index
    inspection_index += 1
    started = time.perf_counter_ns()
    result = inspect_target(backend, locator)
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    path = INSPECTIONS / f"{inspection_index:04d}_{label}.json"
    save(path, result)
    log(
        "inspection",
        label=label,
        match_count=result.get("match_count"),
        visible=result.get("visible"),
        duration_ms=duration_ms,
        artifact=str(path),
    )
    return result


def css(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.CSS, value=value)


def wait_visible(
    backend: PlaywrightBackend,
    runtime_url: str,
    plan_id: str,
    selector: str,
    *,
    screenshot: bool,
    timeout_ms: int = 20_000,
):
    return run_plan(
        backend,
        plan_id,
        [
            Operation(
                operation_id=plan_id,
                url=runtime_url,
                timeout_ms=timeout_ms,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=timeout_ms,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.ELEMENT_VISIBLE,
                        locator=css(selector),
                    ),
                ),
                expectations=url_expectation(),
            )
        ],
        screenshot=screenshot,
    )


def click_if_visible(
    backend: PlaywrightBackend,
    runtime_url: str,
    label: str,
    candidates: list[Locator],
) -> bool:
    for index, locator in enumerate(candidates, 1):
        state = inspect(backend, f"{label}_candidate_{index}", locator)
        if state.get("match_count") != 1 or state.get("visible") is not True:
            continue
        result = run_plan(
            backend,
            label,
            [
                Operation(
                    operation_id=label,
                    url=runtime_url,
                    action=Action(type=ActionType.CLICK, locator=locator),
                    expectations=url_expectation(),
                )
            ],
            screenshot=True,
        )
        if result.plan_verdict.value != "VERIFIED":
            raise RuntimeError(f"{label} click failed")
        return True
    return False


def screenshot_milestone(
    backend: PlaywrightBackend, runtime_url: str, label: str
) -> None:
    result = run_plan(
        backend,
        label,
        [
            Operation(
                operation_id=label,
                url=runtime_url,
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_timeout_ms=1_000,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.URL_MATCHES,
                        url_value="monkeytype.com",
                        url_match=UrlMatchMode.CONTAINS,
                    ),
                ),
                expectations=url_expectation(),
            )
        ],
        screenshot=True,
    )
    if result.plan_verdict.value != "VERIFIED":
        raise RuntimeError(f"milestone screenshot failed: {label}")


def type_word(
    backend: PlaywrightBackend,
    runtime_url: str,
    word_index: int,
    word: str,
) -> int:
    global verified_key_presses, backspaces_dispatched
    keys = list(word) + ["Space"]
    operations = []
    for key_index, key in enumerate(keys, 1):
        if key == "Backspace":
            backspaces_dispatched += 1
        operations.append(
            Operation(
                operation_id=f"word-{word_index:04d}-key-{key_index:03d}",
                url=runtime_url,
                timeout_ms=5_000,
                action=Action(
                    type=ActionType.PRESS_KEY,
                    key=key,
                    key_scope=KeyPressScope.ACTIVE_PAGE,
                ),
                expectations=url_expectation(),
            )
        )
    result = run_plan(
        backend,
        f"type_word_{word_index:04d}",
        operations,
        screenshot=False,
    )
    if result.plan_verdict.value != "VERIFIED":
        raise RuntimeError(
            f"typing plan failed at word {word_index}: "
            f"{result.plan_verdict.value}/{result.failure_kind}"
        )
    verified = sum(
        1
        for step in result.steps
        if step.attempted and step.operation_verdict == "VERIFIED"
    )
    if verified != len(keys):
        raise RuntimeError(
            f"only {verified}/{len(keys)} key operations verified "
            f"for word {word_index}"
        )
    verified_key_presses += verified
    return verified


def result_is_visible(backend: PlaywrightBackend, word_index: int) -> bool:
    state = inspect(backend, f"result_probe_{word_index:04d}", css("#result"))
    return state.get("match_count") == 1 and state.get("visible") is True


def parse_result(text: str) -> dict[str, Any]:
    normalized = "\n".join(
        line.strip() for line in text.splitlines() if line.strip()
    )

    def number_after(label: str) -> float | None:
        match = re.search(
            rf"(?:^|\n){re.escape(label)}\s*\n?([0-9]+(?:\.[0-9]+)?)%?",
            normalized,
            re.IGNORECASE,
        )
        return float(match.group(1)) if match else None

    wpm = number_after("wpm")
    accuracy = number_after("acc")
    characters = None
    char_match = re.search(
        r"(?:^|\n)characters\s*\n?([0-9]+)\s*/\s*([0-9]+)"
        r"\s*/\s*([0-9]+)\s*/\s*([0-9]+)",
        normalized,
        re.IGNORECASE,
    )
    if char_match:
        characters = [int(value) for value in char_match.groups()]
    return {
        "wpm": wpm,
        "accuracy_percent": accuracy,
        "characters": characters,
        "normalized_result_text": normalized,
    }


def remaining_playwright_processes() -> list[dict[str, Any]]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match "
        "'^(chrome|chromium|firefox|webkit|playwright|node)\\\\.exe$' "
        "-and $_.CommandLine -match "
        "'playwright|ms-playwright|playwright_chromiumdev_profile' } | "
        "Select-Object ProcessId,Name,ParentProcessId,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        return [{"process_check_error": completed.stderr.strip()}]
    raw = completed.stdout.strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, list) else [parsed]


def main() -> int:
    benchmark_started_ns = time.perf_counter_ns()
    backend = PlaywrightBackend(CONFIG)
    launch_ms = None
    cleanup_ms = None
    runtime_url = MONKEYTYPE_URL
    status = "FAIL"
    error = None
    final_parsed: dict[str, Any] = {}
    words_typed = 0
    typing_started_ns = None
    typing_finished_ns = None
    terminal_environment = None
    try:
        launch_started = time.perf_counter_ns()
        backend.start()
        launch_ms = (time.perf_counter_ns() - launch_started) / 1_000_000
        log(
            "browser_started",
            launch_ms=launch_ms,
            browser=backend.browser_environment(),
        )

        navigation = run_plan(
            backend,
            "navigate_monkeytype",
            [
                Operation(
                    operation_id="navigate-monkeytype",
                    url=MONKEYTYPE_URL,
                    timeout_ms=30_000,
                    action=Action(type=ActionType.NAVIGATE),
                    expectations=url_expectation(),
                )
            ],
            screenshot=True,
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Monkeytype navigation was not verified")
        runtime_url = (
            navigation.steps[0].receipt.dispatch_document_url or MONKEYTYPE_URL
        )

        wait_visible(
            backend,
            runtime_url,
            "wait_initial_words",
            "#words",
            screenshot=True,
            timeout_ms=30_000,
        )

        consent_clicked = click_if_visible(
            backend,
            runtime_url,
            "accept_cookie_consent",
            [
                Locator(
                    strategy=LocatorStrategy.ROLE_NAME,
                    role="button",
                    name="Accept all",
                ),
                css("#acceptCookies"),
                css("[data-testid='cookie-accept']"),
            ],
        )
        log("consent_complete", clicked=consent_clicked)

        focus = run_plan(
            backend,
            "focus_monkeytype",
            [
                Operation(
                    operation_id="focus-monkeytype",
                    url=runtime_url,
                    action=Action(
                        type=ActionType.PRESS_KEY,
                        key="Shift",
                        key_scope=KeyPressScope.ACTIVE_PAGE,
                    ),
                    expectations=url_expectation(),
                )
            ],
            screenshot=True,
        )
        if focus.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Monkeytype focus operation was not verified")

        selected_60 = inspect(
            backend,
            "time_60_selected",
            css("[timeconfig='60'].active"),
        )
        if not (
            selected_60.get("match_count") == 1
            and selected_60.get("visible") is True
        ):
            changed = click_if_visible(
                backend,
                runtime_url,
                "select_60_seconds",
                [
                    Locator(
                        strategy=LocatorStrategy.ROLE_NAME,
                        role="button",
                        name="60",
                    ),
                    css("[timeconfig='60']"),
                    css("[data-time='60']"),
                ],
            )
            if not changed:
                raise RuntimeError("60-second test control was not uniquely visible")

        wait_visible(
            backend,
            runtime_url,
            "typing_test_ready",
            ".word.active",
            screenshot=True,
            timeout_ms=20_000,
        )
        ready = inspect(backend, "ready_active_word", css(".word.active"))
        if ready.get("match_count") != 1 or not (ready.get("text") or "").strip():
            raise RuntimeError("typing test did not expose one active word")

        typing_started_ns = time.perf_counter_ns()
        deadline_ns = typing_started_ns + 80_000_000_000
        while time.perf_counter_ns() < deadline_ns:
            if result_is_visible(backend, words_typed):
                typing_finished_ns = time.perf_counter_ns()
                break
            active = inspect(
                backend,
                f"active_word_{words_typed + 1:04d}",
                css(".word.active"),
            )
            word = (active.get("text") or "").strip()
            if active.get("match_count") != 1 or not word:
                if result_is_visible(backend, words_typed):
                    typing_finished_ns = time.perf_counter_ns()
                    break
                raise RuntimeError(
                    f"active word unavailable after {words_typed} words"
                )
            words_typed += 1
            type_word(backend, runtime_url, words_typed, word)
            if words_typed % 25 == 0:
                screenshot_milestone(
                    backend, runtime_url, f"typing_milestone_{words_typed:04d}"
                )
        else:
            raise RuntimeError("results did not appear within 80 seconds")

        final_wait = wait_visible(
            backend,
            runtime_url,
            "wait_final_results",
            "#result",
            screenshot=True,
            timeout_ms=10_000,
        )
        if final_wait.plan_verdict.value != "VERIFIED":
            raise RuntimeError("final result screen was not verified")
        final_result = inspect(backend, "final_result", css("#result"))
        final_body = inspect(backend, "final_body", css("body"))
        final_text = (final_result.get("text") or "").strip()
        if not final_text:
            final_text = (final_body.get("text") or "").strip()
        final_parsed = parse_result(final_text)
        if final_parsed.get("wpm") is None or final_parsed.get(
            "accuracy_percent"
        ) is None:
            raise RuntimeError("WPM or accuracy could not be parsed from results")
        status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log("benchmark_failed", error=error)
    finally:
        terminal_environment = backend.browser_environment()
        cleanup_started = time.perf_counter_ns()
        backend.stop()
        cleanup_ms = (time.perf_counter_ns() - cleanup_started) / 1_000_000
        log(
            "browser_stopped",
            cleanup_ms=cleanup_ms,
            cleanup_errors=list(backend.cleanup_errors),
            lifecycle_state=backend.lifecycle_state.value,
        )

    remaining = remaining_playwright_processes()
    total_ms = (time.perf_counter_ns() - benchmark_started_ns) / 1_000_000
    screenshots = sorted(path.as_posix() for path in SCREENSHOTS.glob("*.png"))
    receipts = sorted(path.as_posix() for path in RECEIPTS.glob("*.json"))
    inspections = sorted(path.as_posix() for path in INSPECTIONS.glob("*.json"))
    characters = final_parsed.get("characters")
    correct = characters[0] if characters else None
    incorrect = characters[1] if characters else None
    extras = characters[2] if characters else None
    missed = characters[3] if characters else None
    result = {
        "verdict": status,
        "error": error,
        "fresh_run": True,
        "runtime_version": "current production checkout",
        "browser": CONFIG.describe(),
        "wpm": final_parsed.get("wpm"),
        "accuracy_percent": final_parsed.get("accuracy_percent"),
        "correct_key_presses": correct,
        "incorrect_key_presses": incorrect,
        "extra_key_presses": extras,
        "missed_key_presses": missed,
        "corrections_backspaces_reported": None,
        "backspaces_dispatched": backspaces_dispatched,
        "verified_key_operations": verified_key_presses,
        "words_typed": words_typed,
        "typing_duration_ms": (
            (typing_finished_ns - typing_started_ns) / 1_000_000
            if typing_started_ns is not None and typing_finished_ns is not None
            else None
        ),
        "total_execution_duration_ms": total_ms,
        "browser_launch_ms": launch_ms,
        "browser_cleanup_ms": cleanup_ms,
        "screenshot_count": len(screenshots),
        "receipt_file_count": len(receipts),
        "inspection_count": len(inspections),
        "cleanup_status": {
            "lifecycle_state": backend.lifecycle_state.value,
            "errors": list(backend.cleanup_errors),
            "terminal_environment_before_stop": terminal_environment,
        },
        "remaining_owned_process_count": len(remaining),
        "remaining_owned_processes": remaining,
        "atomic_snapshot_count": backend._atomic_snapshot_count,
        "atomic_snapshot_fallback_count": backend._atomic_snapshot_fallback_count,
        "result_text": final_parsed.get("normalized_result_text"),
        "screenshots": screenshots,
        "receipts": receipts,
        "inspections": inspections,
    }
    save(ROOT / "benchmark_results.json", result)
    save(ROOT / "terminal_browser.json", result["cleanup_status"])
    print(json.dumps({"verdict": status, "error": error, "result": result}))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
