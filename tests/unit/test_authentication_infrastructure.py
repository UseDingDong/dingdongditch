import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dingdongditch.authentication import (
    AuthEvent, AuthEventType, AuthenticationCallbacks, AuthenticationCapability,
    AuthenticationError, AuthenticationFailureKind, MappingSecretProvider,
    ProfileManager, redact,
)


def test_profile_create_list_remove_and_corruption(tmp_path):
    manager = ProfileManager(tmp_path)
    info = manager.create("work-1")
    assert info.path.is_dir()
    assert [item.name for item in manager.list()] == ["work-1"]
    (info.path / "profile.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(AuthenticationError) as raised:
        manager.require("work-1")
    assert raised.value.kind is AuthenticationFailureKind.PROFILE_CORRUPT
    (info.path / "profile.json").write_text(json.dumps({"schema_version": 1, "name": "work-1", "created_at": info.created_at}), encoding="utf-8")
    manager.remove("work-1")
    assert not info.path.exists()


@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".", "benchmark"])
def test_profile_names_prevent_traversal_and_reserved_names(tmp_path, name):
    with pytest.raises(AuthenticationError):
        ProfileManager(tmp_path).create(name)


def test_profile_remove_still_validates_caller_supplied_name(tmp_path):
    with pytest.raises(AuthenticationError) as raised:
        ProfileManager(tmp_path).remove("../escape")
    assert raised.value.kind is AuthenticationFailureKind.INVALID_PROFILE_NAME


def test_profile_lock_is_exclusive_and_recoverable(tmp_path):
    manager = ProfileManager(tmp_path)
    manager.create("shared")
    lease = manager.acquire("shared")
    try:
        with pytest.raises(AuthenticationError) as raised:
            manager.acquire("shared")
        assert raised.value.kind is AuthenticationFailureKind.PROFILE_IN_USE
    finally:
        lease.close()
    manager.acquire("shared").close()


def test_concurrent_profile_creation_has_one_winner(tmp_path):
    manager = ProfileManager(tmp_path)
    def create():
        try:
            manager.create("race")
            return True
        except (AuthenticationError, FileExistsError):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: create(), range(2))) == [False, True]


def test_secret_injection_is_runtime_only_and_cleared():
    provider = MappingSecretProvider({"password": "s3cr3t"})
    capability = AuthenticationCapability(secrets=provider)
    locator = MagicMock()
    capability.inject(locator, "password")
    locator.fill.assert_called_once_with("s3cr3t")
    assert "s3cr3t" not in repr(provider.get("password"))
    capability.close()
    with pytest.raises(AuthenticationError):
        provider.get("password")


def test_recursive_redaction_hides_keys_and_values():
    value = {"message": "failed using s3cr3t", "password": "s3cr3t", "nested": ["s3cr3t"]}
    result = redact(value, {"x": "s3cr3t"})
    assert "s3cr3t" not in json.dumps(result)


def test_generic_callbacks_and_safe_callback_failure():
    callbacks = AuthenticationCallbacks()
    seen = []
    callbacks.register(AuthEventType.OTP_REQUESTED, seen.append)
    event = AuthEvent(AuthEventType.OTP_REQUESTED, {"channel": "application"})
    assert callbacks.emit(event) == [None]
    assert seen == [event]
    callbacks.register(AuthEventType.TOTP_REQUESTED, lambda _: 1 / 0)
    with pytest.raises(AuthenticationError) as raised:
        callbacks.emit(AuthEvent(AuthEventType.TOTP_REQUESTED))
    assert "division" not in str(raised.value)


def test_session_export_import_clear_and_invalid_file(tmp_path):
    context = MagicMock()
    context.storage_state.return_value = {"cookies": [], "origins": []}
    context.pages = []
    capability = AuthenticationCapability()
    capability.bind_context(context)
    exported = tmp_path / "session.json"
    capability.export_session(exported)
    capability.import_session(exported)
    context.clear_cookies.assert_called()
    capability.clear_session()
    invalid = tmp_path / "bad.json"
    invalid.write_text('{"schema_version":1,"storage_state":{}}', encoding="utf-8")
    before = context.clear_cookies.call_count
    with pytest.raises(AuthenticationError) as raised:
        capability.import_session(invalid)
    assert raised.value.kind is AuthenticationFailureKind.SESSION_INVALID
    assert context.clear_cookies.call_count == before


def test_session_rejects_unsafe_origin_before_mutating_context(tmp_path):
    context = MagicMock()
    capability = AuthenticationCapability()
    capability.bind_context(context)
    source = tmp_path / "unsafe.json"
    source.write_text(json.dumps({"schema_version": 1, "storage_state": {"cookies": [], "origins": [{"origin": "file:///private", "localStorage": []}]}}), encoding="utf-8")
    with pytest.raises(AuthenticationError) as raised:
        capability.import_session(source)
    assert raised.value.kind is AuthenticationFailureKind.SESSION_INVALID
    context.clear_cookies.assert_not_called()


def test_readiness_failure_and_lease_cleanup(tmp_path):
    manager = ProfileManager(tmp_path)
    manager.create("ready")
    capability = AuthenticationCapability(profiles=manager)
    capability.acquire_profile("ready")
    page = MagicMock()
    page.is_closed.return_value = False
    page.evaluate.side_effect = RuntimeError("not ready")
    with pytest.raises(AuthenticationError) as raised:
        capability.verify_ready(page)
    assert raised.value.kind is AuthenticationFailureKind.NOT_READY
    capability.close()
    manager.acquire("ready").close()
