"""Fresh ExecutionPlan-only Windows desktop vertical-slice benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from dingdongditch.contract.desktop import (
    ApprovedApplication,
    DesktopAction,
    DesktopActionType,
    DesktopExecutionPlan,
    DesktopExpectedState,
    DesktopNameMatch,
    DesktopOperation,
    UITarget,
    WindowSelector,
)
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.runtime.desktop_executor import execute_desktop_plan


RUN_ROOT = Path(__file__).resolve().parent
TEST_FOLDER = (RUN_ROOT / "desktop_test_folder").resolve()
FILE_NAME = "hello_from_dingdongditch.txt"
UNIQUE_TEXT = "Hello from the DingDongDitch Windows desktop benchmark."
SCREENSHOTS = RUN_ROOT / "screenshots"

explorer = WindowSelector(application=ApprovedApplication.EXPLORER)
notepad = WindowSelector(application=ApprovedApplication.NOTEPAD)

plan = DesktopExecutionPlan(
    plan_id="windows-desktop-vertical-slice-20260728-231500",
    screenshot_config=ScreenshotConfig(
        policy=ScreenshotPolicy.AFTER_SUCCESS,
        artifact_root=str(SCREENSHOTS),
        max_per_operation=1,
        max_per_plan=16,
    ),
    operations=(
        DesktopOperation(
            "launch-explorer",
            DesktopAction(
                type=DesktopActionType.LAUNCH_APPLICATION,
                application=ApprovedApplication.EXPLORER,
                timeout_ms=15_000,
                expected=DesktopExpectedState(window_present=True, focused=True),
            ),
        ),
        DesktopOperation(
            "navigate-controlled-folder",
            DesktopAction(
                type=DesktopActionType.OPEN_PATH_IN_EXPLORER,
                path=str(TEST_FOLDER),
                timeout_ms=15_000,
                expected=DesktopExpectedState(
                    window_present=True,
                    focused=True,
                    path=str(TEST_FOLDER),
                    visible_target=UITarget(
                        name=FILE_NAME,
                        control_type="ListItem",
                    ),
                ),
            ),
        ),
        DesktopOperation(
            "activate-test-file",
            DesktopAction(
                type=DesktopActionType.ACTIVATE_UI_TARGET,
                window=explorer,
                target=UITarget(name=FILE_NAME, control_type="ListItem"),
                timeout_ms=15_000,
                expected=DesktopExpectedState(
                    window_present=True,
                    focused=True,
                    visible_target=UITarget(
                        name=UNIQUE_TEXT,
                        control_type="Document",
                        name_match=DesktopNameMatch.CONTAINS,
                    ),
                ),
            ),
        ),
        DesktopOperation(
            "close-associated-text-app",
            DesktopAction(
                type=DesktopActionType.CLOSE_WINDOW,
                window=notepad,
                timeout_ms=10_000,
                expected=DesktopExpectedState(window_present=False),
            ),
        ),
        DesktopOperation(
            "launch-notepad",
            DesktopAction(
                type=DesktopActionType.LAUNCH_APPLICATION,
                application=ApprovedApplication.NOTEPAD,
                timeout_ms=15_000,
                expected=DesktopExpectedState(window_present=True, focused=True),
            ),
        ),
        DesktopOperation(
            "verify-notepad-focused",
            DesktopAction(
                type=DesktopActionType.FOCUS_WINDOW,
                window=notepad,
                timeout_ms=10_000,
                expected=DesktopExpectedState(window_present=True, focused=True),
            ),
        ),
        DesktopOperation(
            "close-notepad",
            DesktopAction(
                type=DesktopActionType.CLOSE_WINDOW,
                window=notepad,
                timeout_ms=10_000,
                expected=DesktopExpectedState(window_present=False),
            ),
        ),
        DesktopOperation(
            "close-explorer",
            DesktopAction(
                type=DesktopActionType.CLOSE_WINDOW,
                window=explorer,
                timeout_ms=10_000,
                expected=DesktopExpectedState(window_present=False),
            ),
        ),
    ),
)

receipt = execute_desktop_plan(plan)
(RUN_ROOT / "execution_plan.json").write_text(
    json.dumps(plan.describe(), indent=2), encoding="utf-8"
)
(RUN_ROOT / "final_receipt.json").write_text(
    json.dumps(receipt.to_dict(), indent=2), encoding="utf-8"
)
(RUN_ROOT / "run_summary.json").write_text(
    json.dumps(
        {
            "plan_verdict": receipt.plan_verdict.value,
            "verified_steps": receipt.verified_step_count,
            "declared_steps": receipt.declared_step_count,
            "screenshot_count": sum(len(item.screenshots) for item in receipt.steps),
            "receipt_count": len(receipt.steps),
            "cleanup_errors": receipt.lifecycle["cleanup_errors"],
            "remaining_owned_process_ids": receipt.lifecycle[
                "remaining_owned_process_ids"
            ],
        },
        indent=2,
    ),
    encoding="utf-8",
)
print(json.dumps(receipt.to_dict(), indent=2))
