from pathlib import Path

import pytest

from dingdongditch.contract.browser import BrowserConfig
from dingdongditch.contract.desktop import (
    ApprovedApplication,
    DesktopAction,
    DesktopActionType,
    DesktopExecutionPlan,
    DesktopExpectedState,
    DesktopOperation,
    UITarget,
    WindowSelector,
)
from dingdongditch.contract.operation import Action, ActionType, Operation
from dingdongditch.contract.plan import ExecutionPlan


def test_launch_requires_approved_application():
    with pytest.raises(ValueError, match="approved application"):
        DesktopAction(type=DesktopActionType.LAUNCH_APPLICATION).validate()


def test_open_path_rejects_missing_and_non_directory(tmp_path):
    with pytest.raises(ValueError, match="requires path"):
        DesktopAction(type=DesktopActionType.OPEN_PATH_IN_EXPLORER).validate()
    file_path = tmp_path / "file.txt"
    file_path.write_text("safe", encoding="utf-8")
    with pytest.raises(ValueError, match="existing directory"):
        DesktopAction(
            type=DesktopActionType.OPEN_PATH_IN_EXPLORER,
            path=str(file_path.resolve()),
        ).validate()


def test_close_requires_owned_selector():
    with pytest.raises(ValueError, match="owned_only"):
        DesktopAction(
            type=DesktopActionType.CLOSE_WINDOW,
            window=WindowSelector(
                application=ApprovedApplication.NOTEPAD, owned_only=False
            ),
            expected=DesktopExpectedState(window_present=False),
        ).validate()


def test_target_and_timeout_validation():
    with pytest.raises(ValueError, match="control_type"):
        UITarget(name="hello.txt", control_type="").validate()
    with pytest.raises(ValueError, match="between"):
        DesktopAction(
            type=DesktopActionType.LAUNCH_APPLICATION,
            application=ApprovedApplication.NOTEPAD,
            timeout_ms=0,
        ).validate()


def test_duplicate_operations_rejected():
    action = DesktopAction(
        type=DesktopActionType.LAUNCH_APPLICATION,
        application=ApprovedApplication.NOTEPAD,
    )
    plan = DesktopExecutionPlan(
        plan_id="duplicate",
        operations=(
            DesktopOperation("same", action),
            DesktopOperation("same", action),
        ),
    )
    with pytest.raises(ValueError, match="duplicate"):
        plan.validate()


def test_existing_browser_plan_remains_valid():
    plan = ExecutionPlan(
        plan_id="browser-backward-compatible",
        browser_config=BrowserConfig(),
        operations=[
            Operation(
                operation_id="navigate",
                url="about:blank",
                action=Action(type=ActionType.NAVIGATE),
            )
        ],
    )
    plan.validate()
