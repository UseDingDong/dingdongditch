"""Fail-closed contracts for the minimal Windows desktop execution domain."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from dingdongditch.contract.plan import FailurePolicy
from dingdongditch.contract.screenshot import ScreenshotConfig


class DesktopActionType(str, Enum):
    LAUNCH_APPLICATION = "launch_application"
    OPEN_PATH_IN_EXPLORER = "open_path_in_explorer"
    WAIT_FOR_WINDOW = "wait_for_window"
    FOCUS_WINDOW = "focus_window"
    ACTIVATE_UI_TARGET = "activate_ui_target"
    CLOSE_WINDOW = "close_window"


class ApprovedApplication(str, Enum):
    EXPLORER = "explorer"
    NOTEPAD = "notepad"


class DesktopNameMatch(str, Enum):
    EXACT = "exact"
    CONTAINS = "contains"


class SafeClosePolicy(str, Enum):
    WINDOW_CLOSE = "window_close"


@dataclass(frozen=True)
class WindowSelector:
    application: ApprovedApplication | None = None
    title: str | None = None
    title_match: DesktopNameMatch = DesktopNameMatch.CONTAINS
    owned_only: bool = True
    require_unique: bool = True

    def validate(self) -> None:
        if self.application is None and not (self.title and self.title.strip()):
            raise ValueError("window selector requires application or title")
        if not isinstance(self.owned_only, bool) or not isinstance(
            self.require_unique, bool
        ):
            raise ValueError("window selector boolean fields must be bool")

    def describe(self) -> dict[str, Any]:
        return {
            "application": self.application.value if self.application else None,
            "title": self.title,
            "title_match": self.title_match.value,
            "owned_only": self.owned_only,
            "require_unique": self.require_unique,
        }


@dataclass(frozen=True)
class UITarget:
    name: str
    control_type: str
    name_match: DesktopNameMatch = DesktopNameMatch.EXACT
    require_unique: bool = True

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("UI target name is required")
        if not self.control_type or not self.control_type.strip():
            raise ValueError("UI target control_type is required")

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "control_type": self.control_type,
            "name_match": self.name_match.value,
            "require_unique": self.require_unique,
        }


@dataclass(frozen=True)
class DesktopExpectedState:
    window_present: bool = True
    focused: bool | None = None
    path: str | None = None
    visible_target: UITarget | None = None

    def validate(self) -> None:
        if not isinstance(self.window_present, bool):
            raise ValueError("window_present must be bool")
        if self.focused is not None and not isinstance(self.focused, bool):
            raise ValueError("focused must be bool or None")
        if self.path is not None and not Path(self.path).is_absolute():
            raise ValueError("expected path must be absolute")
        if self.visible_target:
            self.visible_target.validate()

    def describe(self) -> dict[str, Any]:
        return {
            "window_present": self.window_present,
            "focused": self.focused,
            "path": self.path,
            "visible_target": (
                self.visible_target.describe() if self.visible_target else None
            ),
        }


@dataclass(frozen=True)
class DesktopAction:
    type: DesktopActionType
    application: ApprovedApplication | None = None
    path: str | None = None
    window: WindowSelector | None = None
    target: UITarget | None = None
    timeout_ms: int = 10_000
    expected: DesktopExpectedState = field(default_factory=DesktopExpectedState)
    close_policy: SafeClosePolicy = SafeClosePolicy.WINDOW_CLOSE

    def validate(self) -> None:
        if not isinstance(self.timeout_ms, int) or isinstance(self.timeout_ms, bool):
            raise ValueError("desktop timeout_ms must be an int")
        if not 100 <= self.timeout_ms <= 120_000:
            raise ValueError("desktop timeout_ms must be between 100 and 120000")
        self.expected.validate()
        if self.type == DesktopActionType.LAUNCH_APPLICATION:
            if self.application not in (ApprovedApplication.EXPLORER, ApprovedApplication.NOTEPAD):
                raise ValueError("launch_application requires an approved application")
            if any((self.path, self.window, self.target)):
                raise ValueError("launch_application does not accept path/window/target")
        elif self.type == DesktopActionType.OPEN_PATH_IN_EXPLORER:
            if not self.path:
                raise ValueError("open_path_in_explorer requires path")
            candidate = Path(self.path)
            if not candidate.is_absolute():
                raise ValueError("Explorer path must be absolute")
            if not candidate.exists() or not candidate.is_dir():
                raise ValueError("Explorer path must be an existing directory")
            if self.application is not None or self.window or self.target:
                raise ValueError("open_path_in_explorer accepts only path")
        elif self.type in (
            DesktopActionType.WAIT_FOR_WINDOW,
            DesktopActionType.FOCUS_WINDOW,
            DesktopActionType.CLOSE_WINDOW,
        ):
            if self.window is None:
                raise ValueError(f"{self.type.value} requires window selector")
            self.window.validate()
            if self.application is not None or self.path or self.target:
                raise ValueError(f"{self.type.value} accepts only window selector")
            if self.type == DesktopActionType.CLOSE_WINDOW and not self.window.owned_only:
                raise ValueError("close_window requires owned_only=true")
        elif self.type == DesktopActionType.ACTIVATE_UI_TARGET:
            if self.window is None or self.target is None:
                raise ValueError("activate_ui_target requires window and target")
            self.window.validate()
            self.target.validate()
            if self.application is not None or self.path:
                raise ValueError("activate_ui_target does not accept application/path")
        else:
            raise ValueError(f"unsupported desktop action: {self.type!r}")

    def describe(self) -> dict[str, Any]:
        self.validate()
        return {
            "type": self.type.value,
            "application": self.application.value if self.application else None,
            "path": self.path,
            "window": self.window.describe() if self.window else None,
            "target": self.target.describe() if self.target else None,
            "timeout_ms": self.timeout_ms,
            "expected": self.expected.describe(),
            "close_policy": self.close_policy.value,
        }


@dataclass(frozen=True)
class DesktopOperation:
    operation_id: str
    action: DesktopAction
    screenshot_config: ScreenshotConfig | None = None

    def validate(self) -> None:
        if not self.operation_id or not self.operation_id.strip():
            raise ValueError("operation_id is required")
        self.action.validate()
        if self.screenshot_config:
            self.screenshot_config.validate()

    def describe(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "action": self.action.describe(),
            "screenshot_config": (
                self.screenshot_config.describe() if self.screenshot_config else None
            ),
        }


@dataclass(frozen=True)
class DesktopExecutionPlan:
    plan_id: str
    operations: tuple[DesktopOperation, ...]
    failure_policy: FailurePolicy = FailurePolicy.STOP_ON_FAILURE
    screenshot_config: ScreenshotConfig | None = None

    def validate(self) -> None:
        if not self.plan_id or not self.plan_id.strip():
            raise ValueError("plan_id is required")
        if not self.operations:
            raise ValueError("desktop plan requires at least one operation")
        if self.failure_policy != FailurePolicy.STOP_ON_FAILURE:
            raise ValueError("only stop_on_failure is supported")
        ids = [item.operation_id for item in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate operation_id values")
        if self.screenshot_config:
            self.screenshot_config.validate()
        for operation in self.operations:
            operation.validate()

    def describe(self) -> dict[str, Any]:
        self.validate()
        return {
            "domain": "windows_desktop",
            "plan_id": self.plan_id,
            "operations": [item.describe() for item in self.operations],
            "failure_policy": self.failure_policy.value,
            "screenshot_config": (
                self.screenshot_config.describe() if self.screenshot_config else None
            ),
        }
