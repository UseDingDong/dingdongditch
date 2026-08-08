from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dingdongditch import (
    BrowserConfig,
    PublicSessionStatus,
    SessionFailureKind,
    StatefulSessionError,
    StatefulSessionRuntime,
)
from dingdongditch.contract.browser import BrowserConfigError, BrowserFailureKind


def _fake_backend(*, cleanup_error: bool = False):
    backend = MagicMock()
    backend.is_started = True
    backend.page_id = "page-1"
    backend.cleanup_errors = []
    backend.list_pages.return_value = [{
        "page_id": "page-1", "active": True, "current_url": "about:blank",
        "lifecycle_state": "open",
    }]
    if cleanup_error:
        backend.stop.side_effect = RuntimeError("sensitive path must not escape")
    return backend


def test_open_close_idempotent_and_closed_rejection():
    backend = _fake_backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session()
        assert opened.status == PublicSessionStatus.OPEN
        closed = runtime.close_session(opened.session_id)
        assert closed.status == PublicSessionStatus.CLOSED
        assert runtime.close_session(opened.session_id).status == PublicSessionStatus.CLOSED
        with pytest.raises(StatefulSessionError) as raised:
            runtime.inspect_pages(opened.session_id)
        assert raised.value.failure_kind == SessionFailureKind.SESSION_CLOSED
    backend.stop.assert_called_once()


def test_unknown_session_and_expired_cleanup():
    runtime = StatefulSessionRuntime(default_idle_timeout_ms=10)
    with pytest.raises(StatefulSessionError) as raised:
        runtime.get_session("unknown")
    assert raised.value.failure_kind == SessionFailureKind.SESSION_NOT_FOUND

    backend = _fake_backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        opened = runtime.open_session(idle_timeout_ms=1)
        runtime._records[opened.session_id].last_activity_at_ms -= 10
        assert runtime.cleanup_expired_sessions() == (opened.session_id,)
        with pytest.raises(StatefulSessionError) as expired:
            runtime.inspect_pages(opened.session_id)
        assert expired.value.failure_kind == SessionFailureKind.SESSION_EXPIRED


def test_profile_lock_and_startup_errors_are_sanitized():
    failure = BrowserConfigError(
        "C:/secret/profile is locked",
        failure_kind=BrowserFailureKind.PROFILE_IN_USE,
    )
    backend = _fake_backend()
    backend.start.side_effect = failure
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        with pytest.raises(StatefulSessionError) as raised:
            StatefulSessionRuntime().open_session(BrowserConfig(profile="named"))
    assert raised.value.failure_kind == SessionFailureKind.PROFILE_LOCKED
    assert "secret" not in str(raised.value)


def test_cleanup_failure_is_structured_and_redacted():
    backend = _fake_backend(cleanup_error=True)
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session()
        with pytest.raises(StatefulSessionError) as raised:
            runtime.close_session(opened.session_id)
        assert raised.value.failure_kind == SessionFailureKind.CLEANUP_FAILURE
        assert "sensitive" not in str(raised.value)
        assert runtime.get_session(opened.session_id).status == PublicSessionStatus.CLOSED


def test_invalid_page_id_is_structured():
    backend = _fake_backend()
    backend.inspect_page.return_value = None
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session()
        with pytest.raises(StatefulSessionError) as raised:
            runtime.select_page(opened.session_id, "not-there")
        assert raised.value.failure_kind == SessionFailureKind.INVALID_PAGE_ID
        runtime.close_session(opened.session_id)
