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
    BrowserProfile,
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
    TypingSession,
    TypingSessionConfig,
    execute_operation,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import dingdong_profile_directory
from dingdongditch.contract.expectation import UrlMatchMode


URL = "https://monkeytype.com/"
ARTIFACTS = Path("artifacts/monkeytype_challenge").resolve()


def op(
    operation_id: str,
    action: Action,
    *,
    screenshots: bool = False,
    expectations: list[Expectation] | None = None,
) -> Operation:
    return Operation(
        operation_id=operation_id,
        url=URL,
        action=action,
        expectations=expectations or [],
        timeout_ms=30_000,
        screenshot_config=ScreenshotConfig(
            policy=ScreenshotPolicy.AFTER_SUCCESS if screenshots else ScreenshotPolicy.NEVER,
            artifact_root=str(ARTIFACTS),
            full_page=True,
        ),
    )


def main() -> int:
    wall_started = time.perf_counter()
    config = BrowserConfig(
        engine=BrowserEngine.CHROMIUM,
        channel=BrowserChannel.BUNDLED,
        headless=False,
        profile=BrowserProfile.DINGDONG,
    )
    config.validate()
    backend = PlaywrightBackend(config)
    recovery: list[str] = []
    result: dict[str, object] = {
        "challenge_result": "FAILED",
        "effective_browser_profile": None,
        "wpm": None,
        "accuracy": None,
        "typing_session_used": False,
        "characters_safely_typed": 0,
        "session_checkpoints": [],
        "safe_stop_event": None,
        "errors": [],
        "test_errors": None,
        "page_observations": 0,
        "input_completion_status": "NOT_STARTED",
        "test_completion_status": "NOT_COMPLETED",
        "active_typing_time_seconds": 0.0,
        "waiting_time_after_input_exhaustion_seconds": 0.0,
        "artificial_key_delay_used": False,
        "monkeytype_mode_confirmed": None,
        "word_count_completed": None,
        "recovery_actions": recovery,
    }
    try:
        backend.start()
        environment = backend.browser_environment()
        effective_profile = backend.browser_config.profile.value
        profile_confirmation = {
            **environment,
            "profile": effective_profile,
            "persistent_profile_directory": str(dingdong_profile_directory()),
        }
        result["effective_browser_profile"] = effective_profile
        print("PROFILE_CONFIRMATION=" + json.dumps(profile_confirmation, sort_keys=True), flush=True)
        if effective_profile != BrowserProfile.DINGDONG.value:
            raise RuntimeError(f"effective profile is not dingdong: {profile_confirmation!r}")
        if environment.get("headless") is not False:
            raise RuntimeError(f"browser is not headed: {environment!r}")

        nav = execute_operation(
            op(
                "navigate-monkeytype",
                Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="monkeytype.com",
                        url_match=UrlMatchMode.CONTAINS,
                    )
                ],
            ),
            backend=backend,
            browser_config=config,
        )
        if nav.execution_error is not None:
            raise RuntimeError(f"navigation failed: {nav.execution_error}")

        body_locator = Locator(strategy=LocatorStrategy.CSS, value="body")
        startup_text = (inspect_target(backend, body_locator).get("text") or "")
        if re.search(r"\bwpm\s*[\r\n ]+\d+", startup_text, re.I):
            restart_locator = Locator(
                LocatorStrategy.CSS, value="[aria-label='Restart Test']"
            )
            restart_state = inspect_target(backend, restart_locator)
            if restart_state.get("match_count") != 1:
                raise RuntimeError(
                    f"persisted results detected but restart control unavailable: {restart_state!r}"
                )
            restart_receipt = execute_operation(
                op(
                    "restart-from-results",
                    Action(ActionType.CLICK, locator=restart_locator),
                ),
                backend=backend,
                browser_config=config,
            )
            if restart_receipt.execution_error is not None:
                raise RuntimeError(
                    f"could not restart persisted result: {restart_receipt.execution_error}"
                )
            recovery.append("returned from persisted results via Restart Test")

        words_mode_locator = Locator(
            LocatorStrategy.ROLE_NAME,
            role="button",
            name="words",
            name_match=NameMatchMode.EXACT,
        )
        words_mode_state = {}
        for _ in range(40):
            words_mode_state = inspect_target(backend, words_mode_locator)
            if words_mode_state.get("match_count") == 1:
                break
            time.sleep(0.25)
        if words_mode_state.get("match_count") != 1:
            raise RuntimeError(
                f"Words mode control unavailable: {words_mode_state!r}"
            )
        words_mode_receipt = execute_operation(
            op(
                "select-words-mode",
                Action(ActionType.CLICK, locator=words_mode_locator),
            ),
            backend=backend,
            browser_config=config,
        )
        if words_mode_receipt.execution_error is not None:
            raise RuntimeError(
                f"could not select Words mode: {words_mode_receipt.execution_error}"
            )
        result["monkeytype_mode_confirmed"] = "words"
        recovery.append("selected Words mode via accessible button")

        words_locator = Locator(strategy=LocatorStrategy.CSS, value="#words")
        words_text = ""
        for _ in range(30):
            state = inspect_target(backend, words_locator)
            words_text = (state.get("text") or "").strip()
            if state.get("visible") and len(words_text.split()) >= 10:
                break
            time.sleep(0.25)
        if not words_text:
            body = inspect_target(
                backend, Locator(strategy=LocatorStrategy.CSS, value="body")
            )
            raise RuntimeError(f"typing test did not load; body={body.get('text')!r}")

        # Monkeytype's word container can include the whole generated queue.
        # Whitespace normalization preserves the displayed word order.
        words = re.findall(r"[A-Za-z]+", words_text)
        if len(words) < 10:
            raise RuntimeError(f"could not extract displayed words: {words_text!r}")
        phrase = " ".join(words) + " "
        print(f"DISPLAYED_WORD_COUNT={len(words)}", flush=True)

        focus_state = backend.read_page_focus_state()
        active = focus_state.get("active_element") or {}
        intended_focused = (
            (
                active.get("tag") == "textarea"
                and active.get("id") == "wordsInput"
            )
            or (
                active.get("tag") not in {"input", "textarea", "select"}
                and active.get("contenteditable") is not True
            )
        )
        if not intended_focused:
            close_candidates = (
                "[aria-label*='close' i]",
                "button[title*='close' i]",
                ".modal .close",
            )
            closed = False
            for close_index, selector in enumerate(close_candidates):
                close_locator = Locator(
                    strategy=LocatorStrategy.CSS, value=selector
                )
                close_state = inspect_target(backend, close_locator)
                if (
                    close_state.get("match_count") == 1
                    and close_state.get("visible") is True
                ):
                    close_receipt = execute_operation(
                        op(
                            f"close-overlay-{close_index}",
                            Action(type=ActionType.CLICK, locator=close_locator),
                        ),
                        backend=backend,
                        browser_config=config,
                    )
                    if close_receipt.execution_error is None:
                        closed = True
                        recovery.append(f"closed overlay via {selector}")
                        break
            focus_state = backend.read_page_focus_state()
            active = focus_state.get("active_element") or {}
            intended_focused = (
                (
                    active.get("tag") == "textarea"
                    and active.get("id") == "wordsInput"
                )
                or (
                    active.get("tag") not in {"input", "textarea", "select"}
                    and active.get("contenteditable") is not True
                )
            )
        if not intended_focused:
            diagnostics = {}
            for selector in (
                "#commandLineWrapper",
                "#commandLine",
                "[role='dialog']",
                ".modal",
                ".popup",
                "input",
            ):
                diagnostics[selector] = inspect_target(
                    backend,
                    Locator(strategy=LocatorStrategy.CSS, value=selector),
                )
            print(
                "OVERLAY_DIAGNOSTICS="
                + json.dumps(diagnostics, sort_keys=True),
                flush=True,
            )
            raise RuntimeError(
                f"could not clear editable overlay focus: {focus_state!r}"
            )
        typing_context_locator = Locator(
            strategy=LocatorStrategy.CSS, value="#wordsInput"
        )
        typing_context = inspect_target(backend, typing_context_locator)
        if typing_context.get("match_count") != 1:
            raise RuntimeError(
                f"Monkeytype typing context is unavailable: {typing_context!r}"
            )
        typing_result = TypingSession(
            TypingSessionConfig(
                session_id="monkeytype-typing",
                url=URL,
                text=phrase,
                target_locator=typing_context_locator,
                max_text_chunk_characters=10,
                inter_key_delay_ms=0,
                operation_timeout_ms=30_000,
            ),
            backend=backend,
            browser_config=config,
        ).run()
        result["typing_session_used"] = True
        result["characters_safely_typed"] = typing_result.typed_characters
        result["active_typing_time_seconds"] = round(
            typing_result.duration_ms / 1000, 3
        )
        result["session_receipts"] = [
            item.to_dict() for item in typing_result.receipts
        ]
        result["page_observations"] = sum(
            int(getattr(item, "pre_action_observation", None) is not None)
            + int(getattr(item, "post_action_observation", None) is not None)
            for item in typing_result.receipts
        )
        if typing_result.status.value != "completed":
            result["safe_stop_event"] = {
                "status": typing_result.status.value,
                "failure_kind": typing_result.failure_kind,
                "error": typing_result.error,
            }
            result["input_completion_status"] = "SESSION_FAILED"
        else:
            result["input_completion_status"] = "INPUT_COMPLETED"
        print(
            "TYPING_SESSION="
            + json.dumps(
                {
                    "status": typing_result.status.value,
                    "requested_characters": typing_result.requested_characters,
                    "typed_characters": typing_result.typed_characters,
                    "duration_ms": typing_result.duration_ms,
                    "failure_kind": typing_result.failure_kind,
                    "error": typing_result.error,
                    "receipts": [
                        item.to_dict() for item in typing_result.receipts
                    ],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        session_error = None
        if typing_result.status.value != "completed":
            session_error = (
                f"typing session {typing_result.status.value}: "
                f"{typing_result.failure_kind}: {typing_result.error}"
            )

        # Fresh read-only evidence from the completed page.
        results_text = ""
        waiting_started = time.perf_counter()
        wait_observations = 0
        for _ in range(150):
            if not backend.is_started:
                break
            results_text = (inspect_target(backend, body_locator).get("text") or "").strip()
            wait_observations += 1
            if re.search(r"\bwpm\b", results_text, re.I) and re.search(
                r"\bacc(?:uracy)?\b", results_text, re.I
            ):
                break
            time.sleep(0.5)
        result["waiting_time_after_input_exhaustion_seconds"] = round(
            time.perf_counter() - waiting_started, 3
        )
        result["page_observations"] += wait_observations
        print("RESULTS_TEXT=" + json.dumps(results_text), flush=True)

        wpm_match = re.search(r"\bwpm\s*[\r\n ]+(\d+(?:\.\d+)?)", results_text, re.I)
        acc_match = re.search(
            r"\bacc(?:uracy)?\s*[\r\n ]+(\d+(?:\.\d+)?)%?", results_text, re.I
        )
        characters_match = re.search(
            r"\bcharacters\s*[\r\n ]+(\d+)/(\d+)/(\d+)/(\d+)",
            results_text,
            re.I,
        )
        words_result_match = re.search(
            r"\btest type\s*[\r\n ]+words\s+(\d+)",
            results_text,
            re.I,
        )
        if not (wpm_match and acc_match):
            raise RuntimeError(
                (session_error + "; " if session_error else "")
                + "results screen metrics were not found in fresh page evidence"
            )
        result["wpm"] = wpm_match.group(1)
        result["accuracy"] = acc_match.group(1) + "%"
        result["test_completion_status"] = "TEST_COMPLETED"
        if characters_match:
            result["test_errors"] = sum(
                int(value) for value in characters_match.groups()[1:]
            )
        if words_result_match:
            result["word_count_completed"] = int(words_result_match.group(1))
        else:
            result["word_count_completed"] = len(words)
        result["challenge_result"] = "PASSED"
    except Exception as exc:
        result["errors"] = [f"{type(exc).__name__}: {exc}"]
    finally:
        result["total_execution_time_seconds"] = round(time.perf_counter() - wall_started, 3)
        try:
            backend.stop()
        except Exception as exc:
            result.setdefault("errors", [])
            result["errors"].append(f"cleanup: {type(exc).__name__}: {exc}")  # type: ignore[union-attr]
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / "summary.json").write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
        print("FINAL_RESULT=" + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["challenge_result"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
