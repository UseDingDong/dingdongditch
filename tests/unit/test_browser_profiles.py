from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dingdongditch import BrowserConfig, BrowserProfile
from dingdongditch.backends.playwright_backend import (
    PlaywrightBackend,
    launch_playwright_browser,
    launch_playwright_persistent_context,
)
from dingdongditch.contract.browser import (
    BrowserConfigError,
    BrowserEngine,
    dingdong_profile_directory,
)
from dingdongditch.plan_json import browser_config_from_dict


def test_benchmark_is_the_public_api_default():
    config = BrowserConfig()
    assert config.profile is BrowserProfile.BENCHMARK
    assert config.describe()["profile"] == "benchmark"


def test_profile_is_parsed_from_public_json_api():
    config = browser_config_from_dict({"profile": "dingdong", "headless": True})
    assert config.profile is BrowserProfile.DINGDONG


def test_dingdong_directory_is_deterministic_and_overrideable(tmp_path, monkeypatch):
    expected = tmp_path / "isolated-profile"
    monkeypatch.setenv("DINGDONGDITCH_PROFILE_DIR", str(expected))
    assert dingdong_profile_directory() == expected.resolve()
    assert dingdong_profile_directory() == expected.resolve()


def test_dingdong_uses_same_persistent_context_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("DINGDONGDITCH_PROFILE_DIR", str(tmp_path / "profile"))
    playwright = MagicMock()
    context = MagicMock()
    playwright.chromium.launch_persistent_context.return_value = context
    config = BrowserConfig(profile=BrowserProfile.DINGDONG, headless=True)

    assert launch_playwright_persistent_context(playwright, config) is context
    assert launch_playwright_persistent_context(playwright, config) is context
    expected = str((tmp_path / "profile").resolve())
    assert playwright.chromium.launch_persistent_context.call_count == 2
    for call in playwright.chromium.launch_persistent_context.call_args_list:
        assert call.args[0] == expected
        assert call.kwargs == {"headless": True, "accept_downloads": True}


def test_benchmark_keeps_fresh_browser_context_behavior():
    playwright = MagicMock()
    launch_playwright_browser(playwright, BrowserConfig())
    playwright.chromium.launch.assert_called_once_with(headless=True)
    playwright.chromium.launch_persistent_context.assert_not_called()


def test_persistent_context_is_active_without_browser_handle():
    backend = PlaywrightBackend(BrowserConfig(profile=BrowserProfile.DINGDONG))
    backend._started = True
    backend._context = MagicMock()
    backend._page = MagicMock()
    backend._page.is_closed.return_value = False
    backend._browser = None
    assert backend.is_started is True


def test_persistent_profiles_are_chromium_only():
    with pytest.raises(BrowserConfigError, match="requires engine=chromium"):
        BrowserConfig(
            engine=BrowserEngine.FIREFOX, profile=BrowserProfile.DINGDONG
        ).validate()


def test_default_profile_uses_existing_chrome_default_directory(tmp_path):
    playwright = MagicMock()
    context = MagicMock()
    playwright.chromium.launch_persistent_context.return_value = context
    with patch(
        "dingdongditch.backends.playwright_backend.default_chrome_user_data_directory",
        return_value=Path(tmp_path),
    ):
        result = launch_playwright_persistent_context(
            playwright, BrowserConfig(profile=BrowserProfile.DEFAULT)
        )
    assert result is context
    playwright.chromium.launch_persistent_context.assert_called_once_with(
        str(tmp_path),
        channel="chrome",
        args=["--profile-directory=Default"],
        headless=True,
        accept_downloads=True,
    )
