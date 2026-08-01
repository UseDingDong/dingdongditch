"""Windows-only, allowlisted desktop backend using Microsoft UI Automation."""

from __future__ import annotations

import platform
import threading
import time
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from dingdongditch.runtime.publication import commit_file

from dingdongditch.contract.desktop import (
    ApprovedApplication,
    DesktopAction,
    DesktopActionType,
    DesktopNameMatch,
    UITarget,
    WindowSelector,
)
from dingdongditch.contract.runtime import LifecycleState
from dingdongditch.contract.screenshot import ScreenshotConfig


def monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


class DesktopBackendError(RuntimeError):
    def __init__(self, message: str, *, failure_kind: str) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


@dataclass
class OwnedWindow:
    handle: int
    application: str
    process_id: int
    source: str


@dataclass
class DesktopDispatchResult:
    ok: bool
    started_at_ms: int
    completed_at_ms: int
    failure_kind: str | None
    error: str | None
    evidence: dict[str, Any]


class WindowsDesktopBackend:
    backend_identity = "windows-uia-pywinauto"

    def __init__(self, *, artifact_root: str | Path = "artifacts/desktop") -> None:
        if platform.system() != "Windows":
            raise DesktopBackendError(
                "Windows desktop backend is supported only on Windows",
                failure_kind="unsupported_platform",
            )
        self.artifact_root = Path(artifact_root)
        self.session_id = str(uuid.uuid4())
        self.lifecycle_state = LifecycleState.NOT_STARTED
        self.cleanup_errors: list[dict[str, Any]] = []
        self.telemetry: list[dict[str, Any]] = []
        self._owned_process_ids: set[int] = set()
        self._owned_windows: dict[int, OwnedWindow] = {}
        self._baseline_handles: set[int] = set()
        self._ownership_lock = threading.RLock()
        self._ownership_thread_id: int | None = None
        self._ownership_depth = 0

    @contextmanager
    def exclusive_use(self):
        if not self._ownership_lock.acquire(blocking=False):
            raise DesktopBackendError(
                "desktop backend is already owned by another transaction",
                failure_kind="ownership_violation",
            )
        try:
            thread_id = threading.get_ident()
            if self._ownership_thread_id not in (None, thread_id):
                raise DesktopBackendError(
                    "desktop backend ownership is ambiguous",
                    failure_kind="ownership_violation",
                )
            self._ownership_thread_id = thread_id
            self._ownership_depth += 1
            yield
        finally:
            self._ownership_depth -= 1
            if self._ownership_depth == 0:
                self._ownership_thread_id = None
            self._ownership_lock.release()

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "domain": "windows_desktop",
            "platform": "Windows",
            "provider": "pywinauto",
            "accessibility_backend": "uia",
            "actions": [item.value for item in DesktopActionType],
            "approved_applications": [item.value for item in ApprovedApplication],
            "arbitrary_commands": False,
            "coordinate_primary_control": False,
            "screenshots": True,
        }

    @property
    def is_started(self) -> bool:
        return self.lifecycle_state == LifecycleState.ACTIVE

    @property
    def owned_process_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._owned_process_ids))

    @property
    def owned_window_handles(self) -> tuple[int, ...]:
        return tuple(sorted(self._owned_windows))

    def start(self) -> None:
        with self.exclusive_use():
            self._start()

    def _start(self) -> None:
        if self.is_started:
            return
        self.lifecycle_state = LifecycleState.STARTING
        self._baseline_handles = set(self._top_level_handles())
        self.lifecycle_state = LifecycleState.ACTIVE

    def _native(self):
        from pywinauto import Desktop
        from pywinauto.application import Application
        import win32gui
        import win32process

        return Desktop, Application, win32gui, win32process

    def _top_level_handles(self) -> list[int]:
        Desktop, _, _, _ = self._native()
        handles: list[int] = []
        for wrapper in Desktop(backend="uia").windows():
            try:
                if wrapper.is_visible():
                    handles.append(int(wrapper.handle))
            except Exception:
                continue
        return handles

    def _window_info(self, handle: int) -> dict[str, Any]:
        Desktop, _, win32gui, win32process = self._native()
        wrapper = Desktop(backend="uia").window(handle=handle)
        _, pid = win32process.GetWindowThreadProcessId(handle)
        try:
            title = wrapper.window_text()
        except Exception:
            title = win32gui.GetWindowText(handle)
        try:
            import psutil
            process_name = psutil.Process(pid).name()
        except Exception:
            process_name = ""
        return {
            "window_handle": int(handle),
            "window_title": title,
            "process_id": int(pid),
            "process_identity": str(process_name),
            "visible": bool(wrapper.is_visible()),
            "enabled": bool(wrapper.is_enabled()),
        }

    def _foreground_handle(self) -> int:
        _, _, win32gui, _ = self._native()
        return int(win32gui.GetForegroundWindow())

    def _wait_until(
        self, predicate: Callable[[], Any], *, timeout_ms: int, failure_kind: str
    ) -> Any:
        deadline = monotonic_ms() + timeout_ms
        last_error: Exception | None = None
        while monotonic_ms() <= deadline:
            try:
                value = predicate()
                if value:
                    return value
            except DesktopBackendError:
                raise
            except Exception as exc:
                last_error = exc
            time.sleep(0.1)
        detail = f": {last_error}" if last_error else ""
        raise DesktopBackendError(
            f"bounded desktop wait expired after {timeout_ms}ms{detail}",
            failure_kind=failure_kind,
        )

    @staticmethod
    def _application_matches(selector: WindowSelector, info: dict[str, Any]) -> bool:
        if selector.application is None:
            return True
        title = info["window_title"].lower()
        process = str(info.get("process_identity") or "").lower()
        if selector.application == ApprovedApplication.EXPLORER:
            return process == "explorer.exe"
        if selector.application == ApprovedApplication.NOTEPAD:
            return process == "notepad.exe"
        return False

    def _matches_selector(self, selector: WindowSelector, handle: int) -> bool:
        if selector.owned_only and handle not in self._owned_windows:
            return False
        try:
            info = self._window_info(handle)
        except Exception:
            return False
        if selector.application is not None:
            owned = self._owned_windows.get(handle)
            if owned and owned.application != selector.application.value:
                return False
            if not owned and not self._application_matches(selector, info):
                return False
        if selector.title:
            actual = info["window_title"]
            if selector.title_match == DesktopNameMatch.EXACT:
                if actual != selector.title:
                    return False
            elif selector.title.lower() not in actual.lower():
                return False
        return True

    def find_windows(self, selector: WindowSelector) -> list[int]:
        selector.validate()
        handles = (
            list(self._owned_windows)
            if selector.owned_only
            else self._top_level_handles()
        )
        return [handle for handle in handles if self._matches_selector(selector, handle)]

    def _resolve_window(self, selector: WindowSelector, timeout_ms: int) -> int:
        def discover() -> int | bool:
            matches = self.find_windows(selector)
            if selector.require_unique and len(matches) > 1:
                raise DesktopBackendError(
                    f"window selector matched {len(matches)} windows",
                    failure_kind="window_not_unique",
                )
            return matches[0] if matches else False

        return int(
            self._wait_until(
                discover, timeout_ms=timeout_ms, failure_kind="window_timeout"
            )
        )

    def _register_new_window(
        self,
        *,
        before: set[int],
        application: ApprovedApplication,
        timeout_ms: int,
        source: str,
        expected_title: str | None = None,
        expected_process_id: int | None = None,
    ) -> int:
        def discover() -> int | bool:
            candidates = []
            for handle in self._top_level_handles():
                if handle in before or handle in self._owned_windows:
                    continue
                try:
                    info = self._window_info(handle)
                    if (
                        expected_process_id is not None
                        and info["process_id"] != expected_process_id
                    ):
                        continue
                    title = info["window_title"]
                    if expected_title and expected_title.lower() not in title.lower():
                        continue
                    if application == ApprovedApplication.NOTEPAD and "notepad" not in title.lower():
                        continue
                    candidates.append((handle, info))
                except Exception:
                    continue
            if len(candidates) > 1:
                raise DesktopBackendError(
                    f"launch produced {len(candidates)} candidate windows",
                    failure_kind="window_not_unique",
                )
            if not candidates:
                return False
            handle, info = candidates[0]
            self._owned_windows[handle] = OwnedWindow(
                handle=handle,
                application=application.value,
                process_id=info["process_id"],
                source=source,
            )
            self._owned_process_ids.add(info["process_id"])
            return handle

        return int(
            self._wait_until(
                discover,
                timeout_ms=timeout_ms,
                failure_kind="window_timeout",
            )
        )

    def _launch(self, application: ApprovedApplication, timeout_ms: int) -> dict[str, Any]:
        Desktop, Application, _, _ = self._native()
        before = set(self._top_level_handles())
        command = {
            ApprovedApplication.EXPLORER: "explorer.exe /separate",
            ApprovedApplication.NOTEPAD: "notepad.exe",
        }[application]
        app = Application(backend="uia").start(command, timeout=timeout_ms / 1000)
        launched_pid = int(app.process)
        self._owned_process_ids.add(launched_pid)
        handle = self._register_new_window(
            before=before,
            application=application,
            timeout_ms=timeout_ms,
            source="launch_application",
            expected_process_id=launched_pid,
        )
        info = self._window_info(handle)
        return {
            "requested_application": application.value,
            "resolved_executable": command.split()[0],
            "launched_process_id": launched_pid,
            **info,
            "cleanup_ownership_status": "session_owned",
        }

    def _open_explorer(self, path: str, timeout_ms: int) -> dict[str, Any]:
        Desktop, _, _, _ = self._native()
        candidate = Path(path).resolve()
        handle = self._resolve_window(
            WindowSelector(application=ApprovedApplication.EXPLORER),
            timeout_ms,
        )
        window = Desktop(backend="uia").window(handle=handle)
        window.set_focus()
        # Explorer exposes navigation focus via Ctrl+L and an accessible Edit.
        window.type_keys("^l", set_foreground=True)
        edit = self._wait_until(
            lambda: next(
                (
                    item
                    for item in window.descendants(control_type="Edit")
                    if item.is_visible() and item.is_enabled()
                ),
                False,
            ),
            timeout_ms=timeout_ms,
            failure_kind="explorer_address_not_found",
        )
        edit.set_edit_text(str(candidate))
        edit.type_keys("{ENTER}")
        self._wait_until(
            lambda: candidate.name.lower() in window.window_text().lower(),
            timeout_ms=timeout_ms,
            failure_kind="explorer_navigation_timeout",
        )
        info = self._window_info(handle)
        return {
            "requested_path": str(candidate),
            "resolved_executable": "explorer.exe",
            "launched_process_id": self._owned_windows[handle].process_id,
            **info,
            "cleanup_ownership_status": "session_owned",
            "navigation_method": "uia_address_edit",
        }

    def _target_matches(self, wrapper: Any, target: UITarget) -> bool:
        try:
            if wrapper.element_info.control_type != target.control_type:
                return False
            name = wrapper.window_text()
            return (
                name == target.name
                if target.name_match == DesktopNameMatch.EXACT
                else target.name.lower() in name.lower()
            )
        except Exception:
            return False

    def _find_targets(self, handle: int, target: UITarget) -> list[Any]:
        Desktop, _, _, _ = self._native()
        window = Desktop(backend="uia").window(handle=handle)
        return [
            item
            for item in window.descendants()
            if self._target_matches(item, target)
        ]

    def _verify_expected(
        self, action: DesktopAction, handle: int | None
    ) -> tuple[bool, dict[str, Any]]:
        expected = action.expected
        present = handle is not None and handle in self._top_level_handles()
        result: dict[str, Any] = {
            "window_present": {
                "expected": expected.window_present,
                "actual": present,
                "passed": present == expected.window_present,
            }
        }
        passed = result["window_present"]["passed"]
        if expected.focused is not None:
            actual = present and self._foreground_handle() == handle
            result["focused"] = {
                "expected": expected.focused,
                "actual": actual,
                "passed": actual == expected.focused,
            }
            passed = passed and result["focused"]["passed"]
        if expected.visible_target and handle is not None:
            matches = self._find_targets(handle, expected.visible_target)
            actual = len(matches) == 1 if expected.visible_target.require_unique else bool(matches)
            result["visible_target"] = {
                "expected": expected.visible_target.describe(),
                "match_count": len(matches),
                "passed": actual,
            }
            passed = passed and actual
        if expected.path is not None and handle is not None:
            # Explorer exposes the current location through an Address control.
            path_name = str(Path(expected.path).resolve())
            names = []
            Desktop, _, _, _ = self._native()
            window = Desktop(backend="uia").window(handle=handle)
            for item in window.descendants(control_type="Edit"):
                try:
                    names.append(item.get_value())
                except Exception:
                    continue
            actual = any(
                value and (
                    path_name.lower() in value.lower()
                    or Path(path_name).name.lower() in value.lower()
                )
                for value in names
            )
            result["path"] = {
                "expected": path_name,
                "accessibility_values": names,
                "passed": actual,
            }
            passed = passed and actual
        return passed, result

    def dispatch(self, action: DesktopAction) -> DesktopDispatchResult:
        with self.exclusive_use():
            return self._dispatch(action)

    def _dispatch(self, action: DesktopAction) -> DesktopDispatchResult:
        action.validate()
        if not self.is_started:
            raise DesktopBackendError(
                "desktop backend is not active", failure_kind="backend_not_active"
            )
        started = monotonic_ms()
        previous_foreground = self._foreground_handle()
        evidence: dict[str, Any] = {
            "requested": action.describe(),
            "previous_foreground_window": previous_foreground,
        }
        handle: int | None = None
        try:
            if action.type == DesktopActionType.LAUNCH_APPLICATION:
                assert action.application
                evidence.update(self._launch(action.application, action.timeout_ms))
                handle = evidence["window_handle"]
            elif action.type == DesktopActionType.OPEN_PATH_IN_EXPLORER:
                assert action.path
                evidence.update(self._open_explorer(action.path, action.timeout_ms))
                handle = evidence["window_handle"]
            elif action.type == DesktopActionType.WAIT_FOR_WINDOW:
                assert action.window
                handle = self._resolve_window(action.window, action.timeout_ms)
                evidence.update(self._window_info(handle))
            elif action.type == DesktopActionType.FOCUS_WINDOW:
                assert action.window
                handle = self._resolve_window(action.window, action.timeout_ms)
                Desktop, _, _, _ = self._native()
                Desktop(backend="uia").window(handle=handle).set_focus()
                self._wait_until(
                    lambda: self._foreground_handle() == handle,
                    timeout_ms=action.timeout_ms,
                    failure_kind="focus_timeout",
                )
                evidence.update(self._window_info(handle))
            elif action.type == DesktopActionType.ACTIVATE_UI_TARGET:
                assert action.window and action.target
                handle = self._resolve_window(action.window, action.timeout_ms)
                matches = self._find_targets(handle, action.target)
                if action.target.require_unique and len(matches) != 1:
                    raise DesktopBackendError(
                        f"UI target matched {len(matches)} controls",
                        failure_kind=(
                            "ui_target_not_found" if not matches else "ui_target_not_unique"
                        ),
                    )
                if not matches:
                    raise DesktopBackendError(
                        "UI target not found", failure_kind="ui_target_not_found"
                    )
                target = matches[0]
                before = set(self._top_level_handles())
                props = {
                    "name": target.window_text(),
                    "control_type": target.element_info.control_type,
                    "automation_id": target.element_info.automation_id,
                    "class_name": target.element_info.class_name,
                }
                try:
                    target.invoke()
                    activation_method = "uia_invoke"
                except Exception:
                    target.double_click_input()
                    activation_method = "uia_resolved_double_click"
                evidence["target_uia_properties"] = props
                evidence["activation_method"] = activation_method
                if action.expected.window_present:
                    new_handle = self._register_new_window(
                        before=before,
                        application=ApprovedApplication.NOTEPAD,
                        timeout_ms=action.timeout_ms,
                        source="activate_ui_target",
                    )
                    handle = new_handle
                    evidence["activated_window"] = self._window_info(new_handle)
            elif action.type == DesktopActionType.CLOSE_WINDOW:
                assert action.window
                handle = self._resolve_window(action.window, action.timeout_ms)
                owned = self._owned_windows.get(handle)
                if owned is None:
                    raise DesktopBackendError(
                        "refusing to close a window not owned by this session",
                        failure_kind="ownership_violation",
                    )
                Desktop, _, _, _ = self._native()
                Desktop(backend="uia").window(handle=handle).close()
                self._wait_until(
                    lambda: handle not in self._top_level_handles(),
                    timeout_ms=action.timeout_ms,
                    failure_kind="close_timeout",
                )
                self._owned_windows.pop(handle, None)
                evidence.update(
                    {
                        "window_handle": handle,
                        "process_id": owned.process_id,
                        "cleanup_ownership_status": "session_owned_closed",
                    }
                )
            passed, verification = self._verify_expected(action, handle)
            evidence["verification_result"] = verification
            evidence["final_foreground_window"] = self._foreground_handle()
            evidence["execution_duration_ms"] = monotonic_ms() - started
            return DesktopDispatchResult(
                ok=passed,
                started_at_ms=started,
                completed_at_ms=monotonic_ms(),
                failure_kind=None if passed else "verification_failed",
                error=None if passed else "expected desktop post-action state not verified",
                evidence=evidence,
            )
        except DesktopBackendError as exc:
            evidence["final_foreground_window"] = self._foreground_handle()
            evidence["execution_duration_ms"] = monotonic_ms() - started
            return DesktopDispatchResult(
                ok=False,
                started_at_ms=started,
                completed_at_ms=monotonic_ms(),
                failure_kind=exc.failure_kind,
                error=str(exc),
                evidence=evidence,
            )
        except Exception as exc:
            evidence["final_foreground_window"] = self._foreground_handle()
            evidence["execution_duration_ms"] = monotonic_ms() - started
            return DesktopDispatchResult(
                ok=False,
                started_at_ms=started,
                completed_at_ms=monotonic_ms(),
                failure_kind="desktop_action_failed",
                error=str(exc),
                evidence=evidence,
            )

    def capture_screenshot(
        self,
        *,
        plan_id: str,
        operation_id: str,
        reason: str,
        config: ScreenshotConfig,
    ) -> dict[str, Any]:
        from PIL import ImageGrab

        root = Path(config.artifact_root)
        root.mkdir(parents=True, exist_ok=True)
        name = f"{plan_id}__{operation_id}__{reason}__{self.session_id}.png"
        path = root / name
        temporary = root / f".{name}.{uuid.uuid4().hex}.tmp"
        image = ImageGrab.grab(all_screens=True)
        try:
            image.save(temporary, "PNG")
            commit_file(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "path": str(path.resolve()),
            "reason": reason,
            "width": image.width,
            "height": image.height,
            "captured_at_ms": monotonic_ms(),
        }

    def _pid_exists(self, pid: int) -> bool:
        import win32api
        import win32con

        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            win32api.CloseHandle(handle)
            return True
        except Exception:
            return False

    def remaining_owned_process_ids(self) -> list[int]:
        live_window_pids = {
            item.process_id
            for item in self._owned_windows.values()
            if item.handle in self._top_level_handles()
        }
        return sorted(pid for pid in self._owned_process_ids if pid in live_window_pids)

    def stop(self) -> None:
        with self.exclusive_use():
            self._stop()

    def _stop(self) -> None:
        if self.lifecycle_state == LifecycleState.STOPPED:
            return
        self.lifecycle_state = LifecycleState.STOPPING
        Desktop, _, _, _ = self._native()
        for handle, owned in list(self._owned_windows.items()):
            try:
                if handle in self._top_level_handles():
                    Desktop(backend="uia").window(handle=handle).close()
                    self._wait_until(
                        lambda h=handle: h not in self._top_level_handles(),
                        timeout_ms=5_000,
                        failure_kind="cleanup_close_timeout",
                    )
                self._owned_windows.pop(handle, None)
            except Exception as exc:
                self.cleanup_errors.append(
                    {
                        "window_handle": handle,
                        "process_id": owned.process_id,
                        "error": str(exc),
                    }
                )
        self.lifecycle_state = (
            LifecycleState.STOPPED
            if not self.cleanup_errors
            else LifecycleState.FAILED
        )
