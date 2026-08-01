from __future__ import annotations

from dingdongditch.backends.playwright_backend import PlaywrightBackend


def test_new_backend_generation_drops_all_previous_owned_state():
    backend = PlaywrightBackend()
    backend._pages["old"] = object()
    backend._page_ids_by_object[1] = "old"
    backend._dialog_history.append({"old": True})
    backend._network.append(object())
    backend.telemetry.append({"event": "old"})
    backend.terminal_session_identity = {"browser_session_id": "old"}
    backend._prepare_new_generation()
    assert backend._pages == {}
    assert backend._page_ids_by_object == {}
    assert backend._dialog_history == []
    assert backend._network == []
    assert backend.telemetry == []
    assert backend.terminal_session_identity is None


def test_stop_is_idempotent_before_and_after_a_session():
    backend = PlaywrightBackend()
    initial = backend.lifecycle_state
    backend.stop()
    assert backend.lifecycle_state == initial
    backend.stop()
    assert backend.lifecycle_state == initial
