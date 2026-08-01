"""Two-turn Gemini conversation through DingDongDitch's visible browser runtime."""
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
from dingdongditch.contract.observation import ObservationReference, PageObservationOptions
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.inspection import observe_page
from dingdongditch.runtime.plan_executor import execute_plan
from dingdongditch.runtime.typing_session import TypingFocusPolicy, TypingSession, TypingSessionConfig

ROOT = Path(__file__).resolve().parent
GEMINI = "https://gemini.google.com/app"
MESSAGE_1 = (
    "Hello Gemini. I am speaking to you through a browser execution runtime called "
    "DingDongDitch. Please introduce yourself in two short sentences, then ask me "
    "one question about DingDongDitch."
)
MESSAGE_2 = (
    "DingDongDitch is a model-neutral browser execution runtime. An external planner "
    "decides what should happen, while DingDongDitch observes the page, executes "
    "bounded browser operations, verifies outcomes, and produces evidence-backed receipts."
)


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def locator_from_candidate(candidate: dict[str, Any]) -> Locator:
    kind = candidate["locator_type"]
    value = candidate["locator_value"]
    if kind == "role_name":
        return Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role=value["role"],
            name=value["name"],
        )
    if kind == "test_id":
        return Locator(strategy=LocatorStrategy.TEST_ID, value=value)
    if kind == "exact_text":
        return Locator(strategy=LocatorStrategy.EXACT_TEXT, value=value)
    if kind == "css":
        return Locator(strategy=LocatorStrategy.CSS, value=value)
    raise ValueError(f"unsupported observation locator candidate: {kind}")


def unique_locator(element: dict[str, Any]) -> tuple[Locator, dict[str, Any]]:
    supported = {"role_name", "test_id", "exact_text", "css"}
    candidate = next(
        (
            item for item in element["locator_candidates"]
            if item["unique"] and item["locator_type"] in supported
        ),
        None,
    )
    if candidate is None:
        raise RuntimeError(f"element {element['element_id']} has no unique executable locator")
    return locator_from_candidate(candidate), candidate


def prompt_elements(observation: Any) -> list[dict[str, Any]]:
    results = []
    for element in observation.interactive_elements:
        role = str(element.get("semantic_role") or "").lower()
        tag = str(element.get("dom_tag") or "").lower()
        name = str(element.get("accessible_name") or "").lower()
        placeholder = str(element.get("placeholder") or "").lower()
        editable = element.get("editable") is True or tag in {"textarea", "input"}
        language = f"{name} {placeholder}"
        if element.get("visible") and editable and any(
            token in language for token in ("prompt", "ask gemini", "enter a prompt", "message gemini")
        ):
            results.append(element)
        elif element.get("visible") and role == "textbox" and editable:
            results.append(element)
    return results


def page_text(observation: Any) -> str:
    return "\n".join(
        str(block.get("text") or "").strip()
        for block in observation.visible_text
        if str(block.get("text") or "").strip()
    )


def controls(observation: Any) -> dict[str, list[dict[str, Any]]]:
    found = {"stop": [], "send": [], "signin": [], "dismiss": []}
    for element in observation.interactive_elements:
        if not element.get("visible"):
            continue
        label = " ".join(
            str(element.get(key) or "") for key in ("accessible_name", "visible_text", "placeholder")
        ).strip().lower()
        if any(x in label for x in ("stop response", "stop generating", "stop generation")):
            found["stop"].append(element)
        if any(x in label for x in ("send message", "submit", "send prompt")):
            found["send"].append(element)
        if "sign in" in label:
            found["signin"].append(element)
        if any(x == label for x in ("got it", "no thanks", "dismiss", "close")):
            found["dismiss"].append(element)
    return found


