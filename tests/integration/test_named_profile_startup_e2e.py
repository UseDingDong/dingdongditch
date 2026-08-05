from dingdongditch.authentication import AuthenticationCapability, ProfileManager
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserConfig


def test_named_profile_automatically_starts_ready_and_releases_lock(tmp_path):
    manager = ProfileManager(tmp_path / "profiles")
    manager.create("integration")
    capability = AuthenticationCapability(profiles=manager)
    backend = PlaywrightBackend(
        BrowserConfig(profile="integration"), authentication=capability
    )
    backend.start()
    try:
        assert backend.is_started
        assert backend.page.evaluate("() => document.readyState") in {
            "interactive", "complete"
        }
    finally:
        backend.stop()
    manager.acquire("integration").close()
