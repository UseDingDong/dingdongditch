"""Model-neutral browser configuration (session-level, not per-target).

Supported today: Playwright-bundled Chromium, Firefox, and WebKit.
Installed Chromium-family channels (chrome/msedge/brave) remain unsupported.
Native Safari is not an engine alias and is not supported.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Any
from dingdongditch.contract.download import DownloadPolicy


class BrowserProvider(str, Enum):
    PLAYWRIGHT = "playwright"


class BrowserEngine(str, Enum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class BrowserChannel(str, Enum):
    BUNDLED = "bundled"
    CHROME = "chrome"
    MSEDGE = "msedge"
    BRAVE = "brave"


class BrowserProfile(str, Enum):
    """Browser state policy for a session."""

    BENCHMARK = "benchmark"
    DINGDONG = "dingdong"
    DEFAULT = "default"


def dingdong_profile_directory() -> Path:
    """Return the deterministic, isolated persistent profile directory."""
    override = os.environ.get("DINGDONGDITCH_PROFILE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return (base / "DingDongDitch" / "browser-profiles" / "dingdong").resolve()


def default_chrome_user_data_directory() -> Path | None:
    """Locate Chrome's user-data root without creating or modifying it."""
    candidates: list[Path]
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        candidates = [Path(local) / "Google" / "Chrome" / "User Data"] if local else []
    elif os.uname().sysname == "Darwin":
        candidates = [Path.home() / "Library" / "Application Support" / "Google" / "Chrome"]
    else:
        candidates = [
            Path.home() / ".config" / "google-chrome",
            Path.home() / ".config" / "chromium",
        ]
    return next((path.resolve() for path in candidates if path.is_dir()), None)


class BrowserFailureKind(str, Enum):
    UNSUPPORTED_BROWSER_PROVIDER = "unsupported_browser_provider"
    UNSUPPORTED_BROWSER_ENGINE = "unsupported_browser_engine"
    UNSUPPORTED_BROWSER_CHANNEL = "unsupported_browser_channel"
    UNSUPPORTED_ENGINE_CHANNEL_COMBINATION = "unsupported_engine_channel_combination"
    BROWSER_BINARY_UNAVAILABLE = "browser_binary_unavailable"
    BROWSER_LAUNCH_FAILED = "browser_launch_failed"
    BROWSER_CONTEXT_CREATION_FAILED = "browser_context_creation_failed"
    PAGE_CREATION_FAILED = "page_creation_failed"
    CONTRADICTORY_BROWSER_CONFIG = "contradictory_browser_config"
    PROFILE_IN_USE = "profile_in_use"


# Implemented combinations — keep in sync with launch_playwright_browser().
SUPPORTED_ENGINE_CHANNELS: frozenset[tuple[BrowserEngine, BrowserChannel]] = frozenset(
    {
        (BrowserEngine.CHROMIUM, BrowserChannel.BUNDLED),
        (BrowserEngine.FIREFOX, BrowserChannel.BUNDLED),
        (BrowserEngine.WEBKIT, BrowserChannel.BUNDLED),
    }
)


class BrowserConfigError(ValueError):
    """Structured browser configuration / launch failure."""

    def __init__(self, message: str, *, failure_kind: BrowserFailureKind) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


