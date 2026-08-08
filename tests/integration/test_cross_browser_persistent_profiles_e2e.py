from __future__ import annotations

import pytest

from dingdongditch.authentication import AuthenticationCapability, ProfileManager
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserConfig, BrowserConfigError, BrowserEngine


@pytest.mark.parametrize("engine", [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT])
def test_isolated_persistent_profile_survives_clean_reopen(tmp_path, fixture_url, engine):
    manager = ProfileManager(tmp_path / "profiles")
    name = f"persist-{engine.value}"
    manager.create(name)

    first = PlaywrightBackend(
        BrowserConfig(engine=engine, profile=name),
        authentication=AuthenticationCapability(profiles=manager),
    )
    first.start()
    try:
        first.page.goto(fixture_url, wait_until="domcontentloaded")
        first.page.evaluate("() => localStorage.setItem('ddd-profile-probe', 'retained')")
        assert first.browser_environment()["engine"] == engine.value
    finally:
        first.stop()

    second = PlaywrightBackend(
        BrowserConfig(engine=engine, profile=name),
        authentication=AuthenticationCapability(profiles=manager),
    )
    second.start()
    try:
        second.page.goto(fixture_url, wait_until="domcontentloaded")
        assert second.page.evaluate("() => localStorage.getItem('ddd-profile-probe')") == "retained"
    finally:
        second.stop()


def test_profile_lock_remains_exclusive_for_selected_engine(tmp_path):
    manager = ProfileManager(tmp_path / "profiles")
    manager.create("locked")
    first = PlaywrightBackend(
        BrowserConfig(engine=BrowserEngine.FIREFOX, profile="locked"),
        authentication=AuthenticationCapability(profiles=manager),
    )
    first.start()
    try:
        second = PlaywrightBackend(
            BrowserConfig(engine=BrowserEngine.FIREFOX, profile="locked"),
            authentication=AuthenticationCapability(profiles=manager),
        )
        with pytest.raises(BrowserConfigError) as raised:
            second.start()
        assert raised.value.failure_kind.value == "profile_in_use"
    finally:
        first.stop()
