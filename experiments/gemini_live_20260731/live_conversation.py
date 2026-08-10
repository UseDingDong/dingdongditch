"""Persistent, observation-driven Gemini conversation through DingDongDitch."""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserConfig, BrowserEngine, BrowserProfile
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import UrlMatchMode
from dingdongditch.contract.observation import ObservationReference, PageObservationOptions
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.inspection import observe_page
from dingdongditch.runtime.plan_executor import execute_plan
from dingdongditch.runtime.generation_monitor import (
    GenerationStatus,
    ProgressBasedGenerationMonitor,
)
from dingdongditch.runtime.inbox import read_published_text
from dingdongditch.runtime.run_ownership import acquire_run_generation
from dingdongditch.runtime.publication import publish_json
from dingdongditch.runtime.typing_session import TypingSession, TypingSessionConfig

ROOT = Path(__file__).resolve().parent
INBOX = ROOT / "messages"
OUTBOX = ROOT / "responses"
GEMINI = "https://gemini.google.com/app"
NO_PROGRESS_LEASE_MS = 30_000


class GenerationStalledError(RuntimeError):
    def __init__(self, turn: int, evidence: list[dict[str, Any]]) -> None:
        super().__init__(f"Gemini turn {turn} generation stalled")
        self.evidence = evidence


def write_json(path: Path, value: Any) -> None:
    publish_json(path, value)


def load_message(path: Path) -> str | None:
    return read_published_text(path)


def locator(candidate: dict[str, Any]) -> Locator:
    kind, value = candidate["locator_type"], candidate["locator_value"]
    if kind == "role_name":
        return Locator(strategy=LocatorStrategy.ROLE_NAME, role=value["role"], name=value["name"])
    if kind == "test_id":
        return Locator(strategy=LocatorStrategy.TEST_ID, value=value)
    if kind == "exact_text":
        return Locator(strategy=LocatorStrategy.EXACT_TEXT, value=value)
    if kind == "css":
        return Locator(strategy=LocatorStrategy.CSS, value=value)
    raise ValueError(kind)


def unique_locator(element: dict[str, Any]) -> Locator:
    for item in element["locator_candidates"]:
        if item["unique"] and item["locator_type"] in {"role_name", "test_id", "exact_text", "css"}:
            return locator(item)
    raise RuntimeError(f"No unique executable locator for {element['element_id']}")


def prompts(observation: Any) -> list[dict[str, Any]]:
    found = []
    for element in observation.interactive_elements:
        if not element.get("visible"):
            continue
        role = str(element.get("semantic_role") or "").lower()
        tag = str(element.get("dom_tag") or "").lower()
        language = " ".join(
            str(element.get(key) or "").lower()
            for key in ("accessible_name", "placeholder", "visible_text")
        )
        editable = element.get("editable") is True or tag in {"textarea", "input"}
        if editable and (
            any(token in language for token in ("prompt", "ask gemini", "enter a prompt", "message gemini"))
            or role == "textbox"
        ):
            found.append(element)
    return found


def page_text(observation: Any) -> str:
    return "\n".join(
        str(block.get("text") or "").strip()
        for block in observation.visible_text
        if str(block.get("text") or "").strip()
    )


def streaming(observation: Any) -> bool:
    for element in observation.interactive_elements:
        label = " ".join(
            str(element.get(key) or "").lower()
            for key in ("accessible_name", "visible_text", "placeholder")
        )
        if element.get("visible") and any(
            token in label for token in ("stop response", "stop generating", "stop generation")
        ):
            return True
    return False


def completion_sample_is_stable(
    text: str,
    previous_text: str,
    last_text: str,
    is_streaming: bool,
) -> bool:
    return text != previous_text and text == last_text and not is_streaming


def page_state(observation: Any) -> str:
    text = page_text(observation).lower()
    if len(prompts(observation)) == 1:
        return "gemini_conversation_interface"
    if any(token in text for token in ("sign in", "choose an account", "use your google account")):
        return "authentication_required"
    if not text and not observation.interactive_elements:
        return "blank_or_unhydrated"
    return "other_observable_state"


