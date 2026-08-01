from __future__ import annotations

import threading

import pytest

from dingdongditch.backends.playwright_backend import (
    BackendOwnershipError,
    PlaywrightBackend,
)
from dingdongditch.contract.browser import BrowserConfig


def test_backend_lease_is_reentrant_for_owning_thread():
    backend = PlaywrightBackend(BrowserConfig())

    with backend.exclusive_use("outer"):
        with backend.exclusive_use("inner"):
            assert backend._ownership_depth == 2

    assert backend._ownership_depth == 0
    assert backend._ownership_thread_id is None


def test_backend_lease_rejects_concurrent_owner_without_waiting():
    backend = PlaywrightBackend(BrowserConfig())
    owner_ready = threading.Event()
    release_owner = threading.Event()

    def owner():
        with backend.exclusive_use("owner-operation"):
            owner_ready.set()
            assert release_owner.wait(timeout=5)

    thread = threading.Thread(target=owner)
    thread.start()
    assert owner_ready.wait(timeout=5)

    with pytest.raises(BackendOwnershipError, match="owner-operation"):
        with backend.exclusive_use("competing-operation"):
            pass

    release_owner.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_backend_stop_cannot_race_active_owner():
    backend = PlaywrightBackend(BrowserConfig())
    owner_ready = threading.Event()
    release_owner = threading.Event()

    def owner():
        with backend.exclusive_use("active-transaction"):
            owner_ready.set()
            assert release_owner.wait(timeout=5)

    thread = threading.Thread(target=owner)
    thread.start()
    assert owner_ready.wait(timeout=5)

    with pytest.raises(BackendOwnershipError, match="active-transaction"):
        backend.stop()

    release_owner.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
