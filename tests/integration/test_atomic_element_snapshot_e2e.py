import pytest

from dingdongditch import (
    BrowserConfig,
    BrowserEngine,
    Locator,
    LocatorStrategy,
    inspect_target,
)
from dingdongditch.backends.element_snapshot import SnapshotAvailability
from dingdongditch.backends.playwright_backend import PlaywrightBackend


def css(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.CSS, value=value)


@pytest.mark.parametrize(
    "engine", [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT]
)
def test_atomic_snapshot_states_and_public_inspection_contract(fixture_url, engine):
    backend = PlaywrightBackend(BrowserConfig(engine=engine, headless=True))
    backend.start()
    try:
        backend.page.goto(fixture_url, wait_until="domcontentloaded")

        visible = backend.capture_element_snapshot(css("#text-input"))
        hidden = backend.capture_element_snapshot(
            css("[data-testid='hidden-reveal']")
        )
        disabled = backend.capture_element_snapshot(
            css("[data-testid='disabled-proceed']")
        )
        missing = backend.capture_element_snapshot(css("#atomic-missing"))
        duplicate = backend.capture_element_snapshot(css(".ambiguous-target"))

        assert visible.availability == SnapshotAvailability.AVAILABLE
        assert visible.visible is True
        assert visible.enabled is True
        assert visible.role == "textbox"
        assert visible.bounding_box is not None
        assert hidden.visible is False
        assert disabled.enabled is False
        assert missing.availability == SnapshotAvailability.MISSING
        assert duplicate.availability == SnapshotAvailability.AMBIGUOUS
        assert duplicate.match_count == 2

        public = inspect_target(backend, css("#text-input"))
        assert set(public) == {
            "page",
            "locator",
            "frame",
            "match_count",
            "exists",
            "ambiguous",
            "visible",
            "enabled",
            "text",
            "target_resolution",
        }
        assert public["match_count"] == 1
        assert public["visible"] is True
        assert backend._atomic_snapshot_fallback_count == 0
    finally:
        backend.stop()


def test_snapshot_is_not_cached_across_navigation_boundaries(fixture_url):
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    backend.start()
    try:
        backend.page.goto(fixture_url, wait_until="domcontentloaded")
        before = backend.capture_element_snapshot(css("#text-input"))
        backend.page.set_content("<main id='replacement'>replacement</main>")
        after = backend.capture_element_snapshot(css("#text-input"))
        replacement = backend.capture_element_snapshot(css("#replacement"))

        assert before.availability == SnapshotAvailability.AVAILABLE
        assert after.availability == SnapshotAvailability.MISSING
        assert replacement.availability == SnapshotAvailability.AVAILABLE
        assert backend._atomic_snapshot_count == 2
        assert backend._atomic_snapshot_fallback_count == 0
    finally:
        backend.stop()