def main() -> int:
    run_lease = acquire_run_generation(ROOT / "runs")
    RUN = run_lease.path
    INBOX = RUN / "messages"
    OUTBOX = RUN / "responses"
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    for stale in (RUN / "status.json", RUN / "failure.json", RUN / "STOP"):
        if stale.exists():
            stale.unlink()
    requested_engine = BrowserEngine(os.environ.get("DINGDONGDITCH_GEMINI_ENGINE", "chromium"))
    requested_profile = (
        BrowserProfile.DINGDONG
        if requested_engine == BrowserEngine.CHROMIUM
        else BrowserProfile.BENCHMARK
    )
    config = BrowserConfig(
        engine=requested_engine,
        profile=requested_profile,
        headless=False,
    )
    backend = PlaywrightBackend(browser_config=config)
    observation_number = 0
    operation_number = 0

    def observe(label: str) -> Any:
        nonlocal observation_number
        observation_number += 1
        value = observe_page(
            backend,
            PageObservationOptions(
                max_interactive_elements=500,
                max_text_blocks=400,
                max_text_length=4000,
                freshness_max_age_ms=30_000,
            ),
        )
        write_json(RUN / "observations" / f"{observation_number:04d}_{label}.json", value.to_dict())
        return value

    def run(operation: Operation) -> None:
        nonlocal operation_number
        operation_number += 1
        receipt = execute_plan(
            ExecutionPlan(
                plan_id=f"gemini-live-{operation_number:03d}",
                browser_config=config,
                initial_plan_timeout_ms=60_000,
                operations=[operation],
            ),
            backend=backend,
        )
        write_json(RUN / "receipts" / f"{operation_number:04d}.json", receipt.to_dict())
        if receipt.plan_verdict.value != "VERIFIED":
            raise RuntimeError(f"Operation not verified: {operation.operation_id}")

    def await_completion(turn: int, previous_text: str) -> tuple[Any, str]:
        monitor = ProgressBasedGenerationMonitor(
            baseline_text=previous_text,
            no_progress_lease_ms=NO_PROGRESS_LEASE_MS,
            stable_observations_required=2,
        )
        while True:
            backend.page.wait_for_timeout(2000)
            observed = observe(f"turn_{turn}_completion")
            text = page_text(observed)
            active = streaming(observed)
            result = monitor.observe(
                observation_id=observed.observation_id,
                captured_at_ms=observed.captured_at_ms,
                text=text,
                generation_active=active,
                progress_signals=("generation_active",) if active else (),
                fresh=True,
            )
            if result.status == GenerationStatus.COMPLETED:
                return observed, text
            if result.status == GenerationStatus.GENERATION_STALLED:
                raise GenerationStalledError(turn, result.evidence)

    try:
        backend.start()
        environment = backend.browser_environment()
        write_json(RUN / "browser_environment.json", environment)
        if environment.get("headless") is not False or environment.get("engine") != requested_engine.value:
            raise RuntimeError(
                f"Required headed {requested_engine.value} was not established: {environment}"
            )
        run(
            Operation(
                operation_id="navigate-gemini",
                url=GEMINI,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="gemini.google.com",
                        url_match=UrlMatchMode.CONTAINS,
                    )
                ],
                timeout_ms=45_000,
            )
        )
        initialization = []
        current = observe("initial")
        deadline = time.monotonic() + 60
        stable_state = None
        stable_count = 0
        while True:
            state = page_state(current)
            initialization.append(
                {
                    "observation_id": current.observation_id,
                    "url": current.url,
                    "title": current.title,
                    "state": state,
                    "prompt_count": len(prompts(current)),
                    "interactive_count": len(current.interactive_elements),
                    "visible_text_length": len(page_text(current)),
                }
            )
            write_json(RUN / "initialization.json", initialization)
            if state == stable_state:
                stable_count += 1
            else:
                stable_state, stable_count = state, 1
            if state == "gemini_conversation_interface":
                break
            if state == "authentication_required" and stable_count >= 2:
                raise RuntimeError("Gemini requires authentication in the DINGDONG profile")
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Gemini did not expose a usable prompt within 60 seconds; final observed state: {state}"
                )
            backend.page.wait_for_timeout(2000)
            current = observe("initialization_wait")
        write_json(
            RUN / "status.json",
            {
                "status": "ready",
                "url": current.url,
                "title": current.title,
                "profile": "dingdong",
                "initialization_observations": len(initialization),
            },
        )
        turn = 1
        while not (RUN / "STOP").exists():
            message_path = INBOX / f"{turn:03d}.txt"
            message = load_message(message_path)
            while message is None and not (RUN / "STOP").exists():
                time.sleep(0.25)
                message = load_message(message_path)
            if (RUN / "STOP").exists():
                break
            assert message is not None
            prompt_list = prompts(current)
            if len(prompt_list) != 1:
                current = observe(f"turn_{turn}_pre_type")
                prompt_list = prompts(current)
            if len(prompt_list) != 1:
                raise RuntimeError(f"Turn {turn}: expected one prompt textbox, found {len(prompt_list)}")
            prompt = prompt_list[0]
            validation = backend.validate_observation_reference(
                ObservationReference(
                    current.observation_id,
                    prompt["element_id"],
                    {"visible": True, "enabled": True},
                )
            )
            if not validation.fresh:
                current = observe(f"turn_{turn}_refresh")
                prompt = prompts(current)[0]
            prompt_locator = unique_locator(prompt)
            before = page_text(current)
            result = TypingSession(
                TypingSessionConfig(
                    session_id=f"gemini-live-turn-{turn}",
                    url=current.url,
                    text=message,
                    target_locator=prompt_locator,
                    max_text_chunk_characters=25,
                    inter_key_delay_ms=4,
                    operation_timeout_ms=30_000,
                ),
                backend=backend,
                browser_config=config,
            ).run()
            write_json(RUN / "typing" / f"{turn:04d}.json", result.to_dict())
            if result.status.value != "completed":
                raise RuntimeError(f"Turn {turn} TypingSession failed: {result.failure_kind}")
            typed = observe(f"turn_{turn}_typed")
            typed_prompts = prompts(typed)
            if len(typed_prompts) != 1:
                raise RuntimeError(f"Turn {turn}: prompt was not unique after typing")
            submit_locator = unique_locator(typed_prompts[0])
            run(
                Operation(
                    operation_id=f"submit-turn-{turn}",
                    url=typed.url,
                    action=Action(type=ActionType.PRESS_KEY, locator=submit_locator, key="Enter"),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_EXISTS,
                            locator=submit_locator,
                            exists=True,
                        )
                    ],
                    timeout_ms=20_000,
                )
            )
            current, completed_text = await_completion(turn, before)
            write_json(
                OUTBOX / f"{turn:03d}.json",
                {
                    "turn": turn,
                    "url": current.url,
                    "observation_id": current.observation_id,
                    "visible_conversation": completed_text,
                    "observation": current.to_dict(),
                },
            )
            print(f"TURN_COMPLETE {turn}", flush=True)
            turn += 1
        run_lease.finish("completed")
        return 0
    except Exception as exc:
        failure = {
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        if isinstance(exc, GenerationStalledError):
            failure["result"] = GenerationStatus.GENERATION_STALLED.value
            failure["browser_evidence"] = exc.evidence
        write_json(RUN / "failure.json", failure)
        print(f"EXPERIMENT_FAILURE {type(exc).__name__}: {exc}", flush=True)
        run_lease.finish("failed", error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        backend.stop()
        run_lease.close()


if __name__ == "__main__":
    raise SystemExit(main())
