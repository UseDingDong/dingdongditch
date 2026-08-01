"""Generic observation-driven live browser conversation harness.

The host atomically publishes immutable JSON commands into ``control/commands/pending``.
This process executes only declared DingDongDitch operations, preserves their
receipts and fresh PageObservations, and keeps the headed persistent browser
session alive between commands.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dingdongditch import (  # noqa: E402
    Action,
    ActionType,
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProfile,
    BrowserProvider,
    Locator,
    LocatorStrategy,
    NameMatchMode,
    ObservationReference,
    Operation,
    PageObservationOptions,
    ScreenshotConfig,
    execute_operation,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend  # noqa: E402
from dingdongditch.runtime.run_ownership import acquire_run_generation  # noqa: E402
from dingdongditch.runtime.publication import append_json_line, publish_json  # noqa: E402
from dingdongditch.runtime.file_queue import AtomicFileQueue  # noqa: E402


RUN_DIR = ROOT / "artifacts" / "gemini_live_conversation"
CONTROL_DIR = RUN_DIR / "control"
COMMAND_PATH = CONTROL_DIR / "command.json"
STATUS_PATH = CONTROL_DIR / "status.json"
EVENTS_PATH = RUN_DIR / "events.jsonl"
SCREENSHOTS_DIR = RUN_DIR / "screenshots"


def atomic_json(path: Path, value: object) -> None:
    publish_json(path, value)


def append_event(value: object) -> None:
    append_json_line(EVENTS_PATH, value)


def locator_from_dict(raw: dict[str, object]) -> Locator:
    strategy = LocatorStrategy(str(raw["strategy"]))
    if strategy == LocatorStrategy.ROLE_NAME:
        return Locator(
            strategy=strategy,
            role=str(raw["role"]),
            name=str(raw["name"]),
            name_match=NameMatchMode(str(raw.get("name_match", "exact"))),
        )
    return Locator(strategy=strategy, value=str(raw["value"]))


def main() -> int:
    global RUN_DIR, CONTROL_DIR, COMMAND_PATH, STATUS_PATH, EVENTS_PATH, SCREENSHOTS_DIR
    run_lease = acquire_run_generation(RUN_DIR)
    RUN_DIR = run_lease.path
    CONTROL_DIR = RUN_DIR / "control"
    COMMAND_PATH = CONTROL_DIR / "command.json"
    STATUS_PATH = CONTROL_DIR / "status.json"
    EVENTS_PATH = RUN_DIR / "events.jsonl"
    SCREENSHOTS_DIR = RUN_DIR / "screenshots"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    config = BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=BrowserEngine.CHROMIUM,
        channel=BrowserChannel.BUNDLED,
        headless=False,
        profile=BrowserProfile.DINGDONG,
    )
    backend = PlaywrightBackend(config)
    sequence = 0
    command_queue = AtomicFileQueue(CONTROL_DIR / "commands")
    started = time.time()
    run_outcome = "failed"
    try:
        backend.start()
        atomic_json(
            STATUS_PATH,
            {
                "state": "ready",
                "started_at_epoch": started,
                "browser": backend.browser_environment(),
            },
        )
        while True:
            claim = command_queue.claim()
            if claim is None:
                time.sleep(0.2)
                continue
            command = claim.payload
            command_id = claim.message_id
            sequence += 1
            kind = str(command["kind"])
            result: dict[str, object] = {
                "command_id": command_id,
                "sequence": sequence,
                "kind": kind,
                "started_at_epoch": time.time(),
            }
            try:
                if kind == "navigate":
                    url = str(command["url"])
                    operation = Operation(
                        operation_id=f"{sequence:04d}-navigate",
                        url=url,
                        timeout_ms=int(command.get("timeout_ms", 45_000)),
                        action=Action(type=ActionType.NAVIGATE),
                    )
                    receipt = execute_operation(operation, backend=backend)
                    result["receipt"] = receipt.to_dict()
                elif kind == "observe":
                    observation = backend.observe_page(
                        PageObservationOptions(
                            freshness_max_age_ms=int(
                                command.get("freshness_max_age_ms", 30_000)
                            )
                        )
                    )
                    observation_path = (
                        RUN_DIR / f"{sequence:04d}_observation_{command_id}.json"
                    )
                    atomic_json(observation_path, observation.to_dict())
                    result["observation_path"] = str(observation_path)
                    result["observation_id"] = observation.observation_id
                    result["url"] = observation.url
                    result["title"] = observation.title
                elif kind in {"fill", "press_key", "click"}:
                    reference = ObservationReference(
                        observation_id=str(command["observation_id"]),
                        element_id=str(command["element_id"]),
                        expected=dict(command.get("expected", {})),
                    )
                    locator = locator_from_dict(dict(command["locator"]))
                    action_type = ActionType(kind)
                    action_kwargs: dict[str, object] = {
                        "type": action_type,
                        "locator": locator,
                    }
                    if kind == "fill":
                        action_kwargs["text"] = str(command["text"])
                    elif kind == "press_key":
                        action_kwargs["key"] = str(command["key"])
                    operation = Operation(
                        operation_id=f"{sequence:04d}-{kind}",
                        url=str(command["url"]),
                        timeout_ms=int(command.get("timeout_ms", 30_000)),
                        action=Action(**action_kwargs),
                    )
                    receipt = execute_operation(
                        operation,
                        backend=backend,
                        observation_reference=reference,
                    )
                    result["receipt"] = receipt.to_dict()
                    result["freshness_validation"] = (
                        (receipt.action_evidence or {}).get(
                            "observation_transaction"
                        )
                    )
                elif kind == "screenshot":
                    result["screenshot"] = backend.capture_screenshot(
                        plan_id="gemini-live-conversation",
                        step_id=f"{sequence:04d}",
                        operation_id=command_id,
                        reason=str(command.get("reason", "evidence")),
                        config=ScreenshotConfig(artifact_root=SCREENSHOTS_DIR),
                    )
                elif kind == "stop":
                    result["state"] = "stopping"
                    result["finished_at_epoch"] = time.time()
                    append_event(result)
                    atomic_json(STATUS_PATH, result)
                    command_queue.complete(claim, result)
                    run_outcome = "completed"
                    break
                else:
                    raise ValueError(f"unknown command kind: {kind}")
                result["state"] = "complete"
            except Exception as exc:
                result["state"] = "error"
                result["error"] = f"{type(exc).__name__}: {exc}"
                result["traceback"] = traceback.format_exc()
            result["finished_at_epoch"] = time.time()
            append_event(result)
            atomic_json(STATUS_PATH, result)
            command_queue.complete(claim, result)
    finally:
        backend.stop()
        run_lease.finish(run_outcome)
        run_lease.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