def main() -> int:
    started = time.monotonic()
    for name in ("observations", "receipts", "typing", "screenshots"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    config = BrowserConfig(profile=BrowserProfile.DINGDONG, headless=False)
    screenshots = ScreenshotConfig(
        policy=ScreenshotPolicy.ALWAYS,
        full_page=False,
        max_per_operation=2,
        max_per_plan=2,
        artifact_root=str(ROOT / "screenshots"),
        capture_timeout_ms=10_000,
    )
    backend = PlaywrightBackend(browser_config=config)
    summary: dict[str, Any] = {
        "experiment_result": "FAIL",
        "browser_profile": config.profile.value,
        "configured_headless": config.headless,
        "persistent_profile_used": False,
        "page_observations_performed": 0,
        "freshness_validations": [],
        "typing_sessions_used": 0,
        "user_message_1": MESSAGE_1,
        "user_message_2": MESSAGE_2,
        "recovery_events": [],
        "runtime_defects_repaired": [],
        "safety_stops_or_rejected_page_instructions": [],
    }
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
                max_text_length=2000,
                freshness_max_age_ms=30_000,
            ),
        )
        dump(ROOT / "observations" / f"{observation_number:03d}_{label}.json", value.to_dict())
        summary["page_observations_performed"] = observation_number
        return value

    def validate(obs: Any, element: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
        result = backend.validate_observation_reference(
            ObservationReference(obs.observation_id, element["element_id"], expected)
        ).to_dict()
        summary["freshness_validations"].append(
            {"observation_id": obs.observation_id, "element_id": element["element_id"], **result}
        )
        if not result["fresh"]:
            raise RuntimeError(f"observation reference validation failed: {result['reason']}")
        return result

    def run(operation: Operation) -> Any:
        nonlocal operation_number
        operation_number += 1
        receipt = execute_plan(
            ExecutionPlan(
                plan_id=f"gemini-{operation_number:02d}-{operation.operation_id}",
                browser_config=config,
                screenshot_config=screenshots,
                initial_plan_timeout_ms=60_000,
                operations=[operation],
            ),
            backend=backend,
        )
        dump(ROOT / "receipts" / f"{operation_number:02d}_{operation.operation_id}.json", receipt.to_dict())
        if receipt.plan_verdict.value != "VERIFIED":
            raise RuntimeError(f"operation not verified: {operation.operation_id}")
        return receipt

    def wait_complete(turn: int, previous_text: str) -> tuple[Any, str, list[dict[str, Any]]]:
        evidence: list[dict[str, Any]] = []
        stable = 0
        last = ""
        saw_streaming = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            backend.page.wait_for_timeout(2000)
            obs = observe(f"turn{turn}_completion_check")
            text = page_text(obs)
            state = controls(obs)
            streaming = bool(state["stop"])
            saw_streaming = saw_streaming or streaming
            changed_from_before = text != previous_text and len(text) > len(previous_text)
            if text == last and changed_from_before and not streaming:
                stable += 1
            else:
                stable = 0
            evidence.append(
                {
                    "observation_id": obs.observation_id,
                    "streaming_control_visible": streaming,
                    "send_control_visible": bool(state["send"]),
                    "text_length": len(text),
                    "stable_idle_samples": stable,
                }
            )
            last = text
            if stable >= 2:
                return obs, text, evidence
        raise TimeoutError(
            f"turn {turn} did not reach two stable idle observations; saw_streaming={saw_streaming}"
        )

    try:
        backend.start()
        environment = backend.browser_environment()
        summary["browser_environment"] = environment
        summary["persistent_profile_used"] = (
            config.profile == BrowserProfile.DINGDONG
            and environment.get("engine") == "chromium"
            and environment.get("newly_launched") is True
        )
        if environment.get("headless") is not False:
            raise RuntimeError("browser is not headed")

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
        initial = observe("initial")
        initial_controls = controls(initial)
        prompts = prompt_elements(initial)
        summary["initial_url"] = initial.url
        summary["initial_title"] = initial.title
        summary["initial_overlays"] = initial.overlays
        if not prompts and initial_controls["signin"]:
            summary["initial_gemini_page_state"] = "sign-in required"
            summary["authentication_required"] = True
            summary["experiment_result"] = "SAFE_STOP"
            return 2
        if not prompts and initial_controls["dismiss"]:
            dismiss = initial_controls["dismiss"][0]
            validate(initial, dismiss, {"visible": True, "enabled": True})
            dismiss_locator, dismiss_candidate = unique_locator(dismiss)
            summary["recovery_events"].append(
                {"kind": "harmless_dismissal", "candidate": dismiss_candidate}
            )
            run(
                Operation(
                    operation_id="dismiss-onboarding",
                    url=initial.url,
                    action=Action(type=ActionType.CLICK, locator=dismiss_locator),
                    timeout_ms=20_000,
                )
            )
            initial = observe("after_dismissal")
            prompts = prompt_elements(initial)
        if len(prompts) != 1:
            summary["initial_gemini_page_state"] = "other observed state"
            summary["authentication_required"] = bool(initial_controls["signin"])
            summary["prompt_candidates"] = prompts
            raise RuntimeError(f"expected one visible Gemini prompt surface, found {len(prompts)}")

        summary["initial_gemini_page_state"] = "Gemini chat interface available"
        summary["authentication_required"] = False
        prompt = prompts[0]
        validate(initial, prompt, {"visible": True, "enabled": True})
        prompt_locator, prompt_candidate = unique_locator(prompt)
        summary["prompt_surface"] = {
            "element_id": prompt["element_id"],
            "role": prompt.get("semantic_role"),
            "accessible_name": prompt.get("accessible_name"),
            "placeholder": prompt.get("placeholder"),
            "locator_candidate": prompt_candidate,
        }

        before_1 = page_text(initial)
        typing_1 = TypingSession(
            TypingSessionConfig(
                session_id="gemini-message-1",
                url=initial.url,
                text=MESSAGE_1,
                focus_locator=prompt_locator,
                focus_policy=TypingFocusPolicy.TARGET_FOCUSED,
                verify_every_characters=25,
                inter_key_delay_ms=4,
                operation_timeout_ms=15_000,
            ),
            backend=backend,
            browser_config=config,
        ).run()
        summary["typing_sessions_used"] += 1
        dump(ROOT / "typing" / "message_1.json", typing_1.to_dict())
        if typing_1.status.value != "completed":
            raise RuntimeError(f"first typing session failed: {typing_1.failure_kind}")
        typed_1 = observe("message1_typed")
        prompt_now = prompt_elements(typed_1)
        if len(prompt_now) != 1:
            raise RuntimeError("prompt surface was not uniquely observable after first typing")
        validate(typed_1, prompt_now[0], {"visible": True, "enabled": True})
        submit_locator, _ = unique_locator(prompt_now[0])
        run(
            Operation(
                operation_id="submit-message-1",
                url=typed_1.url,
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
        completed_1, text_1, completion_1 = wait_complete(1, before_1)
        summary["response_completion_evidence_turn_1"] = completion_1
        summary["gemini_response_1_visible_conversation"] = text_1

        prompts_2 = prompt_elements(completed_1)
        if len(prompts_2) != 1:
            raise RuntimeError("existing chat input was not uniquely observable for second turn")
        validate(completed_1, prompts_2[0], {"visible": True, "enabled": True})
        prompt_locator_2, _ = unique_locator(prompts_2[0])
        before_2 = text_1
        typing_2 = TypingSession(
            TypingSessionConfig(
                session_id="gemini-message-2",
                url=completed_1.url,
                text=MESSAGE_2,
                focus_locator=prompt_locator_2,
                focus_policy=TypingFocusPolicy.TARGET_FOCUSED,
                verify_every_characters=25,
                inter_key_delay_ms=4,
                operation_timeout_ms=15_000,
            ),
            backend=backend,
            browser_config=config,
        ).run()
        summary["typing_sessions_used"] += 1
        dump(ROOT / "typing" / "message_2.json", typing_2.to_dict())
        if typing_2.status.value != "completed":
            raise RuntimeError(f"second typing session failed: {typing_2.failure_kind}")
        typed_2 = observe("message2_typed")
        prompt_after_2 = prompt_elements(typed_2)
        if len(prompt_after_2) != 1:
            raise RuntimeError("prompt surface was not uniquely observable after second typing")
        validate(typed_2, prompt_after_2[0], {"visible": True, "enabled": True})
        submit_locator_2, _ = unique_locator(prompt_after_2[0])
        run(
            Operation(
                operation_id="submit-message-2",
                url=typed_2.url,
                action=Action(type=ActionType.PRESS_KEY, locator=submit_locator_2, key="Enter"),
                expectations=[
                    Expectation(
                        type=ExpectationType.ELEMENT_EXISTS,
                        locator=submit_locator_2,
                        exists=True,
                    )
                ],
                timeout_ms=20_000,
            )
        )
        completed_2, text_2, completion_2 = wait_complete(2, before_2)
        summary["response_completion_evidence_turn_2"] = completion_2
        summary["gemini_response_2_visible_conversation"] = text_2
        summary["full_visible_conversation_evidence"] = completed_2.to_dict()
        summary["experiment_result"] = "PASS"
        return 0
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
        return 1
    finally:
        summary["total_execution_time_seconds"] = round(time.monotonic() - started, 3)
        dump(ROOT / "evidence_artifact.json", summary)
        backend.stop()


if __name__ == "__main__":
    raise SystemExit(main())
