import platform

import pytest

from dingdongditch.backends.windows_desktop_backend import (
    DesktopBackendError,
    OwnedWindow,
    WindowsDesktopBackend,
)
from dingdongditch.contract.desktop import (
    ApprovedApplication,
    DesktopActionType,
    WindowSelector,
)


def test_capabilities_are_honest_and_allowlisted():
    caps = WindowsDesktopBackend.capabilities()
    assert caps["domain"] == "windows_desktop"
    assert caps["arbitrary_commands"] is False
    assert caps["coordinate_primary_control"] is False
    assert set(caps["approved_applications"]) == {"explorer", "notepad"}
    assert set(caps["actions"]) == {item.value for item in DesktopActionType}


def test_unsupported_platform_is_gated(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    with pytest.raises(DesktopBackendError) as raised:
        WindowsDesktopBackend()
    assert raised.value.failure_kind == "unsupported_platform"


def test_window_discovery_and_uniqueness(monkeypatch, tmp_path):
    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    backend._owned_windows = {
        1: OwnedWindow(1, "notepad", 101, "test"),
        2: OwnedWindow(2, "notepad", 102, "test"),
    }
    monkeypatch.setattr(
        backend,
        "_window_info",
        lambda handle: {
            "window_handle": handle,
            "window_title": f"Note {handle} - Notepad",
            "process_id": 100 + handle,
        },
    )
    selector = WindowSelector(application=ApprovedApplication.NOTEPAD)
    assert backend.find_windows(selector) == [1, 2]
    with pytest.raises(DesktopBackendError) as raised:
        backend._resolve_window(selector, 100)
    assert raised.value.failure_kind == "window_not_unique"


def test_bounded_wait_reports_timeout(tmp_path):
    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    with pytest.raises(DesktopBackendError) as raised:
        backend._wait_until(
            lambda: False, timeout_ms=100, failure_kind="test_timeout"
        )
    assert raised.value.failure_kind == "test_timeout"


def test_safe_close_ownership_is_ledger_based(tmp_path):
    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    assert backend.owned_window_handles == ()
    backend._owned_windows[44] = OwnedWindow(44, "notepad", 55, "test")
    assert backend.owned_window_handles == (44,)
    assert backend._owned_windows[44].source == "test"
