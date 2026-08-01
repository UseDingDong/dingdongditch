from __future__ import annotations

import pytest

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import (
    BrowserConfig,
    BrowserConfigError,
    BrowserFailureKind,
    BrowserProfile,
    dingdong_profile_directory,
)
from dingdongditch.runtime.file_lease import (
    LeaseUnavailableError,
    acquire_file_lease,
)


def test_file_lease_is_exclusive_and_reusable(tmp_path):
    path = tmp_path / "resource.lock"
    first = acquire_file_lease(path)
    try:
        with pytest.raises(LeaseUnavailableError):
            acquire_file_lease(path)
    finally:
        first.close()
    second = acquire_file_lease(path)
    second.close()


def test_persistent_profile_lease_fails_before_browser_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("DINGDONGDITCH_PROFILE_DIR", str(tmp_path / "profile"))
    profile = dingdong_profile_directory()
    lease = acquire_file_lease(
        profile.parent / f".{profile.name}.ddd-profile.lock"
    )
    backend = PlaywrightBackend(
        BrowserConfig(headless=False, profile=BrowserProfile.DINGDONG)
    )
    try:
        with pytest.raises(BrowserConfigError) as caught:
            backend.start()
        assert caught.value.failure_kind == BrowserFailureKind.PROFILE_IN_USE
        assert backend._playwright is None
    finally:
        lease.close()
