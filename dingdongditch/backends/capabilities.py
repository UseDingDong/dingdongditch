"""Honest backend capability declaration (no speculative multi-browser claims)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dingdongditch.contract.browser import BrowserChannel, BrowserEngine, BrowserProvider


@dataclass(frozen=True)
class BackendCapabilities:
    """What this DingDongDitch backend build actually supports today."""

    provider: BrowserProvider
    engines: tuple[BrowserEngine, ...]
    channels: tuple[BrowserChannel, ...]
    actions: tuple[str, ...]
    headed: bool
    headless: bool
    notes: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "engines": [e.value for e in self.engines],
            "channels": [c.value for c in self.channels],
            "actions": list(self.actions),
            "headed": self.headed,
            "headless": self.headless,
            "notes": list(self.notes),
        }


# Alias retained for Chromium-era imports; same capability object.
PLAYWRIGHT_BUNDLED_CAPABILITIES = BackendCapabilities(
    provider=BrowserProvider.PLAYWRIGHT,
    engines=(BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT),
    channels=(BrowserChannel.BUNDLED,),
    actions=("navigate", "click", "fill", "press_key", "select_option", "set_checked", "hover", "scroll_to_target", "pointer_move", "wait_for", "download"),
    headed=True,
    headless=True,
    notes=(
        "chromium_bundled_supported",
        "firefox_bundled_supported",
        "webkit_bundled_supported",
        "safari_not_supported",
        "installed_channels_not_implemented",
        "custom_executables_not_implemented",
        "requires_playwright_install_chromium_firefox_webkit",
        "wait_for_video_ended_html5_same_document_only",
        "youtube_vimeo_iframe_media_unsupported",
        "native_media_controls_not_targetable",
        "adaptive_plan_timeout_video_ended_only",
        "iframe_targeting_declared_bounded_paths",
        "no_auto_frame_search_or_main_document_fallback",
        "select_option_multi_values_supported",
    ),
)

# Backward-compatible name used by existing imports/tests.
PLAYWRIGHT_CHROMIUM_BUNDLED_CAPABILITIES = PLAYWRIGHT_BUNDLED_CAPABILITIES
