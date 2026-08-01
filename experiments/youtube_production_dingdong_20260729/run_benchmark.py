"""Persistent-profile 20-minute YouTube production benchmark."""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any

from dingdongditch.contract.browser import (
    BrowserChannel, BrowserConfig, BrowserEngine, BrowserProfile, BrowserProvider,
)
from dingdongditch.contract.operation import Action, ActionType
from dingdongditch.contract.target import ConstraintType, TargetConstraint
from dingdongditch.contract.wait import WaitCondition, WaitConditionType

BASE = Path(__file__).resolve().parent
HERE = BASE / "attempt-6"
SOURCE = BASE.parent / "youtube_production_20260729_atomic_snapshot" / "run_benchmark.py"
spec = importlib.util.spec_from_file_location("youtube_production_source", SOURCE)
assert spec and spec.loader
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

harness.HERE = HERE
harness.RECEIPTS = HERE / "receipts"
harness.INSPECTIONS = HERE / "inspections"
harness.SCREENSHOTS = HERE / "screenshots"
harness.CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
    profile=BrowserProfile.DINGDONG,
)
harness.SHOT_CONFIG = harness.ScreenshotConfig(
    policy=harness.ScreenshotPolicy.AFTER_SUCCESS,
    full_page=False,
    max_per_operation=1,
    max_per_plan=64,
    artifact_root=str(harness.SCREENSHOTS),
    capture_timeout_ms=5_000,
)
harness.VIDEO = harness.Locator(
    strategy=harness.LocatorStrategy.CSS,
    value="video.html5-main-video",
    constraints=(
        TargetConstraint(type=ConstraintType.VISIBLE, visible=True),
    ),
)
original_css = harness.css


def long_form_css(value: str) -> Any:
    if value == "ytd-video-renderer:nth-of-type(1) a#thumbnail":
        value = "ytd-video-renderer:nth-of-type(4) a#thumbnail"
    elif value == "ytd-video-renderer:nth-of-type(2) a#thumbnail":
        value = "ytd-video-renderer:nth-of-type(3) a#thumbnail"
    return original_css(value)


harness.css = long_form_css

active_backend: Any = None
redirects: list[dict[str, Any]] = []
playback_interruptions: list[dict[str, Any]] = []
OriginalBackend = harness.PlaywrightBackend


class ObservedBackend(OriginalBackend):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        global active_backend
        super().__init__(*args, **kwargs)
        active_backend = self

    def stop(self) -> None:
        redirects.extend(
            {"status": item.status, "url": item.url}
            for item in self._network
            if item.status is not None and 300 <= item.status < 400
        )
        super().stop()


harness.PlaywrightBackend = ObservedBackend
original_pointer = harness.pointer


def optional_safe_pointer(
    backend: Any, plan_id: str, url: str, locator: Any
) -> None:
    if plan_id in {"pointer_sidebar", "pointer_filters"}:
        label = plan_id.removeprefix("pointer_")
        state = harness.inspect(backend, f"optional_{label}_check", locator)["data"]
        if state.get("match_count") != 1 or state.get("visible") is not True:
            harness.timeline.append(
                {"optional_target_skipped": label, "reason": "not unique and visible"}
            )
            return
    original_pointer(backend, plan_id, url, locator)


harness.pointer = optional_safe_pointer


def verified_ten_minute_dwell(seconds: float, label: str) -> None:
    del seconds
    assert active_backend is not None
    started = time.perf_counter()
    current_url = active_backend.page.url
    for minute in range(1, 11):
        wait_started = time.perf_counter()
        time.sleep(60)
        harness.timeline.append(
            {
                "host_wait": f"{label}_minute_{minute}",
                "requested_s": 60,
                "actual_s": time.perf_counter() - wait_started,
            }
        )
        try:
            harness.run_plan(
                active_backend,
                f"{label}_checkpoint_{minute:02d}",
                [
                    harness.op(
                        f"{label}-playing-{minute:02d}",
                        current_url,
                        Action(
                            type=ActionType.WAIT_FOR,
                            wait_condition=WaitCondition(
                                type=WaitConditionType.VIDEO_PLAYING,
                                locator=harness.VIDEO,
                            ),
                            wait_timeout_ms=15_000,
                        ),
                        timeout_ms=20_000,
                    )
                ],
            )
        except RuntimeError as exc:
            playback_interruptions.append(
                {"video": label, "minute": minute, "error": str(exc)}
            )
            controls = harness.css(".ytp-play-button")
            harness.run_plan(
                active_backend,
                f"{label}_resume_{minute:02d}",
                [
                    harness.op(
                        f"{label}-resume-click-{minute:02d}",
                        current_url,
                        Action(type=ActionType.CLICK, locator=controls),
                    ),
                    harness.op(
                        f"{label}-resume-verify-{minute:02d}",
                        current_url,
                        Action(
                            type=ActionType.WAIT_FOR,
                            wait_condition=WaitCondition(
                                type=WaitConditionType.VIDEO_PLAYING,
                                locator=harness.VIDEO,
                            ),
                            wait_timeout_ms=15_000,
                        ),
                        timeout_ms=20_000,
                    ),
                ],
            )
    harness.timeline.append(
        {"playback": label, "verified_duration_s": time.perf_counter() - started}
    )


harness.dwell = verified_ten_minute_dwell


def main() -> int:
    code = harness.main()
    report_path = HERE / "benchmark_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    inspection_text = json.dumps(harness.inspections).lower()
    report.update(
        {
            "browser_profile": BrowserProfile.DINGDONG.value,
            "redirect_count": len(redirects),
            "redirects": redirects,
            "consent_prompt_observed": any(
                item["name"].startswith("candidate_")
                and item["data"].get("visible") is True
                for item in harness.inspections
            ),
            "sign_in_request_observed": "sign in" in inspection_text,
            "playback_checkpoints_per_video": 10,
            "playback_interruptions": playback_interruptions,
        }
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
