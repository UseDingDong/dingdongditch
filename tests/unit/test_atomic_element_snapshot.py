from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import Error as PlaywrightError

from dingdongditch import BrowserConfig, Locator, LocatorStrategy
from dingdongditch.backends.element_snapshot import (
    ElementStateSnapshot,
    SnapshotAvailability,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


def locator() -> Locator:
    return Locator(strategy=LocatorStrategy.CSS, value="#target")


def resolved(handle=None, *, count=1, ok=True):
    return SimpleNamespace(
        match_count=count,
        ok=ok,
        playwright_locator=handle,
        trace=SimpleNamespace(to_dict=lambda: {"final_candidate_count": count}),
    )


def atomic_payload(**overrides):
    value = {
        "supported": True,
        "connected": True,
        "visible": True,
        "enabled": True,
        "in_viewport": True,
        "checked": False,
        "selected": None,
        "focused": True,
        "text": "target",
        "value": "live",
        "role": "textbox",
        "bounding_box": {"x": 1, "y": 2, "width": 3, "height": 4},
        "attributes": {"id": "target", "value": "live"},
    }
    value.update(overrides)
    return value


def test_atomic_snapshot_uses_one_evaluation_and_no_serial_queries():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    handle = MagicMock()
    handle.evaluate.return_value = atomic_payload()
    backend._resolve_scoped_target = MagicMock(return_value=resolved(handle))

    snapshot = backend.capture_element_snapshot(locator())

    assert isinstance(snapshot, ElementStateSnapshot)
    assert snapshot.availability == SnapshotAvailability.AVAILABLE
    assert snapshot.visible is True
    assert snapshot.focused is True
    assert snapshot.role == "textbox"
    assert snapshot.bounding_box == {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0}
    assert handle.evaluate.call_count == 1
    handle.is_visible.assert_not_called()
    handle.is_enabled.assert_not_called()
    handle.get_attribute.assert_not_called()
    handle.input_value.assert_not_called()
    assert backend._atomic_snapshot_count == 1
    assert backend._atomic_snapshot_fallback_count == 0


def test_missing_and_ambiguous_snapshots_preserve_legacy_shape():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    backend._resolve_scoped_target = MagicMock(return_value=resolved(None, count=0, ok=False))
    missing = backend.read_element_state(locator())
    assert missing == {
        "match_count": 0,
        "exists": False,
        "target_resolution": {"final_candidate_count": 0},
    }

    backend._resolve_scoped_target = MagicMock(return_value=resolved(None, count=2, ok=False))
    ambiguous = backend.read_element_state(locator())
    assert ambiguous == {
        "match_count": 2,
        "exists": True,
        "ambiguous": True,
        "target_resolution": {"final_candidate_count": 2},
    }


def test_explicit_unsupported_result_uses_and_records_serial_fallback():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    handle = MagicMock()
    handle.evaluate.side_effect = [
        {"supported": False, "error": "unsupported test engine"},
        True,
    ]
    handle.is_visible.return_value = True
    handle.is_enabled.return_value = False
    handle.inner_text.return_value = "fallback"
    handle.get_attribute.return_value = None
    handle.input_value.side_effect = PlaywrightError("not an input")
    handle.is_checked.side_effect = PlaywrightError("not checkable")
    backend._resolve_scoped_target = MagicMock(return_value=resolved(handle))

    state = backend.read_element_state(locator())

    assert state["visible"] is True
    assert state["enabled"] is False
    assert state["text"] == "fallback"
    assert backend._atomic_snapshot_count == 0
    assert backend._atomic_snapshot_fallback_count == 1
    assert backend.telemetry[-1]["event"] == "atomic_element_snapshot_fallback"


def test_detachment_or_navigation_race_does_not_fallback_to_new_state():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    handle = MagicMock()
    handle.evaluate.side_effect = PlaywrightError("Execution context was destroyed")
    backend._resolve_scoped_target = MagicMock(return_value=resolved(handle))

    with pytest.raises(PlaywrightError, match="context was destroyed"):
        backend.capture_element_snapshot(locator())

    assert backend._atomic_snapshot_fallback_count == 0
    handle.is_visible.assert_not_called()


def test_detached_atomic_result_is_unavailable_without_retry_or_fallback():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    handle = MagicMock()
    handle.evaluate.return_value = atomic_payload(connected=False)
    backend._resolve_scoped_target = MagicMock(return_value=resolved(handle))

    snapshot = backend.capture_element_snapshot(locator())

    assert snapshot.availability == SnapshotAvailability.UNAVAILABLE
    assert snapshot.match_count == 1
    assert snapshot.exists is True
    assert snapshot.visible is None
    assert snapshot.error == "element detached during atomic snapshot"
    assert handle.evaluate.call_count == 1
    assert backend._resolve_scoped_target.call_count == 1
    assert backend._atomic_snapshot_fallback_count == 0
