"""Headed YouTube five-minute benchmark using ExecutionPlans only."""
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
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.page_precondition import PageCondition, PageConditionType, PagePrecondition
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.contract.target import ConstraintType, TargetConstraint
from dingdongditch.contract.wait import WaitCondition, WaitConditionType
from dingdongditch.inspection import inspect_target
from dingdongditch.runtime.plan_executor import execute_plan

ROOT = Path(__file__).resolve().parent / "run3"
YOUTUBE = "https://www.youtube.com/"
ORIGIN = "https://www.youtube.com"
QUERY = "Somalia drone footage"


def css(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.CSS, value=value)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def processes() -> dict[int, str]:
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
    found: dict[int, str] = {}
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) >= 2:
            try:
                found[int(row[1])] = row[0]
            except ValueError:
                pass
    return found


def page_at(path: str) -> PagePrecondition:
    return PagePrecondition(
        (
            PageCondition(
                condition_id="youtube-origin",
                type=PageConditionType.ORIGIN_EQUALS,
                origin_value=ORIGIN,
            ),
            PageCondition(
                condition_id="youtube-path",
                type=PageConditionType.PATH_EQUALS,
                path_value=path,
            ),
        )
    )


def main() -> int:
    for name in ("receipts", "screenshots", "inspections", "samples"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    before = processes()
    write_json(ROOT / "processes_before.json", before)
    config = BrowserConfig(profile=BrowserProfile.DINGDONG, headless=False)
    screenshot = ScreenshotConfig(
        policy=ScreenshotPolicy.ALWAYS,
        full_page=False,
        max_per_operation=2,
        max_per_plan=2,
        artifact_root=str(ROOT / "screenshots"),
        capture_timeout_ms=10_000,
    )
    backend = PlaywrightBackend(browser_config=config)
    started = time.monotonic()
    summary: dict[str, Any] = {
        "result": "FAIL",
        "query": QUERY,
        "configured_headless": False,
        "window_required_visible": True,
        "javascript_injection": False,
        "direct_playwright_input": False,
        "samples": [],
        "interruptions": [],
        "overlays": [],
        "ads": [],
        "youtube_errors": [],
    }
    progress: dict[str, Any] = {"phase": "starting", "samples_completed": 0}
    write_json(ROOT / "progress.json", progress)
    step_no = 0

    def run_step(operation: Operation) -> Any:
        nonlocal step_no
        step_no += 1
        receipt = execute_plan(
            ExecutionPlan(
                plan_id=f"youtube-headed-{step_no:02d}-{operation.operation_id}",
                browser_config=config,
                screenshot_config=screenshot,
                initial_plan_timeout_ms=90_000,
                operations=[operation],
            ),
            backend=backend,
        )
        write_json(ROOT / "receipts" / f"{step_no:02d}_{operation.operation_id}.json", receipt.to_dict())
        return receipt

    def inspect(name: str, locator: Locator) -> dict[str, Any]:
        try:
            value = inspect_target(backend, locator)
        except Exception as exc:
            value = {"error": f"{type(exc).__name__}: {exc}"}
        write_json(ROOT / "inspections" / f"{name}.json", value)
        return value

    search = css("input[name='search_query']")
    first_result = css("ytd-video-renderer:first-of-type a#video-title")
    results_root = css("ytd-search")
    title = css("h1.ytd-watch-metadata yt-formatted-string")
    video = Locator(
        strategy=LocatorStrategy.CSS,
        value="video.html5-main-video",
        constraints=(
            TargetConstraint(type=ConstraintType.VISIBLE, visible=True),
        ),
    )
    ad_showing = css("#movie_player.ad-showing")
    captcha = css("form[action*='Captcha'], #captcha, input[name*='captcha' i]")
    error = css("yt-playability-error-supported-renderers, .ytp-error")

    try:
        backend.start()
        effective = backend.browser_environment()
        summary["effective_browser"] = effective
        print(
            "EFFECTIVE_BROWSER_MODE "
            f"profile={config.profile.value} engine={effective.get('engine')} "
            f"headless={str(effective.get('headless')).lower()} window=visible-headed",
            flush=True,
        )
        if effective.get("headless") is not False:
            summary["boundary"] = "not_headed"
            return 1

        setup = [
            Operation(
                operation_id="open-youtube",
                url=YOUTUBE,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(type=ExpectationType.URL, url_value="youtube.com", url_match=UrlMatchMode.CONTAINS),
                    Expectation(type=ExpectationType.ELEMENT_VISIBLE, locator=search, visible=True),
                ],
                timeout_ms=35_000,
            ),
            Operation(
                operation_id="fill-search",
                url=YOUTUBE,
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
                url=YOUTUBE,
                action=Action(type=ActionType.PRESS_KEY, locator=search, key="Enter"),
                expectations=[
                    Expectation(type=ExpectationType.URL, url_value="/results?search_query=", url_match=UrlMatchMode.CONTAINS),
                    Expectation(type=ExpectationType.ELEMENT_VISIBLE, locator=results_root, visible=True),
                ],
                timeout_ms=40_000,
            ),
            Operation(
                operation_id="open-first-playable-result",
                url=YOUTUBE,
                page_precondition=page_at("/results"),
                action=Action(type=ActionType.CLICK, locator=first_result),
                expectations=[
                    Expectation(type=ExpectationType.URL, url_value="/watch?", url_match=UrlMatchMode.CONTAINS),
                    Expectation(type=ExpectationType.ELEMENT_EXISTS, locator=video, exists=True),
                ],
                timeout_ms=45_000,
            ),
        ]
        for operation in setup:
            progress["phase"] = operation.operation_id
            write_json(ROOT / "progress.json", progress)
            receipt = run_step(operation)
            if receipt.plan_verdict.value != "VERIFIED":
                summary["boundary"] = operation.operation_id
                return 1

        summary["video_url"] = backend.page.url
        title_state = inspect("video_title", title)
        summary["video_title"] = title_state.get("text")
        inspect("first_result", first_result)
        captcha_state = inspect("captcha", captcha)
        if captcha_state.get("exists"):
            summary["boundary"] = "captcha"
            return 1
        error_state = inspect("youtube_error_initial", error)
        if error_state.get("visible"):
            summary["youtube_errors"].append(error_state)
            summary["boundary"] = "youtube_error"
            return 1

        # Wait for any ad state to clear; this is observation, not interaction.
        ad_receipt = run_step(
            Operation(
                operation_id="wait-ad-not-showing",
                url=YOUTUBE,
                page_precondition=page_at("/watch"),
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.ELEMENT_HIDDEN,
                        locator=ad_showing,
                    ),
                    wait_timeout_ms=45_000,
                ),
                timeout_ms=50_000,
            )
        )
        if ad_receipt.plan_verdict.value != "VERIFIED":
            summary["ads"].append({"result": "ad_did_not_clear", "receipt": "wait-ad-not-showing"})
            summary["boundary"] = "ad_did_not_clear"
            return 1

        def playing_operation(operation_id: str, timeout_ms: int) -> Operation:
            return Operation(
                operation_id=operation_id,
                url=YOUTUBE,
                page_precondition=page_at("/watch"),
                action=Action(
                    type=ActionType.WAIT_FOR,
                    wait_condition=WaitCondition(
                        type=WaitConditionType.VIDEO_PLAYING,
                        locator=video,
                    ),
                    wait_timeout_ms=timeout_ms,
                ),
                expectations=[
                    Expectation(type=ExpectationType.ELEMENT_EXISTS, locator=video, exists=True)
                ],
                timeout_ms=max(1_000, timeout_ms + 500),
            )

        initial_receipt = run_step(playing_operation("verify-playback-begun", 8_000))
        if initial_receipt.plan_verdict.value != "VERIFIED":
            # Starting playback is a benchmark requirement, not recovery.
            play = css("button.ytp-play-button[title^='Play']")
            start_receipt = run_step(
                Operation(
                    operation_id="start-playback",
                    url=YOUTUBE,
                    page_precondition=page_at("/watch"),
                    action=Action(type=ActionType.CLICK, locator=play),
                    expectations=[Expectation(type=ExpectationType.ELEMENT_EXISTS, locator=video, exists=True)],
                    timeout_ms=15_000,
                )
            )
            if start_receipt.plan_verdict.value != "VERIFIED":
                summary["boundary"] = "start_playback"
                return 1
            initial_receipt = run_step(playing_operation("verify-playback-after-start", 8_000))
            if initial_receipt.plan_verdict.value != "VERIFIED":
                summary["boundary"] = "playback_never_began"
                return 1

        initial_op = initial_receipt.steps[0].receipt
        assert initial_op is not None
        initial_state = initial_op.action_evidence.get("final_observed_state", {})
        summary["initial_playback_state"] = initial_state
        playback_started_wall = time.monotonic()
        initial_time = float(initial_state.get("currentTime") or 0)
        previous_time = initial_time
        previous_source = initial_state.get("currentSrc")
        previous_token = initial_state.get("elementToken")
        progress["phase"] = "observing"
        write_json(ROOT / "progress.json", progress)

        for sample_index in range(1, 11):
            due = playback_started_wall + sample_index * 30
            remaining = due - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            receipt = run_step(
                playing_operation(f"sample-{sample_index:02d}-at-{sample_index * 30}s", 750)
            )
            op_receipt = receipt.steps[0].receipt
            state = (
                op_receipt.action_evidence.get("final_observed_state", {})
                if op_receipt is not None
                else {}
            )
            sample = {
                "sample_index": sample_index,
                "scheduled_seconds": sample_index * 30,
                "wall_elapsed_seconds": round(time.monotonic() - playback_started_wall, 3),
                "verdict": receipt.plan_verdict.value,
                "currentTime": state.get("currentTime"),
                "paused": state.get("paused"),
                "ended": state.get("ended"),
                "readyState": state.get("readyState"),
                "duration": state.get("duration"),
                "playbackRate": state.get("playbackRate"),
                "currentSrc": state.get("currentSrc"),
                "elementToken": state.get("elementToken"),
                "playback_quality": "unavailable_in_typed_contract",
            }
            summary["samples"].append(sample)
            write_json(ROOT / "samples" / f"sample_{sample_index:02d}.json", sample)
            progress["samples_completed"] = sample_index
            progress["last_sample"] = sample
            write_json(ROOT / "progress.json", progress)
            current = float(state.get("currentTime") or 0)
            stopped = (
                receipt.plan_verdict.value != "VERIFIED"
                or bool(state.get("paused"))
                or bool(state.get("ended"))
                or int(state.get("readyState") or 0) < 2
                or current <= previous_time
                or state.get("currentSrc") != previous_source
                or state.get("elementToken") != previous_token
            )
            if stopped:
                summary["interruptions"].append(sample)
                summary["boundary"] = "playback_interrupted"
                summary["playback_duration_achieved_seconds"] = max(0, current - initial_time)
                return 1
            previous_time = current

        summary["playback_duration_achieved_seconds"] = previous_time - initial_time
        summary["observation_wall_seconds"] = time.monotonic() - playback_started_wall
        summary["result"] = "PASS"
        return 0
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
        owned = {"chrome.exe", "chromium.exe", "node.exe", "playwright.exe"}
        after = processes()
        remaining_owned: list[dict[str, Any]] = []
        for _ in range(10):
            remaining_owned = [
                {"pid": pid, "image": image}
                for pid, image in after.items()
                if pid not in before and image.lower() in owned
            ]
            if not remaining_owned:
                break
            time.sleep(0.5)
            after = processes()
        summary["remaining_owned_processes"] = remaining_owned
        summary["cleanup_errors"] = list(backend.cleanup_errors)
        summary["terminal_session_identity"] = backend.terminal_session_identity
        summary["total_runtime_seconds"] = round(time.monotonic() - started, 3)
        write_json(ROOT / "processes_after.json", after)
        write_json(ROOT / "summary.json", summary)
        progress["phase"] = "complete"
        progress["result"] = summary["result"]
        write_json(ROOT / "progress.json", progress)


if __name__ == "__main__":
    raise SystemExit(main())