@dataclass(frozen=True)
class BrowserConfig:
    """Session-level browser selection."""

    provider: BrowserProvider = BrowserProvider.PLAYWRIGHT
    engine: BrowserEngine = BrowserEngine.CHROMIUM
    channel: BrowserChannel = BrowserChannel.BUNDLED
    headless: bool = True
    download_policy: DownloadPolicy = DownloadPolicy()
    profile: BrowserProfile = BrowserProfile.BENCHMARK

    def describe(self) -> dict[str, Any]:
        persistent = self.profile != BrowserProfile.BENCHMARK
        return {
            "provider": self.provider.value,
            "engine": self.engine.value,
            "channel": self.channel.value,
            "headless": self.headless,
            "profile": self.profile.value,
            "persistent": persistent,
            "profile_isolation": (
                "fresh_ephemeral_context"
                if self.profile == BrowserProfile.BENCHMARK
                else "dedicated_runtime_directory"
                if self.profile == BrowserProfile.DINGDONG
                else "existing_user_chrome_profile"
            ),
            "authenticated_state_risk": (
                "none_from_prior_sessions"
                if self.profile == BrowserProfile.BENCHMARK
                else "persistent_state_accessible_to_plans"
                if self.profile == BrowserProfile.DINGDONG
                else "existing_authenticated_user_state_accessible_to_plans"
            ),
            "security_warning": (
                None
                if self.profile == BrowserProfile.BENCHMARK
                else (
                    "Persistent profiles retain cookies and browser-local state; "
                    "the filesystem lease prevents concurrent DingDongDitch use "
                    "but is not a security sandbox."
                )
            ),
            "download_policy": self.download_policy.describe(),
        }

    def validate(self) -> None:
        """Reject unknown/unsupported combinations before any browser launch."""
        if not isinstance(self.provider, BrowserProvider):
            raise BrowserConfigError(
                f"unknown browser provider: {self.provider!r}",
                failure_kind=BrowserFailureKind.UNSUPPORTED_BROWSER_PROVIDER,
            )
        if not isinstance(self.engine, BrowserEngine):
            raise BrowserConfigError(
                f"unknown browser engine: {self.engine!r}",
                failure_kind=BrowserFailureKind.UNSUPPORTED_BROWSER_ENGINE,
            )
        if not isinstance(self.channel, BrowserChannel):
            raise BrowserConfigError(
                f"unknown browser channel: {self.channel!r}",
                failure_kind=BrowserFailureKind.UNSUPPORTED_BROWSER_CHANNEL,
            )
        if not isinstance(self.headless, bool):
            raise BrowserConfigError(
                "headless must be a bool",
                failure_kind=BrowserFailureKind.CONTRADICTORY_BROWSER_CONFIG,
            )
        if not isinstance(self.profile, BrowserProfile):
            raise BrowserConfigError(
                f"unknown browser profile: {self.profile!r}",
                failure_kind=BrowserFailureKind.CONTRADICTORY_BROWSER_CONFIG,
            )
        if self.profile != BrowserProfile.BENCHMARK and self.engine != BrowserEngine.CHROMIUM:
            raise BrowserConfigError(
                f"profile={self.profile.value} requires engine=chromium",
                failure_kind=BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION,
            )
        if self.profile == BrowserProfile.DEFAULT and default_chrome_user_data_directory() is None:
            raise BrowserConfigError(
                "profile=default requested but no existing Chrome profile was found",
                failure_kind=BrowserFailureKind.BROWSER_CONTEXT_CREATION_FAILED,
            )
        if not isinstance(self.download_policy, DownloadPolicy):
            raise BrowserConfigError(
                "download_policy must be a DownloadPolicy",
                failure_kind=BrowserFailureKind.CONTRADICTORY_BROWSER_CONFIG,
            )
        self.download_policy.validate()

        if self.provider != BrowserProvider.PLAYWRIGHT:
            raise BrowserConfigError(
                f"unsupported browser provider: {self.provider.value}",
                failure_kind=BrowserFailureKind.UNSUPPORTED_BROWSER_PROVIDER,
            )

        # Structural engine/channel compatibility (even for reserved values).
        if self.engine == BrowserEngine.CHROMIUM:
            if self.channel not in (
                BrowserChannel.BUNDLED,
                BrowserChannel.CHROME,
                BrowserChannel.MSEDGE,
                BrowserChannel.BRAVE,
            ):
                raise BrowserConfigError(
                    f"unsupported engine/channel combination: "
                    f"{self.engine.value}/{self.channel.value}",
                    failure_kind=BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION,
                )
        elif self.engine in (BrowserEngine.FIREFOX, BrowserEngine.WEBKIT):
            if self.channel != BrowserChannel.BUNDLED:
                raise BrowserConfigError(
                    f"unsupported engine/channel combination: "
                    f"{self.engine.value}/{self.channel.value}",
                    failure_kind=BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION,
                )
        else:
            raise BrowserConfigError(
                f"unsupported browser engine: {self.engine.value}",
                failure_kind=BrowserFailureKind.UNSUPPORTED_BROWSER_ENGINE,
            )

        # Implemented support: Playwright bundled Chromium, Firefox, and WebKit.
        if (self.engine, self.channel) not in SUPPORTED_ENGINE_CHANNELS:
            if self.channel != BrowserChannel.BUNDLED:
                raise BrowserConfigError(
                    f"unsupported browser channel: {self.channel.value} "
                    f"(DingDongDitch currently supports only channel=bundled)",
                    failure_kind=BrowserFailureKind.UNSUPPORTED_BROWSER_CHANNEL,
                )
            raise BrowserConfigError(
                f"unsupported engine/channel combination: "
                f"{self.engine.value}/{self.channel.value}",
                failure_kind=BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION,
            )


def default_browser_config(*, headless: bool = True) -> BrowserConfig:
    """Default: Playwright bundled Chromium."""
    return BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=BrowserEngine.CHROMIUM,
        channel=BrowserChannel.BUNDLED,
        headless=headless,
        profile=BrowserProfile.BENCHMARK,
    )
