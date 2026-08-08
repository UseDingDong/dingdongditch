from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from dingdongditch.authentication import (
    AuthenticationCapability,
    AuthenticationError,
    AuthenticationFailureKind,
    PortableStatePolicy,
)
from dingdongditch.authentication.portable_state import (
    PORTABLE_STATE_KIND,
    PORTABLE_STATE_SCHEMA_VERSION,
    validate_portable_document,
)


def _state():
    return {
        "cookies": [{"name": "sid", "value": "cookie-session-value", "domain": "fixture.test", "path": "/"}],
        "origins": [{
            "origin": "https://fixture.test",
            "localStorage": [
                {"name": "theme", "value": "dark"},
                {"name": "password", "value": "do-not-export"},
            ],
        }],
    }


def test_portable_state_export_import_round_trip_with_origin_isolation(tmp_path):
    export_context = MagicMock()
    export_context.storage_state.return_value = _state()
    exporter = AuthenticationCapability()
    exporter.bind_context(export_context)
    path = tmp_path / "state.json"
    exported = exporter.export_session(path)
    assert exported.status == "completed"
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == PORTABLE_STATE_SCHEMA_VERSION
    assert raw["kind"] == PORTABLE_STATE_KIND
    entries = raw["storage_state"]["origins"][0]["localStorage"]
    assert entries == [{"name": "theme", "value": "dark"}]
    assert "do-not-export" not in path.read_text()

    page = MagicMock()
    import_context = MagicMock()
    import_context.new_page.return_value = page
    importer = AuthenticationCapability()
    importer.bind_context(import_context)
    imported = importer.import_session(path)
    assert imported.status == "completed"
    import_context.clear_cookies.assert_called_once()
    import_context.add_cookies.assert_called_once()
    page.goto.assert_called_once_with("https://fixture.test", wait_until="domcontentloaded")
    page.close.assert_called_once()


def test_portable_state_rejects_malformed_stale_and_unsafe_origins_before_mutation(tmp_path):
    context = MagicMock()
    capability = AuthenticationCapability()
    capability.bind_context(context)
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema_version":2}', encoding="utf-8")
    with pytest.raises(AuthenticationError) as malformed_error:
        capability.import_session(malformed)
    assert malformed_error.value.kind is AuthenticationFailureKind.SESSION_INVALID
    context.clear_cookies.assert_not_called()

    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({
        "schema_version": PORTABLE_STATE_SCHEMA_VERSION,
        "kind": PORTABLE_STATE_KIND,
        "created_at_epoch_ms": int(time.time() * 1000) - 100_000,
        "portable_features": ["cookies", "local_storage"],
        "storage_state": {"cookies": [], "origins": []},
    }), encoding="utf-8")
    with pytest.raises(AuthenticationError) as stale_error:
        capability.import_session(stale, max_age_ms=10)
    assert stale_error.value.kind is AuthenticationFailureKind.SESSION_STALE
    context.clear_cookies.assert_not_called()

    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(json.dumps({
        "schema_version": PORTABLE_STATE_SCHEMA_VERSION,
        "kind": PORTABLE_STATE_KIND,
        "created_at_epoch_ms": int(time.time() * 1000),
        "portable_features": ["local_storage"],
        "storage_state": {"cookies": [], "origins": [{"origin": "file:///private", "localStorage": []}]},
    }), encoding="utf-8")
    with pytest.raises(AuthenticationError) as unsafe_error:
        capability.import_session(unsafe)
    assert unsafe_error.value.kind is AuthenticationFailureKind.SESSION_INVALID
    context.clear_cookies.assert_not_called()

    sensitive = tmp_path / "sensitive.json"
    sensitive.write_text(json.dumps({
        "schema_version": PORTABLE_STATE_SCHEMA_VERSION,
        "kind": PORTABLE_STATE_KIND,
        "created_at_epoch_ms": int(time.time() * 1000),
        "portable_features": ["local_storage"],
        "storage_state": {"cookies": [], "origins": [{
            "origin": "https://fixture.test",
            "localStorage": [{"name": "access_token", "value": "not-portable"}],
        }]},
    }), encoding="utf-8")
    with pytest.raises(AuthenticationError) as sensitive_error:
        capability.import_session(sensitive)
    assert sensitive_error.value.kind is AuthenticationFailureKind.SESSION_INVALID
    context.clear_cookies.assert_not_called()


def test_indexeddb_is_opt_in_and_only_prepared_for_new_context(tmp_path):
    state = _state()
    state["origins"][0]["indexedDB"] = [{"name": "safe-store", "version": 1, "stores": []}]
    context = MagicMock()
    context.storage_state.return_value = state
    capability = AuthenticationCapability()
    capability.bind_context(context)
    path = tmp_path / "indexed.json"
    capability.export_session(path, policy=PortableStatePolicy(include_indexed_db=True))

    active = AuthenticationCapability()
    active.bind_context(MagicMock())
    with pytest.raises(AuthenticationError) as unsupported:
        active.import_session(path)
    assert unsupported.value.kind is AuthenticationFailureKind.SESSION_UNSUPPORTED

    prepared = AuthenticationCapability()
    receipt = prepared.prepare_session_import(path)
    assert "indexed_db" in receipt.included_features
    assert prepared.pending_initial_storage_state() is not None
