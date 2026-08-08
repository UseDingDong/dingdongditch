from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from dingdongditch.backends.capabilities import (
    PLAYWRIGHT_CHROMIUM_BUNDLED_CAPABILITIES,
    BackendCapabilities,
)
from dingdongditch.backends.target_resolver import (
    ResolvedTarget,
    _primary_playwright_locator,
    merge_frame_trace,
    resolve_frame,
    resolve_frame_path,
    resolve_target,
    resolve_target_identity,
)
from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserConfigError,
    BrowserEngine,
    BrowserFailureKind,
    BrowserProvider,
    BrowserProfile,
    default_browser_config,
    default_chrome_user_data_directory,
    dingdong_profile_directory,
    is_persistent_profile,
    profile_value,
)
from dingdongditch.authentication import (
    AuthenticationCapability,
    AuthenticationError,
    AuthenticationFailureKind,
)
from dingdongditch.contract.operation import (
    ActionType,
    KeyPressScope,
    Locator,
    Operation,
    SelectMode,
)
from dingdongditch.backends.element_snapshot import (
    ATOMIC_ELEMENT_SNAPSHOT_JS,
    LEGACY_ATTRIBUTE_NAMES,
    AtomicSnapshotUnsupported,
    ElementStateSnapshot,
    SnapshotAvailability,
)
from dingdongditch.contract.page import (
    NewPageExpectation,
    PageLifecycleState,
    PageTransition,
    PageTransitionPolicy,
)
from dingdongditch.contract.dialog import (
    DialogAction,
    DialogContract,
    DialogRequirement,
)
from dingdongditch.contract.runtime import LifecycleState
from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.target import (
    CardinalityPolicy,
    ResolutionStage,
    TargetResolutionTrace,
)
from dingdongditch.contract.wait import (
    WAIT_POLL_INTERVAL_MS,
    WaitCondition,
    WaitConditionType,
)
from dingdongditch.contract.download import (
    DownloadArtifactStore,
    DownloadCoordinator,
    DownloadEventMonitor,
    DownloadFailureReason,
    DownloadLifecycleState,
    DownloadPageEffectPolicy,
    DownloadSecurityError,
    DownloadTriggerAction,
    TrustedDownloadConfig,
    DownloadDeadline,
    DownloadTimeoutError,
)
from dingdongditch.contract.pointer import PointerOrigin
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.models import SignalAvailability, SignalKind
from dingdongditch.evidence.network import safe_network_record
from dingdongditch.runtime.publication import commit_file, publish_json
from dingdongditch.runtime.file_lease import (
    FileLease,
    LeaseUnavailableError,
    acquire_file_lease,
)


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


class BackendOwnershipError(RuntimeError):
    """Raised when another execution owner currently holds the backend."""


def _classify_launch_failure(exc: BaseException, config: BrowserConfig) -> BrowserConfigError:
    """Map Playwright launch exceptions to honest failure kinds (no Chromium fallback)."""
    message = str(exc)
    lower = message.lower()
    binary_signals = (
        "executable doesn't exist",
        "browserType.launch",
        "please run the following command to download new browsers",
        "playwright install",
        "browser has not been downloaded",
        "firefox.exe",
        "could not find browser",
    )
    if any(s in lower for s in binary_signals) or (
        ("firefox" in lower or "webkit" in lower)
        and ("install" in lower or "download" in lower or "doesn't exist" in lower)
    ):
        return BrowserConfigError(
            f"browser binary unavailable for {config.engine.value} "
            f"(channel={config.channel.value}): {exc}. "
            f"Install with: python -m playwright install {config.engine.value}",
            failure_kind=BrowserFailureKind.BROWSER_BINARY_UNAVAILABLE,
        )
    return BrowserConfigError(
        f"browser launch failed for {config.engine.value}: {exc}",
        failure_kind=BrowserFailureKind.BROWSER_LAUNCH_FAILED,
    )


def launch_playwright_browser(playwright: Playwright, config: BrowserConfig) -> Browser:
    """Authoritative BrowserConfig → Playwright launch translation.

    This is the only place that may call playwright.<engine>.launch(...).
    Unsupported engines/channels must already have failed BrowserConfig.validate().
    Never silently falls back to Chromium.
    """
    if config.provider != BrowserProvider.PLAYWRIGHT:
        raise BrowserConfigError(
            f"unsupported browser provider: {config.provider.value}",
            failure_kind=BrowserFailureKind.UNSUPPORTED_BROWSER_PROVIDER,
        )
    if (
        config.engine == BrowserEngine.CHROMIUM
        and config.channel == BrowserChannel.BUNDLED
    ):
        return playwright.chromium.launch(headless=config.headless)
    if (
        config.engine == BrowserEngine.FIREFOX
        and config.channel == BrowserChannel.BUNDLED
    ):
        return playwright.firefox.launch(headless=config.headless)
    if (
        config.engine == BrowserEngine.WEBKIT
        and config.channel == BrowserChannel.BUNDLED
    ):
        return playwright.webkit.launch(headless=config.headless)
    # Defense in depth: never silently fall back to another engine.
    raise BrowserConfigError(
        f"no Playwright launch mapping for engine={config.engine.value} "
        f"channel={config.channel.value}",
        failure_kind=BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION,
    )


def launch_playwright_persistent_context(
    playwright: Playwright, config: BrowserConfig, *, user_data_dir: Path | None = None
) -> BrowserContext:
    """Launch an engine-specific, isolated persistent context.

    ``profile=default`` remains Chromium-only because it means the existing
    Chrome Default directory.  Named and DingDong profiles use Playwright's
    documented persistent-context API for the selected bundled engine.
    """
    browser_type = {
        BrowserEngine.CHROMIUM: playwright.chromium,
        BrowserEngine.FIREFOX: playwright.firefox,
        BrowserEngine.WEBKIT: playwright.webkit,
    }.get(config.engine)
    if browser_type is None:
        raise BrowserConfigError(
            f"no persistent context mapping for {config.engine.value}",
            failure_kind=BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION,
        )
    if config.profile == BrowserProfile.DINGDONG:
        user_data_dir = dingdong_profile_directory(config.engine)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        return browser_type.launch_persistent_context(
            str(user_data_dir), headless=config.headless, accept_downloads=True
        )
    if config.profile == BrowserProfile.DEFAULT:
        user_data_dir = default_chrome_user_data_directory()
        if user_data_dir is None:
            raise BrowserConfigError(
                "profile=default requested but no existing Chrome profile was found",
                failure_kind=BrowserFailureKind.BROWSER_CONTEXT_CREATION_FAILED,
            )
        return playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            channel="chrome",
            args=["--profile-directory=Default"],
            headless=config.headless,
            accept_downloads=True,
        )
    if isinstance(config.profile, str) and config.profile not in {p.value for p in BrowserProfile}:
        if user_data_dir is None:
            raise BrowserConfigError("named profile directory was not prepared", failure_kind=BrowserFailureKind.BROWSER_CONTEXT_CREATION_FAILED)
        return browser_type.launch_persistent_context(
            str(user_data_dir), headless=config.headless, accept_downloads=True
        )
    raise BrowserConfigError(
        f"profile={profile_value(config.profile)} is not persistent",
        failure_kind=BrowserFailureKind.BROWSER_CONTEXT_CREATION_FAILED,
    )


@dataclass
class NetworkRecord:
    method: str
    url: str
    status: int | None
    request_observed_at_ms: int
    response_observed_at_ms: int | None = None
    content_type: str | None = None
    request_failed: bool = False
    request_observed: bool = True

    @property
    def recorded_at_ms(self) -> int:
        """Compatibility timestamp: response when available, else request."""
        return self.response_observed_at_ms or self.request_observed_at_ms

    def to_runtime_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "status": self.status,
            "request_observed_at_ms": self.request_observed_at_ms,
            "response_observed_at_ms": self.response_observed_at_ms,
            "recorded_at_ms": self.recorded_at_ms,
            "content_type": self.content_type,
            "request_failed": self.request_failed,
            "request_observed": self.request_observed,
        }


@dataclass
class ActionDispatchResult:
    ok: bool
    error: str | None
    started_at_ms: int
    completed_at_ms: int
    recovery_attempts: list[dict[str, Any]] = field(default_factory=list)
    match_count: int | None = None
    resolution_trace: TargetResolutionTrace | None = None
    failure_kind: str | None = None
    action_evidence: dict[str, Any] | None = None


@dataclass
class PageObservation:
    collected_at_ms: int
    url: str
    title: str
    network: list[NetworkRecord]


@dataclass
class PageRegistryEntry:
    page_id: str
    page: Page
    opener_page_id: str | None
    triggering_operation_id: str | None
    created_at_ms: int
    closed_at_ms: int | None = None
    lifecycle_state: PageLifecycleState = PageLifecycleState.OPEN

    def to_dict(self, *, active_page_id: str | None) -> dict[str, Any]:
        try:
            url = self.page.url
        except Exception:
            url = ""
        return {
            "page_id": self.page_id,
            "opener_page_id": self.opener_page_id,
            "triggering_operation_id": self.triggering_operation_id,
            "current_url": url,
            "lifecycle_state": self.lifecycle_state.value,
            "active": self.page_id == active_page_id,
            "created_at_ms": self.created_at_ms,
            "closed_at_ms": self.closed_at_ms,
        }


class PlaywrightBackend:
    """Playwright browser session owner. Not a public automation API.

    Owns: Playwright driver → browser → context → page lifecycle.
    Supports one retained session across ordered operations.
    """

    # The synchronous Playwright API permits many browsers/contexts from one
    # driver, but rejects starting a second driver on the same thread. Share
    # only the process-local driver; every backend still owns and closes its
    # own browser, context, pages, profile lease, and artifacts.
    _driver_lock = threading.RLock()
    _shared_playwright: Playwright | None = None
    _shared_playwright_refcount = 0

    def __init__(
        self,
        browser_config: BrowserConfig | None = None,
        *,
        headless: bool | None = None,
        trusted_download_config: TrustedDownloadConfig | None = None,
        authentication: AuthenticationCapability | None = None,
    ) -> None:
        if browser_config is None:
            browser_config = default_browser_config(
                headless=True if headless is None else headless
            )
        elif headless is not None and headless != browser_config.headless:
            raise BrowserConfigError(
                "contradictory headless values between BrowserConfig and headless=",
                failure_kind=BrowserFailureKind.CONTRADICTORY_BROWSER_CONFIG,
            )
        browser_config.validate()
        self.browser_config = browser_config
        self.trusted_download_config = (
            trusted_download_config or TrustedDownloadConfig()
        )
        self.trusted_download_config.validate()
        self._playwright: Playwright | None = None
        self._playwright_lease_acquired = False
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._network: list[NetworkRecord] = []
        self._network_limit = 512
        self._network_by_request: dict[object, NetworkRecord] = {}
        self.backend_identity = "playwright-sync"
        self.browser_identity = browser_config.engine.value
        self.browser_session_id: str | None = None
        self.context_id: str | None = None
        self.page_id: str | None = None
        self.browser_version: str | None = None
        self._started = False
        self._last_start_was_new = False
        self.lifecycle_state = LifecycleState.NOT_STARTED
        self.cleanup_errors: list[str] = []
        self.terminal_session_identity: dict[str, Any] | None = None
        self.telemetry: list[dict[str, Any]] = []
        self._pages: dict[str, PageRegistryEntry] = {}
        self._page_ids_by_object: dict[int, str] = {}
        self._triggering_operation_id: str | None = None
        self._triggering_opener_page_id: str | None = None
        self._dialog_history: list[dict[str, Any]] = []
        self._download_store: DownloadArtifactStore | None = None
        self._pointer_position: tuple[float, float] | None = None
        self._pointer_page_id: str | None = None
        self._atomic_snapshot_count = 0
        self._atomic_snapshot_fallback_count = 0
        self._ownership_lock = threading.RLock()
        self._ownership_thread_id: int | None = None
        self._ownership_depth = 0
        self._ownership_scope: str | None = None
        self._profile_lease: FileLease | None = None
        self.authentication = authentication or AuthenticationCapability()
        self._profile_data_dir: Path | None = None
        self._generation = 0
        self.observation_store_root = Path(
            self.trusted_download_config.artifact_root
        ) / "observations"

    def _prepare_new_generation(self) -> None:
        """Remove all state owned by a previous terminal browser generation."""
        self._generation += 1
        self._pages.clear()
        self._page_ids_by_object.clear()
        self._dialog_history.clear()
        self._network.clear()
        self._network_by_request.clear()
        self._pointer_position = None
        self._pointer_page_id = None
        self._atomic_snapshot_count = 0
        self._atomic_snapshot_fallback_count = 0
        self._triggering_operation_id = None
        self._triggering_opener_page_id = None
        self.cleanup_errors = []
        self.terminal_session_identity = None
        self.telemetry = []
        if hasattr(self, "_page_observer"):
            delattr(self, "_page_observer")

    @contextmanager
    def exclusive_use(self, scope: str):
        """Acquire fail-fast, reentrant ownership for one backend transaction."""
        acquired = self._ownership_lock.acquire(blocking=False)
        if not acquired:
            raise BackendOwnershipError(
                f"backend is already owned by {self._ownership_scope or 'another transaction'}"
            )
        thread_id = threading.get_ident()
        try:
            if self._ownership_thread_id not in (None, thread_id):
                raise BackendOwnershipError("backend ownership thread changed unexpectedly")
            if self._ownership_depth == 0:
                self._ownership_thread_id = thread_id
                self._ownership_scope = scope
            self._ownership_depth += 1
            yield
        finally:
            if self._ownership_thread_id == thread_id and self._ownership_depth:
                self._ownership_depth -= 1
                if self._ownership_depth == 0:
                    self._ownership_thread_id = None
                    self._ownership_scope = None
            self._ownership_lock.release()

    def _event(self, name: str, **detail: Any) -> None:
        self.telemetry.append({"event": name, "at_ms": monotonic_ms(), **detail})

    @property
    def is_started(self) -> bool:
        if not self._started or self._page is None or self._context is None:
            return False
        try:
            alive = not self._page.is_closed() and (
                self._browser is None or self._browser.is_connected()
            )
        except Exception:
            alive = False
        if not alive:
            self.lifecycle_state = LifecycleState.CRASHED
        return alive

    @classmethod
    def capabilities(cls) -> BackendCapabilities:
        return PLAYWRIGHT_CHROMIUM_BUNDLED_CAPABILITIES

    def browser_environment(self) -> dict[str, Any]:
        """JSON-serializable browser/session metadata for receipts."""
        return {
            "provider": self.browser_config.provider.value,
            "engine": self.browser_config.engine.value,
            "channel": self.browser_config.channel.value,
            "headless": self.browser_config.headless,
            "profile": profile_value(self.browser_config.profile),
            "persistent": is_persistent_profile(self.browser_config.profile),
            "download_policy": self.browser_config.download_policy.describe(),
            "backend_identity": self.backend_identity,
            "browser_version": self.browser_version,
            "browser_session_id": self.browser_session_id,
            "context_id": self.context_id,
            "page_id": self.page_id,
            "newly_launched": self._last_start_was_new if self._started else None,
            "lifecycle_state": self.lifecycle_state.value,
            "cleanup_errors": list(self.cleanup_errors),
            "terminal_session_identity": self.terminal_session_identity,
            "capabilities": self.capabilities().describe(),
        }

    def read_page_focus_state(self) -> dict[str, Any]:
        """Return bounded focus facts for guarded interaction sessions."""
        if not self.is_started:
            raise RuntimeError("page focus inspection requires an active backend")
        raw = self.page.evaluate(
            """() => {
                const active = document.activeElement;
                return {
                    focused: document.hasFocus(),
                    active_element: active ? {
                        tag: active.tagName.toLowerCase(),
                        id: active.id || null,
                        role: active.getAttribute("role"),
                        test_id: active.getAttribute("data-testid"),
                        contenteditable: active.isContentEditable
                    } : null
                };
            }"""
        )
        return {
            "focused": bool(raw.get("focused")),
            "active_element": raw.get("active_element"),
            "url": self.page.url,
            "page_id": self.page_id,
        }

    def read_focus_containment(self, locator: Locator) -> bool:
        """Whether the uniquely resolved target contains the active DOM element."""
        resolved = self._resolve_scoped_target(
            locator, cardinality=CardinalityPolicy.EXACTLY_ONE
        )
        if (
            not resolved.ok
            or resolved.match_count != 1
            or resolved.playwright_locator is None
        ):
            return False
        return bool(
            resolved.playwright_locator.evaluate(
                "element => element.contains(document.activeElement)"
            )
        )

    def observe_page(self, options: Any = None) -> Any:
        """Return a bounded deterministic interaction map for the active page."""
        with self.exclusive_use("page_observation"):
            from dingdongditch.page_observer import PageObserver

            observer = getattr(self, "_page_observer", None)
            if observer is None:
                observer = self._page_observer = PageObserver(self)
            return observer.observe_page(options)

    def validate_observation_reference(self, reference: Any) -> Any:
        """Re-resolve an observation-local target or reject it as stale."""
        with self.exclusive_use("observation_validation"):
            from dingdongditch.page_observer import PageObserver

            observer = getattr(self, "_page_observer", None)
            if observer is None:
                observer = self._page_observer = PageObserver(self)
            return observer.validate_reference(reference)

    def attest_observation_locators(self, observation_id: str) -> Any:
        """Collect locator attestations under an independent backend lease."""
        with self.exclusive_use("locator_attestation"):
            from dingdongditch.page_observer import PageObserver

            observer = getattr(self, "_page_observer", None)
            if observer is None:
                observer = self._page_observer = PageObserver(self)
            return observer.attest_observation_locators(observation_id)

    def observation_evidence_view(self, observation_id: str, **kwargs: Any) -> Any:
        """Compose immutable observation and attestation evidence."""
        with self.exclusive_use("observation_evidence_view"):
            from dingdongditch.page_observer import PageObserver

            observer = getattr(self, "_page_observer", None)
            if observer is None:
                observer = self._page_observer = PageObserver(self)
            return observer.evidence_view(observation_id, **kwargs)

    def start(self) -> None:
        with self.exclusive_use("backend_start"):
            self._start()

    def _start(self) -> None:
        """Create or reuse the browser session. Validate before any launch."""
        if self.is_started:
            return
        if self._started:
            self.lifecycle_state = LifecycleState.CRASHED
            raise BrowserConfigError(
                "browser session is closed, crashed, or unusable",
                failure_kind=BrowserFailureKind.BROWSER_LAUNCH_FAILED,
            )

        self.browser_config.validate()
        self._prepare_new_generation()
        named_profile = isinstance(self.browser_config.profile, str) and self.browser_config.profile not in {p.value for p in BrowserProfile}
        if named_profile:
            try:
                self._profile_data_dir = self.authentication.acquire_profile(
                    self.browser_config.profile,
                    engine=self.browser_config.engine.value,
                )
            except AuthenticationError as exc:
                profile_failures = {
                    "profile_in_use": BrowserFailureKind.PROFILE_IN_USE,
                    "profile_not_found": BrowserFailureKind.PROFILE_NOT_FOUND,
                    "profile_corrupt": BrowserFailureKind.PROFILE_CORRUPT,
                }
                raise BrowserConfigError(
                    str(exc),
                    failure_kind=profile_failures.get(
                        exc.kind.value, BrowserFailureKind.BROWSER_LAUNCH_FAILED
                    ),
                ) from exc
        elif is_persistent_profile(self.browser_config.profile):
            profile_dir = (
                dingdong_profile_directory(self.browser_config.engine)
                if self.browser_config.profile == BrowserProfile.DINGDONG
                else default_chrome_user_data_directory()
            )
            if profile_dir is None:
                raise BrowserConfigError(
                    "persistent browser profile is unavailable",
                    failure_kind=BrowserFailureKind.BROWSER_LAUNCH_FAILED,
                )
            lease_path = profile_dir.parent / f".{profile_dir.name}.ddd-profile.lock"
            try:
                self._profile_lease = acquire_file_lease(lease_path)
            except LeaseUnavailableError as exc:
                raise BrowserConfigError(
                    f"persistent browser profile is already in use: {profile_dir}",
                    failure_kind=BrowserFailureKind.PROFILE_IN_USE,
                ) from exc
        self.lifecycle_state = LifecycleState.STARTING
        self._event("backend_start_started_at")
        self._last_start_was_new = True
        try:
            with type(self)._driver_lock:
                if type(self)._shared_playwright is None:
                    type(self)._shared_playwright = sync_playwright().start()
                type(self)._shared_playwright_refcount += 1
                self._playwright_lease_acquired = True
                self._playwright = type(self)._shared_playwright
            self._event("playwright_started_at")
        except Exception as exc:
            self.lifecycle_state = LifecycleState.FAILED
            self.stop()
            raise BrowserConfigError(
                f"browser launch failed: {exc}",
                failure_kind=BrowserFailureKind.BROWSER_LAUNCH_FAILED,
            ) from exc

        try:
            if self.browser_config.profile == BrowserProfile.BENCHMARK:
                self._browser = launch_playwright_browser(
                    self._playwright, self.browser_config
                )
                self.browser_version = getattr(self._browser, "version", None)
                self._event("browser_launched_at")
            else:
                self._context = launch_playwright_persistent_context(
                    self._playwright, self.browser_config, user_data_dir=self._profile_data_dir
                )
                self._browser = self._context.browser
                self.browser_version = getattr(self._browser, "version", None)
                self._event("persistent_context_launched_at")
        except BrowserConfigError:
            self.stop()
            raise
        except Exception as exc:
            self.stop()
            raise _classify_launch_failure(exc, self.browser_config) from exc

        try:
            if self._context is None:
                initial_state = self.authentication.pending_initial_storage_state()
                self._context = self._browser.new_context(
                    accept_downloads=True,
                    **({"storage_state": initial_state} if initial_state is not None else {}),
                )
                if initial_state is not None:
                    self.authentication.confirm_pending_initial_storage_state()
            elif self.authentication.pending_initial_storage_state() is not None:
                # Persistent-context import has no safe IndexedDB injection
                # path.  Call import_session for its cookies/localStorage path.
                raise AuthenticationError(
                    "prepared portable state requires a new ephemeral context",
                    kind=AuthenticationFailureKind.SESSION_UNSUPPORTED,
                )
            self._context.on("page", self._on_context_page)
            self._event("context_created_at")
        except Exception as exc:
            self.stop()
            raise BrowserConfigError(
                f"browser context creation failed: {exc}",
                failure_kind=BrowserFailureKind.BROWSER_CONTEXT_CREATION_FAILED,
            ) from exc

        try:
            self._page = (
                self._context.pages[0]
                if self._context.pages
                else self._context.new_page()
            )
            self.authentication.bind_context(self._context)
            self.authentication.verify_ready(self._page)
            self._event("page_created_at")
            self._network = []
            self._network_by_request = {}

            def trim_network() -> None:
                if len(self._network) <= self._network_limit:
                    return
                removed = self._network[: len(self._network) - self._network_limit]
                del self._network[: len(removed)]
                for record in removed:
                    self._network_by_request = {
                        key: value
                        for key, value in self._network_by_request.items()
                        if value is not record
                    }

            def request_key(request: Any) -> object:
                # Playwright normally preserves wrapper identity.  Prefer the
                # stable internal GUID when exposed so response.request can be
                # correlated even if it is a fresh Python wrapper.
                impl = getattr(request, "_impl_obj", None)
                guid = getattr(impl, "_guid", None)
                return guid if isinstance(guid, str) else id(request)

            def on_request(request: Any) -> None:
                try:
                    record = NetworkRecord(
                        method=request.method,
                        url=request.url,
                        status=None,
                        request_observed_at_ms=monotonic_ms(),
                    )
                    self._network.append(record)
                    self._network_by_request[request_key(request)] = record
                    trim_network()
                except Exception:
                    # Browser event handling never changes action dispatch.
                    pass

            def on_response(response: Any) -> None:
                try:
                    request = response.request
                    record = self._network_by_request.get(request_key(request))
                    if record is None:
                        # Some browser events can be observed after the request
                        # hook was installed.  Record the response honestly;
                        # it is not presented as a timed request/response pair.
                        record = NetworkRecord(
                            method=request.method,
                            url=response.url,
                            status=None,
                            request_observed_at_ms=monotonic_ms(),
                            request_observed=False,
                        )
                        self._network.append(record)
                        self._network_by_request[request_key(request)] = record
                    record.status = response.status
                    record.response_observed_at_ms = monotonic_ms()
                    record.content_type = response.headers.get("content-type")
                    trim_network()
                except Exception:
                    pass

            def on_request_failed(request: Any) -> None:
                try:
                    record = self._network_by_request.get(request_key(request))
                    if record is not None:
                        record.request_failed = True
                except Exception:
                    pass

            # Context-level listeners cover every declared page transition;
            # they are bounded and contain metadata only.
            self._context.on("request", on_request)
            self._context.on("response", on_response)
            self._context.on("requestfailed", on_request_failed)
            self.browser_session_id = str(uuid.uuid4())
            self.context_id = str(uuid.uuid4())
            self.page_id = self._page_ids_by_object.get(id(self._page)) or str(
                uuid.uuid4()
            )
            self._register_page(
                self._page,
                page_id=self.page_id,
                opener_page_id=None,
                triggering_operation_id=None,
            )
            self._started = True
            self.lifecycle_state = LifecycleState.ACTIVE
            self._event("backend_start_finished_at")
        except Exception as exc:
            self.stop()
            raise BrowserConfigError(
                f"page creation failed: {exc}",
                failure_kind=BrowserFailureKind.PAGE_CREATION_FAILED,
            ) from exc

    def stop(self) -> None:
        with self.exclusive_use("backend_stop"):
            self._stop()

    def _stop(self) -> None:
        """Close page/context/browser/driver; clear session identifiers."""
        if (
            not self._started
            and self._playwright is None
            and self._browser is None
            and self._context is None
            and self._profile_lease is None
            and self._profile_data_dir is None
        ):
            return
        self.lifecycle_state = LifecycleState.STOPPING
        self.cleanup_errors = []
        self._event("cleanup_started_at")
        self.terminal_session_identity = {
            "browser_session_id": self.browser_session_id,
            "context_id": self.context_id,
            "page_id": self.page_id,
            "pages": self.list_pages(),
            "dialogs": self.list_dialog_history(),
            "browser_version": self.browser_version,
        }
        if self._download_store is not None:
            try:
                self._download_store.close()
            except Exception as exc:
                self.cleanup_errors.append(
                    f"download_store_close:{type(exc).__name__}: {exc}"
                )
            self._download_store = None

        try:
            if self._context is not None:
                self._context.close()
                self._event("context_closed_at")
                self.terminal_session_identity["pages"] = self.list_pages()
                self.terminal_session_identity["dialogs"] = self.list_dialog_history()
        except Exception as exc:
            self.cleanup_errors.append(f"context_close:{type(exc).__name__}: {exc}")
        try:
            if self._browser is not None:
                self._browser.close()
                self._event("browser_closed_at")
        except Exception as exc:
            self.cleanup_errors.append(f"browser_close:{type(exc).__name__}: {exc}")
        try:
            if self._playwright_lease_acquired:
                with type(self)._driver_lock:
                    type(self)._shared_playwright_refcount = max(
                        0, type(self)._shared_playwright_refcount - 1
                    )
                    if type(self)._shared_playwright_refcount == 0:
                        shared = type(self)._shared_playwright
                        type(self)._shared_playwright = None
                        if shared is not None:
                            shared.stop()
                            self._event("playwright_stopped_at")
        except Exception as exc:
            self.cleanup_errors.append(f"playwright_stop:{type(exc).__name__}: {exc}")
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._playwright_lease_acquired = False
        self._network = []
        self._network_by_request = {}
        self.browser_session_id = None
        self.context_id = None
        self.page_id = None
        self.browser_version = None
        self._started = False
        self._last_start_was_new = False
        self._triggering_operation_id = None
        self._triggering_opener_page_id = None
        if self._profile_lease is not None:
            try:
                self._profile_lease.close()
            except Exception as exc:
                self.cleanup_errors.append(
                    f"profile_lease_close:{type(exc).__name__}: {exc}"
                )
            self._profile_lease = None
        try:
            self.authentication.close()
        except Exception as exc:
            self.cleanup_errors.append(f"authentication_close:{type(exc).__name__}")
        self._profile_data_dir = None
        self.lifecycle_state = (
            LifecycleState.FAILED if self.cleanup_errors else LifecycleState.STOPPED
        )
        self._event("cleanup_finished_at", cleanup_failures=len(self.cleanup_errors))

    def mark_session_reused(self) -> None:
        """Record that subsequent receipts use a session launched by its owner."""
        if self.is_started:
            self._last_start_was_new = False

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("PlaywrightBackend not started")
        return self._page

    def _register_page(
        self,
        page: Page,
        *,
        page_id: str | None = None,
        opener_page_id: str | None,
        triggering_operation_id: str | None,
    ) -> PageRegistryEntry:
        existing_id = self._page_ids_by_object.get(id(page))
        if existing_id is not None:
            return self._pages[existing_id]
        entry = PageRegistryEntry(
            page_id=page_id or str(uuid.uuid4()),
            page=page,
            opener_page_id=opener_page_id,
            triggering_operation_id=triggering_operation_id,
            created_at_ms=monotonic_ms(),
        )
        self._pages[entry.page_id] = entry
        self._page_ids_by_object[id(page)] = entry.page_id

        def on_close() -> None:
            entry.lifecycle_state = PageLifecycleState.CLOSED
            entry.closed_at_ms = monotonic_ms()
            self._event("page_closed_at", page_id=entry.page_id)

        page.on("close", on_close)
        self._event(
            "page_registered_at",
            page_id=entry.page_id,
            opener_page_id=opener_page_id,
            triggering_operation_id=triggering_operation_id,
        )
        return entry

    def _on_context_page(self, page: Page) -> None:
        self._register_page(
            page,
            opener_page_id=self._triggering_opener_page_id,
            triggering_operation_id=self._triggering_operation_id,
        )

    def list_pages(self) -> list[dict[str, Any]]:
        return [
            entry.to_dict(active_page_id=self.page_id)
            for entry in self._pages.values()
        ]

    def list_dialog_history(self) -> list[dict[str, Any]]:
        """Return a read-only copy of native dialog evidence."""
        return [dict(item) for item in self._dialog_history]

    def capture_screenshot(self, *, plan_id: str, step_id: str, operation_id: str, reason: str, config: Any) -> dict[str, Any]:
        """Capture one deterministic evidence artifact; errors are returned, never raised."""
        started = monotonic_ms()
        path: Path | None = None
        temporary: Path | None = None
        redaction_requested = bool(config.redact_password_inputs or config.sensitive_selectors)
        redaction_status = "not_requested"
        redaction_selectors: list[str] = []
        redaction_match_count = 0
        try:
            root = Path(config.artifact_root)
            root.mkdir(parents=True, exist_ok=True)
            safe = lambda value: "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value))
            path = root / f"{safe(plan_id)}__{safe(step_id)}__{safe(operation_id)}__{safe(reason)}__{self.page_id}.png"
            temporary = root / f".{path.name}.{uuid.uuid4().hex}.tmp"
            masks: list[Any] = []
            if config.redact_password_inputs:
                redaction_selectors.append('input[type="password"]')
            redaction_selectors.extend(config.sensitive_selectors)
            for selector in redaction_selectors:
                for frame in list(self.page.frames):
                    locator = frame.locator(selector)
                    # Resolve now so malformed selectors, detached frames, or
                    # page failures are known before any image is written.
                    # Playwright resolves the same locator again while applying
                    # masks to the screenshot.
                    redaction_match_count += locator.count()
                    masks.append(locator)
            if redaction_requested:
                redaction_status = "applied"
            try:
                self.page.screenshot(
                    path=str(temporary),
                    full_page=bool(config.full_page),
                    timeout=int(config.capture_timeout_ms),
                    mask=masks,
                )
                commit_file(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return {"captured": True, "plan_id": plan_id, "step_id": step_id, "operation_id": operation_id, "page_id": self.page_id, "reason": reason, "url": self.page.url, "timestamp_ms": monotonic_ms(), "full_page": bool(config.full_page), "artifact_path": path.as_posix(), "capture_duration_ms": max(0, monotonic_ms() - started), "redaction_status": redaction_status, "redaction_requested": redaction_requested, "redaction_selectors": redaction_selectors, "redaction_match_count": redaction_match_count, "capture_error": None}
        except Exception as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            return {"captured": False, "plan_id": plan_id, "step_id": step_id, "operation_id": operation_id, "page_id": self.page_id, "reason": reason, "timestamp_ms": monotonic_ms(), "full_page": bool(getattr(config, "full_page", False)), "artifact_path": None, "capture_duration_ms": max(0, monotonic_ms() - started), "redaction_status": "failed" if redaction_requested else "not_requested", "redaction_requested": redaction_requested, "redaction_selectors": redaction_selectors, "redaction_match_count": redaction_match_count, "capture_error": f"{type(exc).__name__}: {exc}"}

    def inspect_page(self, page_id: str) -> dict[str, Any] | None:
        entry = self._pages.get(page_id)
        return entry.to_dict(active_page_id=self.page_id) if entry else None

    def _activate_page(self, page_id: str) -> None:
        entry = self._pages.get(page_id)
        if entry is None:
            raise ValueError(f"unknown page_id: {page_id}")
        if entry.lifecycle_state != PageLifecycleState.OPEN or entry.page.is_closed():
            raise ValueError(f"page is not open: {page_id}")
        self._page = entry.page
        self.page_id = entry.page_id
        entry.page.bring_to_front()

    @staticmethod
    def _text_matches(actual: str, expected: str, mode: TextMatchMode) -> bool:
        return actual == expected if mode == TextMatchMode.EXACT else expected in actual

    @staticmethod
    def _url_matches(actual: str, expected: str, mode: UrlMatchMode) -> bool:
        return actual == expected if mode == UrlMatchMode.EXACT else expected in actual

    def _verify_new_page(
        self,
        page: Page,
        expectations: tuple[NewPageExpectation, ...],
        *,
        timeout_ms: int,
    ) -> list[dict[str, Any]]:
        deadline = monotonic_ms() + timeout_ms
        try:
            page.wait_for_load_state("domcontentloaded", timeout=max(1, timeout_ms))
        except PlaywrightTimeoutError:
            pass
        if page.is_closed():
            raise RuntimeError("new page closed before verification")
        results: list[dict[str, Any]] = []
        for expected in expectations:
            remaining = max(1, deadline - monotonic_ms())
            if expected.visible_locator is not None:
                locator = _primary_playwright_locator(page, expected.visible_locator)
                try:
                    locator.wait_for(state="visible", timeout=remaining)
                    passed = locator.count() == 1 and locator.is_visible()
                except PlaywrightTimeoutError:
                    passed = False
                results.append(
                    {
                        "type": "visible_element",
                        "expected": expected.describe(),
                        "passed": passed,
                    }
                )
            if expected.url_value is not None:
                actual = page.url
                results.append(
                    {
                        "type": "url",
                        "expected": expected.describe(),
                        "actual": actual,
                        "passed": self._url_matches(
                            actual, expected.url_value, expected.url_match
                        ),
                    }
                )
            if expected.title_value is not None:
                actual = page.title()
                results.append(
                    {
                        "type": "title",
                        "expected": expected.describe(),
                        "actual": actual,
                        "passed": self._text_matches(
                            actual, expected.title_value, expected.title_match
                        ),
                    }
                )
        return results

    def ensure_on_url(self, url: str, timeout_ms: int) -> None:
        current = self.page.url
        if self._same_document_url(current, url):
            return
        if current in ("about:blank", "about:blank/", ""):
            self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return
        # Host declared a target URL for the operation; navigate if not already there
        # unless the action itself is navigate (handled separately).
        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    @staticmethod
    def _same_document_url(current: str, declared: str) -> bool:
        """True when already on the declared document (fragment differences allowed).

        Preserves in-page hash/history state so url_matches waits can observe
        fragment changes. Path/query mismatches still trigger navigation.
        """
        if current == declared or current.rstrip("/") == declared.rstrip("/"):
            return True
        from urllib.parse import urlsplit, urlunsplit

        def base(u: str) -> str:
            parts = urlsplit(u)
            path = parts.path.rstrip("/") or "/"
            return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))

        return base(current) == base(declared)

    def observe(self, collector: EvidenceCollector) -> PageObservation:
        """Collect URL/title/network. Tolerates mid-redirect context destruction.

        Some pages redirect after ``domcontentloaded``; reading ``title`` can
        fail once. That is observation fragility, not a cue to retry the host
        action or heal locators.
        """
        now = monotonic_ms()
        url = ""
        title = ""
        notes = "page observation"
        try:
            url = self.page.url
        except Exception as exc:
            notes = f"url_unavailable:{type(exc).__name__}"
        try:
            title = self.page.title()
        except Exception as exc:
            # Brief settle for redirect races only — not an action retry.
            try:
                self.page.wait_for_timeout(150)
                title = self.page.title()
            except Exception:
                title = ""
                notes = f"{notes};title_unavailable:{type(exc).__name__}"
        net_snapshot = [
            record
            for record in self._network
            if collector.window_started_at_ms is None
            or record.recorded_at_ms >= collector.window_started_at_ms
        ]
        collector.add(
            kind=SignalKind.URL,
            collected_at_ms=now,
            payload={"url": url, "title": title},
            notes=notes,
        )
        collector.add(
            kind=SignalKind.NETWORK,
            collected_at_ms=now,
            payload={
                "records": [n.to_runtime_dict() for n in net_snapshot],
                "discarded_record_count": max(0, len(self._network) - len(net_snapshot)),
            },
            notes="network log snapshot at observation time",
        )
        return PageObservation(
            collected_at_ms=now,
            url=url,
            title=title,
            network=net_snapshot,
        )

    def capture_network_artifact(
        self,
        *,
        operation_id: str,
        action_started_at_ms: int | None,
        request: Any,
    ) -> dict[str, Any]:
        """Write an explicitly requested bounded, sanitized Layer-3 trace.

        This method never feeds verifier input.  It deliberately does not use
        Playwright's context-wide HAR facility: that facility can capture
        unrelated pre/post-operation traffic and headers, which violates the
        per-operation bounded evidence boundary.
        """
        request.validate()
        matching_records = [
            item.to_runtime_dict()
            for item in self._network
            if action_started_at_ms is None or item.recorded_at_ms >= action_started_at_ms
        ]
        truncated = len(matching_records) > request.max_records
        records = matching_records[-request.max_records :]
        artifact_id = "network-trace-" + uuid.uuid4().hex
        filename = f"{artifact_id}.json"
        try:
            root = Path(self.trusted_download_config.artifact_root).resolve()
            destination = root / "network-traces" / filename
            payload = {
                "schema_version": 1,
                "kind": "sanitized_network_trace",
                "operation_id": operation_id,
                "records": [safe_network_record(record) for record in records],
                "truncated": truncated,
                "bodies_included": False,
                "headers_included": False,
            }
            publish_json(destination, payload, sort_keys=True)
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            return {
                "artifact_id": artifact_id,
                "kind": "network_trace",
                "status": "available",
                "filename": filename,
                "record_count": len(records),
                "sha256": digest,
                "headers_included": False,
                "bodies_included": False,
            }
        except Exception as exc:
            return {
                "artifact_id": artifact_id,
                "kind": "network_trace",
                "status": "failed",
                "filename": filename,
                "reason": type(exc).__name__,
                "headers_included": False,
                "bodies_included": False,
            }

    def participate_webauthn(self, request: Any) -> dict[str, Any]:
        """Delegate only metadata to a host transport; never control authenticators."""
        origin: str | None = None
        try:
            parsed = urlsplit(self.page.url)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                origin = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            origin = None
        receipt = self.authentication.participate_webauthn(
            request,
            browser_engine=self.browser_identity,
            page_origin=origin,
        )
        return receipt.to_dict()

    def _resolve_locator(self, locator: Locator):
        """Primary-only Playwright locator (constraints applied via resolve_target)."""
        from dingdongditch.backends.target_resolver import _primary_playwright_locator

        return _primary_playwright_locator(self.page, locator)

    def count_matches(
        self,
        locator: Locator,
        *,
        frame: Locator | None = None,
        frame_path: tuple[Locator, ...] = (),
    ) -> int:
        root = self.page
        path = frame_path or ((frame,) if frame is not None else ())
        if path:
            framed = resolve_frame_path(
                self.page, path, backend_identity=self.backend_identity
            )
            if not framed.ok or framed.frame is None:
                return framed.match_count
            root = framed.frame
        result = resolve_target(
            root,
            locator,
            cardinality=CardinalityPolicy.EXACTLY_ONE,
            backend_identity=self.backend_identity,
        )
        return result.match_count

    def _resolve_scoped_target(
        self,
        locator: Locator,
        *,
        frame: Locator | None = None,
        frame_path: tuple[Locator, ...] = (),
        cardinality: CardinalityPolicy = CardinalityPolicy.EXACTLY_ONE,
    ) -> ResolvedTarget:
        """Resolve a target in main document or an explicit declared frame path."""
        path = frame_path or ((frame,) if frame is not None else ())
        if not path:
            return resolve_target(
                self.page,
                locator,
                cardinality=cardinality,
                backend_identity=self.backend_identity,
            )
        framed = resolve_frame_path(
            self.page, path, backend_identity=self.backend_identity
        )
        if not framed.ok or framed.frame is None:
            return ResolvedTarget(
                ok=False,
                playwright_locator=None,
                match_count=framed.match_count,
                error=framed.error,
                failure_kind=framed.failure_kind,
                trace=framed.trace,
            )
        resolved = resolve_target(
            framed.frame,
            locator,
            cardinality=cardinality,
            backend_identity=self.backend_identity,
        )
        resolved.trace = merge_frame_trace(framed.trace, resolved.trace)
        return resolved

    def probe_guarded_action_target(self, operation: Operation) -> ResolvedTarget:
        """Resolve a guard target within the authored locate window, without dispatch."""
        if operation.guard is None or operation.action.locator is None:
            raise ValueError("guard probe requires an explicitly guarded target action")
        deadline = monotonic_ms() + operation.locate_retry_ms
        while True:
            resolved = self._resolve_scoped_target(
                operation.action.locator,
                frame=operation.action.frame,
                frame_path=operation.action.frame_path,
                cardinality=operation.cardinality,
            )
            clean_zero = resolved.match_count == 0 and resolved.failure_kind in {
                "zero_after_primary", "zero_after_constraints"
            }
            if not clean_zero or monotonic_ms() >= deadline:
                return resolved
            self.page.wait_for_timeout(min(50, max(1, deadline - monotonic_ms())))

    def _element_in_viewport(self, loc: Any) -> bool | None:
        try:
            return bool(
                loc.evaluate(
                    """(el) => {
                      const r = el.getBoundingClientRect();
                      if (r.width === 0 && r.height === 0) return false;
                      const vh = window.innerHeight || document.documentElement.clientHeight;
                      const vw = window.innerWidth || document.documentElement.clientWidth;
                      return r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;
                    }"""
                )
            )
        except Exception:
            return None

    def _control_kind(self, loc: Any) -> dict[str, Any]:
        try:
            return loc.evaluate(
                """(el) => ({
                  tag: (el.tagName || '').toLowerCase(),
                  type: (el.getAttribute('type') || '').toLowerCase(),
                  role: (el.getAttribute('role') || '').toLowerCase(),
                })"""
            )
        except Exception:
            return {"tag": None, "type": None, "role": None}

    def _url_matches(self, url: str, value: str, mode: UrlMatchMode) -> bool:
        if mode == UrlMatchMode.EXACT:
            return url == value
        return value in url

    def _text_matches(self, actual: str, expected: str, mode: TextMatchMode) -> bool:
        if mode == TextMatchMode.EXACT:
            return actual == expected
        return expected in actual

    def _observe_wait_condition(
        self,
        condition: WaitCondition,
        *,
        cardinality: CardinalityPolicy,
    ) -> tuple[bool | None, dict[str, Any], TargetResolutionTrace | None, str | None]:
        """Return (satisfied|None if indeterminate, observed, trace, failure_kind)."""
        observed: dict[str, Any] = {"condition_type": condition.type.value}
        if condition.type == WaitConditionType.URL_MATCHES:
            assert condition.url_value is not None
            url = self.page.url
            observed["url"] = url
            return (
                self._url_matches(url, condition.url_value, condition.url_match),
                observed,
                None,
                None,
            )
        if condition.type == WaitConditionType.LOAD_STATE:
            # Satisfied if Playwright reports the state without waiting further.
            assert condition.load_state is not None
            state = condition.load_state.value
            observed["load_state"] = state
            try:
                self.page.wait_for_load_state(state, timeout=1)
                observed["load_state_reached"] = True
                return True, observed, None, None
            except PlaywrightTimeoutError:
                observed["load_state_reached"] = False
                return False, observed, None, None
            except PlaywrightError as exc:
                observed["error"] = str(exc)
                return None, observed, None, "wait_observation_failed"

        assert condition.locator is not None
        resolved = self._resolve_scoped_target(
            condition.locator,
            frame=condition.frame,
            frame_path=condition.frame_path,
            cardinality=cardinality,
        )
        observed["match_count"] = resolved.match_count

        if condition.type == WaitConditionType.ELEMENT_HIDDEN:
            if resolved.failure_kind in (
                "zero_after_primary",
                "zero_after_constraints",
                "missing_container",
            ):
                observed["hidden_reason"] = "absent_or_detached"
                return True, observed, resolved.trace, None
            if not resolved.ok or resolved.playwright_locator is None:
                return (
                    False,
                    observed,
                    resolved.trace,
                    resolved.failure_kind or "target_resolution_failed",
                )
            visible = resolved.playwright_locator.is_visible()
            observed["visible"] = visible
            return (not visible), observed, resolved.trace, None

        if not resolved.ok or resolved.playwright_locator is None:
            if resolved.failure_kind in (
                "multiple_after_primary",
                "multiple_after_constraints",
                "ambiguous_container",
                "ambiguous_frame",
                "missing_frame",
                "detached_frame",
                "not_a_frame",
            ):
                return (
                    False,
                    observed,
                    resolved.trace,
                    resolved.failure_kind,
                )
            # Zero matches: not yet satisfied for visible/text/etc.
            return False, observed, resolved.trace, None

        loc = resolved.playwright_locator
        if condition.type == WaitConditionType.ELEMENT_VISIBLE:
            visible = loc.is_visible()
            observed["visible"] = visible
            return visible, observed, resolved.trace, None
        if condition.type == WaitConditionType.TEXT_PRESENT:
            assert condition.text_value is not None
            visible = loc.is_visible()
            text = loc.inner_text() if visible else (loc.text_content() or "")
            observed["text"] = text
            return (
                self._text_matches(text or "", condition.text_value, condition.text_match),
                observed,
                resolved.trace,
                None,
            )
        if condition.type == WaitConditionType.ATTRIBUTE_EQUALS:
            assert condition.attribute_name is not None
            actual = loc.get_attribute(condition.attribute_name)
            if condition.attribute_name == "value":
                try:
                    actual = loc.input_value()
                except PlaywrightError:
                    pass
            observed["attribute_name"] = condition.attribute_name
            observed["attribute_value"] = actual
            return actual == condition.attribute_value, observed, resolved.trace, None
        if condition.type == WaitConditionType.VALUE_EQUALS:
            assert condition.value is not None
            try:
                actual = loc.input_value()
            except PlaywrightError as exc:
                observed["error"] = str(exc)
                return None, observed, resolved.trace, "wait_observation_failed"
            observed["value"] = actual
            return actual == condition.value, observed, resolved.trace, None
        if condition.type == WaitConditionType.CHECKED_EQUALS:
            assert condition.checked is not None
            try:
                actual = bool(loc.is_checked())
            except PlaywrightError as exc:
                observed["error"] = str(exc)
                return None, observed, resolved.trace, "wait_observation_failed"
            observed["checked"] = actual
            return actual == condition.checked, observed, resolved.trace, None
        if condition.type == WaitConditionType.SELECTED_VALUE_EQUALS:
            assert condition.selected_value is not None
            kind = self._control_kind(loc)
            observed["control_kind"] = kind
            if kind.get("tag") != "select":
                return False, observed, resolved.trace, "target_not_select"
            try:
                actual = loc.input_value()
            except PlaywrightError as exc:
                observed["error"] = str(exc)
                return None, observed, resolved.trace, "wait_observation_failed"
            observed["selected_value"] = actual
            return actual == condition.selected_value, observed, resolved.trace, None
        if condition.type == WaitConditionType.ELEMENT_IN_VIEWPORT:
            assert condition.in_viewport is not None
            actual = self._element_in_viewport(loc)
            observed["in_viewport"] = actual
            if actual is None:
                return None, observed, resolved.trace, "viewport_state_not_observable"
            return actual == condition.in_viewport, observed, resolved.trace, None
        if condition.type in (
            WaitConditionType.VIDEO_ENDED,
            WaitConditionType.VIDEO_PLAYING,
            WaitConditionType.VIDEO_COMPLETED_ONCE,
        ):
            kind = self._control_kind(loc)
            observed["control_kind"] = kind
            if kind.get("tag") != "video":
                return False, observed, resolved.trace, "target_not_video"
            try:
                state = loc.evaluate(
                    """(el) => {
                      window.__dddMediaTokens ||= new WeakMap();
                      window.__dddMediaTokenCounter ||= 0;
                      if (!window.__dddMediaTokens.has(el)) {
                        window.__dddMediaTokens.set(el, ++window.__dddMediaTokenCounter);
                      }
                      return ({
                      ended: !!el.ended,
                      paused: !!el.paused,
                      loop: !!el.loop,
                      currentTime: el.currentTime,
                      duration: el.duration,
                      playbackRate: el.playbackRate,
                      readyState: el.readyState,
                      currentSrc: el.currentSrc,
                      elementToken: window.__dddMediaTokens.get(el),
                    });
                    }"""
                )
            except PlaywrightError as exc:
                observed["error"] = str(exc)
                return None, observed, resolved.trace, "wait_observation_failed"
            observed.update(state)
            if condition.type == WaitConditionType.VIDEO_ENDED:
                return bool(state.get("ended")), observed, resolved.trace, None
            if condition.type == WaitConditionType.VIDEO_COMPLETED_ONCE:
                return (
                    bool(state.get("ended")) and not bool(state.get("loop")),
                    observed,
                    resolved.trace,
                    None,
                )
            return False, observed, resolved.trace, None

        return None, observed, resolved.trace, "unsupported_wait_condition"

    def _dispatch_wait_for(
        self,
        operation: Operation,
        *,
        collector: EvidenceCollector,
        started: int,
        plan_timing: Any | None = None,
    ) -> ActionDispatchResult:
        from dingdongditch.runtime.plan_timing import (
            apply_extension_decision,
            compute_video_ended_extension,
        )

        action = operation.action
        assert action.wait_condition is not None
        condition = action.wait_condition
        timeout_ms = action.resolved_wait_timeout_ms()
        deadline = started + timeout_ms
        if plan_timing is not None and plan_timing.plan_deadline_ms is not None:
            deadline = min(deadline, plan_timing.plan_deadline_ms)
        observations = 0
        last_observed: dict[str, Any] = {}
        last_trace: TargetResolutionTrace | None = None
        timing_meta: dict[str, Any] | None = None
        first_media_state: dict[str, Any] | None = None
        previous_media_state: dict[str, Any] | None = None
        media_progressed = False
        media_near_end = False
        media_identity_invalid = False

        # load_state: wait once with remaining budget (not a busy poll for "already there")
        if condition.type == WaitConditionType.LOAD_STATE:
            assert condition.load_state is not None
            remaining = max(1, deadline - monotonic_ms())
            evidence: dict[str, Any] = {
                "type": "wait_for",
                "condition_type": condition.type.value,
                "requested_timeout_ms": timeout_ms,
                "load_state": condition.load_state.value,
                "dispatched": True,
                "already_satisfied": False,
            }
            try:
                self.page.wait_for_load_state(
                    condition.load_state.value, timeout=remaining
                )
                completed = monotonic_ms()
                evidence.update(
                    {
                        "condition_satisfied": True,
                        "timeout_occurred": False,
                        "elapsed_ms": completed - started,
                        "observation_count": 1,
                        "final_observed_state": {
                            "load_state": condition.load_state.value,
                            "load_state_reached": True,
                        },
                    }
                )
                collector.add(
                    kind=SignalKind.ACTION_RESULT,
                    collected_at_ms=completed,
                    payload={"ok": True, **evidence},
                )
                return ActionDispatchResult(
                    ok=True,
                    error=None,
                    started_at_ms=started,
                    completed_at_ms=completed,
                    action_evidence=evidence,
                )
            except PlaywrightTimeoutError:
                completed = monotonic_ms()
                evidence.update(
                    {
                        "condition_satisfied": False,
                        "timeout_occurred": True,
                        "elapsed_ms": completed - started,
                        "observation_count": 1,
                        "final_observed_state": {
                            "load_state": condition.load_state.value,
                            "load_state_reached": False,
                        },
                    }
                )
                collector.add(
                    kind=SignalKind.ACTION_RESULT,
                    collected_at_ms=completed,
                    payload={"ok": True, **evidence},
                )
                return ActionDispatchResult(
                    ok=True,
                    error=None,
                    started_at_ms=started,
                    completed_at_ms=completed,
                    action_evidence=evidence,
                )
            except PlaywrightError as exc:
                completed = monotonic_ms()
                return ActionDispatchResult(
                    ok=False,
                    error=str(exc),
                    started_at_ms=started,
                    completed_at_ms=completed,
                    failure_kind="wait_observation_failed",
                    action_evidence={
                        **evidence,
                        "condition_satisfied": False,
                        "timeout_occurred": False,
                        "elapsed_ms": completed - started,
                    },
                )

        while True:
            observations += 1
            satisfied, observed, trace, fail_kind = self._observe_wait_condition(
                condition, cardinality=operation.cardinality
            )
            last_observed = observed
            if trace is not None:
                last_trace = trace

            if condition.type in (
                WaitConditionType.VIDEO_PLAYING,
                WaitConditionType.VIDEO_COMPLETED_ONCE,
            ) and fail_kind is None and "currentTime" in observed:
                if first_media_state is None:
                    first_media_state = dict(observed)
                if previous_media_state is not None:
                    same_source = (
                        observed.get("currentSrc") == previous_media_state.get("currentSrc")
                    )
                    same_element = (
                        observed.get("elementToken")
                        == previous_media_state.get("elementToken")
                    )
                    if not same_source or not same_element:
                        media_identity_invalid = True
                    current = float(observed.get("currentTime") or 0)
                    previous = float(previous_media_state.get("currentTime") or 0)
                    duration = float(observed.get("duration") or 0)
                    if same_source and current > previous and not observed.get("paused"):
                        media_progressed = True
                    if duration > 0 and previous >= max(0.0, duration - 0.75):
                        media_near_end = True
                    if condition.type == WaitConditionType.VIDEO_PLAYING:
                        satisfied = bool(
                            same_source
                            and same_element
                            and not media_identity_invalid
                            and media_progressed
                            and not observed.get("paused")
                            and not observed.get("ended")
                            and int(observed.get("readyState") or 0) >= 2
                        )
                    elif observed.get("loop"):
                        satisfied = bool(
                            same_source
                            and same_element
                            and not media_identity_invalid
                            and media_progressed
                            and media_near_end
                            and current < previous
                            and current <= 1.0
                            and not observed.get("paused")
                        )
                previous_media_state = dict(observed)

            # Ambiguity / hard target failures abort immediately (not a soft timeout).
            if fail_kind in (
                "multiple_after_primary",
                "multiple_after_constraints",
                "ambiguous_container",
                "ambiguous_frame",
                "missing_frame",
                "detached_frame",
                "not_a_frame",
                "target_not_select",
                "target_not_video",
            ):
                completed = monotonic_ms()
                evidence = {
                    "type": "wait_for",
                    "condition_type": condition.type.value,
                    "requested_timeout_ms": timeout_ms,
                    "condition_satisfied": False,
                    "timeout_occurred": False,
                    "elapsed_ms": completed - started,
                    "observation_count": observations,
                    "final_observed_state": last_observed,
                    "dispatched": True,
                }
                return ActionDispatchResult(
                    ok=False,
                    error=fail_kind,
                    started_at_ms=started,
                    completed_at_ms=completed,
                    resolution_trace=last_trace,
                    failure_kind=fail_kind,
                    action_evidence=evidence,
                )

            if satisfied is True:
                completed = monotonic_ms()
                evidence = {
                    "type": "wait_for",
                    "condition_type": condition.type.value,
                    "requested_timeout_ms": timeout_ms,
                    "condition_satisfied": True,
                    "timeout_occurred": False,
                    "elapsed_ms": completed - started,
                    "observation_count": observations,
                    "final_observed_state": last_observed,
                    "dispatched": True,
                }
                if timing_meta is not None:
                    evidence["adaptive_timing"] = timing_meta
                collector.add(
                    kind=SignalKind.ACTION_RESULT,
                    collected_at_ms=completed,
                    payload={"ok": True, **evidence},
                )
                return ActionDispatchResult(
                    ok=True,
                    error=None,
                    started_at_ms=started,
                    completed_at_ms=completed,
                    resolution_trace=last_trace,
                    action_evidence=evidence,
                )

            if satisfied is None and fail_kind == "wait_observation_failed":
                completed = monotonic_ms()
                return ActionDispatchResult(
                    ok=False,
                    error="wait observation failed",
                    started_at_ms=started,
                    completed_at_ms=completed,
                    resolution_trace=last_trace,
                    failure_kind=fail_kind,
                    action_evidence={
                        "type": "wait_for",
                        "condition_type": condition.type.value,
                        "requested_timeout_ms": timeout_ms,
                        "condition_satisfied": False,
                        "timeout_occurred": False,
                        "elapsed_ms": completed - started,
                        "observation_count": observations,
                        "final_observed_state": last_observed,
                    },
                )

            # Adaptive extension: video_ended only, from observed media facts.
            if (
                condition.type == WaitConditionType.VIDEO_ENDED
                and plan_timing is not None
                and plan_timing.adaptive_timeout_enabled
                and satisfied is False
                and fail_kind is None
                and "duration" in last_observed
            ):
                now = monotonic_ms()
                decision = compute_video_ended_extension(
                    observed=last_observed,
                    now_ms=now,
                    wait_deadline_ms=deadline,
                    plan_timing=plan_timing,
                )
                if decision.granted_extension_ms > 0:
                    timing_meta = decision.to_dict()
                    deadline = apply_extension_decision(
                        decision=decision,
                        wait_deadline_ms=deadline,
                        plan_timing=plan_timing,
                    )
                    if (
                        plan_timing.plan_deadline_ms is not None
                        and deadline > plan_timing.plan_deadline_ms
                    ):
                        deadline = plan_timing.plan_deadline_ms
                elif decision.extension_reason not in (
                    "adaptation_disabled",
                    "no_extension_needed",
                    "already_ended",
                ):
                    # Record explicit non-grants once for receipt evidence.
                    timing_meta = decision.to_dict()
                    if not any(
                        d.extension_reason == decision.extension_reason
                        for d in plan_timing.decisions
                    ):
                        plan_timing.decisions.append(decision)

            now = monotonic_ms()
            if plan_timing is not None and plan_timing.expired(now):
                completed = now
                evidence = {
                    "type": "wait_for",
                    "condition_type": condition.type.value,
                    "requested_timeout_ms": timeout_ms,
                    "condition_satisfied": False,
                    "timeout_occurred": True,
                    "timeout_kind": "plan_deadline",
                    "elapsed_ms": completed - started,
                    "observation_count": observations,
                    "final_observed_state": last_observed,
                    "dispatched": True,
                    "failure_kind": "plan_deadline_expired",
                }
                if timing_meta is not None:
                    evidence["adaptive_timing"] = timing_meta
                collector.add(
                    kind=SignalKind.ACTION_RESULT,
                    collected_at_ms=completed,
                    payload={"ok": True, **evidence},
                )
                return ActionDispatchResult(
                    ok=True,
                    error=None,
                    started_at_ms=started,
                    completed_at_ms=completed,
                    resolution_trace=last_trace,
                    failure_kind="plan_deadline_expired",
                    action_evidence=evidence,
                )

            if now >= deadline:
                completed = now
                evidence = {
                    "type": "wait_for",
                    "condition_type": condition.type.value,
                    "requested_timeout_ms": timeout_ms,
                    "condition_satisfied": False,
                    "timeout_occurred": True,
                    "timeout_kind": "wait_timeout",
                    "elapsed_ms": completed - started,
                    "observation_count": observations,
                    "final_observed_state": last_observed,
                    "dispatched": True,
                }
                if timing_meta is not None:
                    evidence["adaptive_timing"] = timing_meta
                collector.add(
                    kind=SignalKind.ACTION_RESULT,
                    collected_at_ms=completed,
                    payload={"ok": True, **evidence},
                )
                return ActionDispatchResult(
                    ok=True,
                    error=None,
                    started_at_ms=started,
                    completed_at_ms=completed,
                    resolution_trace=last_trace,
                    action_evidence=evidence,
                )

            self.page.wait_for_timeout(WAIT_POLL_INTERVAL_MS)

    def dispatch(
        self,
        operation: Operation,
        *,
        collector: EvidenceCollector,
        plan_timing: Any | None = None,
    ) -> ActionDispatchResult:
        """Install the dialog listener before dispatch and attach evidence."""
        contract = operation.dialog_contract or DialogContract()
        contract.validate()
        observed: list[dict[str, Any]] = []
        listener_started = monotonic_ms()
        page_id = self.page_id

        def on_dialog(dialog: Any) -> None:
            appeared = monotonic_ms()
            entry: dict[str, Any] = {
                "triggering_operation_id": operation.operation_id,
                "page_id": page_id,
                "dialog_type": dialog.type,
                "message": dialog.message,
                "appeared_at_ms": appeared,
                "action_taken": None,
                "prompt_text": None,
                "handling_started_at_ms": appeared,
                "handled_at_ms": None,
                "handling_duration_ms": None,
                "contract_authorized": False,
                "cleanup_only": False,
            }
            observed.append(entry)
            expected_type = contract.dialog_type.value if contract.dialog_type else None
            message_ok = contract.message is None or (
                contract.message in dialog.message
                if contract.message_contains
                else contract.message == dialog.message
            )
            authorized = (
                contract.requirement != DialogRequirement.FORBIDDEN
                and dialog.type == expected_type
                and message_ok
                and (dialog.type != "prompt" or contract.action == DialogAction.DISMISS or contract.prompt_text is not None)
            )
            entry["contract_authorized"] = authorized
            if authorized:
                entry["action_taken"] = contract.action.value
                if contract.action == DialogAction.ACCEPT:
                    entry["prompt_text"] = "[REDACTED]" if contract.redact_prompt_text and contract.prompt_text else contract.prompt_text
                    dialog.accept(prompt_text=contract.prompt_text)
                else:
                    dialog.dismiss()
            else:
                entry["cleanup_only"] = True
                entry["action_taken"] = "dismiss"
                # Emergency dismissal prevents a blocking native dialog from
                # leaking a page/browser resource; it never makes the action pass.
                try:
                    dialog.dismiss()
                except Exception:
                    pass
            handled = monotonic_ms()
            entry["handled_at_ms"] = handled
            entry["handling_duration_ms"] = max(0, handled - appeared)
            self._dialog_history.append(dict(entry))

        self.page.on("dialog", on_dialog)
        try:
            result = self._dispatch_core(operation, collector=collector, plan_timing=plan_timing)
        finally:
            try:
                self.page.remove_listener("dialog", on_dialog)
            except Exception:
                pass

        evidence = dict(result.action_evidence or {})
        contract_desc = contract.describe()
        evidence["dialog_policy"] = contract_desc
        evidence["dialogs"] = [dict(item) for item in observed]
        evidence["dialog_appeared"] = bool(observed)
        evidence["dialog_history_size"] = len(self._dialog_history)
        evidence["dialog_deadline_expired"] = bool(
            plan_timing is not None
            and plan_timing.plan_deadline_ms is not None
            and monotonic_ms() >= plan_timing.plan_deadline_ms
        )
        failure: str | None = None
        error: str | None = result.error
        if contract.requirement == DialogRequirement.REQUIRED and not observed:
            failure = "expected_dialog_not_appeared"
            error = "expected dialog did not appear"
        elif len(observed) > 1:
            failure = "multiple_dialogs_opened"
            error = "multiple dialogs appeared; exactly one was expected"
        elif observed:
            dialog = observed[0]
            expected_type = contract.dialog_type.value if contract.dialog_type else None
            if contract.requirement == DialogRequirement.FORBIDDEN:
                failure = "unexpected_dialog"
                error = "unexpected dialog appeared and was emergency-dismissed"
            elif dialog["dialog_type"] != expected_type:
                failure = "dialog_type_mismatch"
                error = "dialog type did not match declared contract"
            elif contract.message is not None and not (
                contract.message in dialog["message"] if contract.message_contains else contract.message == dialog["message"]
            ):
                failure = "dialog_message_mismatch"
                error = "dialog message did not match declared contract"
            elif contract.dialog_type is not None and contract.dialog_type.value == "prompt" and contract.action == DialogAction.ACCEPT and contract.prompt_text is None:
                failure = "prompt_text_missing"
                error = "prompt text was required but absent"
            elif not dialog["contract_authorized"]:
                failure = "dialog_handling_failed"
                error = "dialog was not authorized by the declared contract"
        if failure is not None:
            return ActionDispatchResult(
                ok=False,
                error=error,
                started_at_ms=result.started_at_ms,
                completed_at_ms=monotonic_ms(),
                recovery_attempts=result.recovery_attempts,
                match_count=result.match_count,
                resolution_trace=result.resolution_trace,
                failure_kind=failure,
                action_evidence=evidence,
            )
        result.action_evidence = evidence
        return result

    def _dispatch_pointer_move(
        self,
        operation: Operation,
        *,
        collector: EvidenceCollector,
        started: int,
        x: float,
        y: float,
        target_resolution: TargetResolutionTrace | None,
        match_count: int | None,
        origin: PointerOrigin,
        bounding_box: dict[str, float] | None = None,
        scrolled_into_view: bool = False,
        recovery: list[dict[str, Any]] | None = None,
    ) -> ActionDispatchResult:
        """Move the pointer and receipt the exact resolved viewport point."""
        request = operation.action.pointer_request
        assert request is not None
        viewport = self.page.viewport_size
        evidence: dict[str, Any] = {
            "type": ActionType.POINTER_MOVE.value,
            "origin": origin.value,
            "requested": request.describe(),
            "resolved_position": {"x": x, "y": y},
            "viewport": dict(viewport) if viewport is not None else None,
            "bounding_box": bounding_box,
            "scrolled_into_view": scrolled_into_view,
            "steps": request.steps,
            "previous_position": (
                {"x": self._pointer_position[0], "y": self._pointer_position[1]}
                if self._pointer_position is not None
                and self._pointer_page_id == self.page_id
                else None
            ),
            "dispatched": False,
            "already_satisfied": False,
            "position_verification": {
                "requested": request.verify_position,
                "method": "backend_command_state",
                "verified": False,
            },
        }
        if viewport is None:
            return ActionDispatchResult(
                ok=False,
                error="pointer movement requires a finite browser viewport",
                started_at_ms=started,
                completed_at_ms=monotonic_ms(),
                recovery_attempts=list(recovery or ()),
                match_count=match_count,
                resolution_trace=target_resolution,
                failure_kind="pointer_viewport_unavailable",
                action_evidence=evidence,
            )
        width = float(viewport["width"])
        height = float(viewport["height"])
        if not (0 <= x < width and 0 <= y < height):
            return ActionDispatchResult(
                ok=False,
                error=(
                    f"resolved pointer position ({x:g}, {y:g}) is outside "
                    f"viewport {width:g}x{height:g}"
                ),
                started_at_ms=started,
                completed_at_ms=monotonic_ms(),
                recovery_attempts=list(recovery or ()),
                match_count=match_count,
                resolution_trace=target_resolution,
                failure_kind="pointer_coordinates_out_of_viewport",
                action_evidence=evidence,
            )

        self.page.mouse.move(x, y, steps=request.steps)
        self._pointer_position = (x, y)
        self._pointer_page_id = self.page_id
        evidence["dispatched"] = True
        evidence["final_position"] = {"x": x, "y": y}
        evidence["position_verification"] = {
            "requested": request.verify_position,
            "method": "backend_command_state",
            "verified": bool(
                request.verify_position
                and self._pointer_position == (x, y)
                and self._pointer_page_id == self.page_id
            ),
        }
        completed = monotonic_ms()
        collector.add(
            kind=SignalKind.ACTION_RESULT,
            collected_at_ms=completed,
            payload={
                "ok": True,
                "action": ActionType.POINTER_MOVE.value,
                "match_count": match_count,
                "locator": (
                    operation.action.locator.describe()
                    if operation.action.locator is not None
                    else None
                ),
                "target_resolution": (
                    target_resolution.to_dict()
                    if target_resolution is not None
                    else None
                ),
                "action_evidence": evidence,
            },
        )
        return ActionDispatchResult(
            ok=True,
            error=None,
            started_at_ms=started,
            completed_at_ms=completed,
            recovery_attempts=list(recovery or ()),
            match_count=match_count,
            resolution_trace=target_resolution,
            action_evidence=evidence,
        )

    def _upload_snapshot(self, loc: Any, token: str) -> dict[str, Any]:
        return loc.evaluate(
            """(el, token) => {
              const scope = (el.parentElement && el.parentElement.closest('[data-testid],fieldset,label,[class*="upload"],[class*="attachment"],[class*="field"],form')) || el.parentElement || el;
              scope.setAttribute('data-ddd-upload-scope', token);
              const visible = n => {
                const r = n.getBoundingClientRect(), s = getComputedStyle(n);
                return n.isConnected && s.visibility !== 'hidden' && s.display !== 'none'
                  && r.width > 0 && r.height > 0;
              };
              return {
                target: {
                  tag: (el.tagName || '').toLowerCase(),
                  type: (el.getAttribute('type') || '').toLowerCase(),
                  id: el.id || null, name: el.getAttribute('name'),
                  accept: el.getAttribute('accept'), multiple: el.hasAttribute('multiple'),
                  aria_label: el.getAttribute('aria-label'),
                },
                scope: {tag: (scope.tagName || '').toLowerCase(), id: scope.id || null},
                file_names: Array.from(el.files || [], f => String(f.name)),
                visible_text: visible(scope) ? (scope.innerText || '').slice(0, 500) : '',
                url: location.href,
              };
            }""",
            token,
        )

    def _upload_post_snapshot(self, token: str, expected: list[str]) -> dict[str, Any]:
        return self.page.evaluate(
            """({token, expected}) => {
              const visible = n => {
                const r = n.getBoundingClientRect(), s = getComputedStyle(n);
                return n.isConnected && s.visibility !== 'hidden' && s.display !== 'none'
                  && r.width > 0 && r.height > 0;
              };
              const scope = document.querySelector(`[data-ddd-upload-scope="${CSS.escape(token)}"]`);
              const root = scope || document.body;
              const inputs = [...(root.matches && root.matches('input[type=file]') ? [root] : []),
                ...Array.from(root.querySelectorAll('input[type=file]'))];
              const fileLists = inputs.map(el => Array.from(el.files || [], f => String(f.name)));
              const text = visible(root) ? (root.innerText || '') : '';
              const filenameHits = expected.filter(name => text.includes(name));
              const controls = Array.from(root.querySelectorAll('button,[role=button],a'))
                .filter(visible).map(n => (n.innerText || n.getAttribute('aria-label') || '').trim())
                .filter(t => /^(remove|delete|replace)(\\s+file)?$/i.test(t)).slice(0, 10);
              if (scope) scope.removeAttribute('data-ddd-upload-scope');
              return {
                scope_retained: !!scope,
                replacement_input_count: inputs.length,
                file_lists: fileLists,
                visible_filename_hits: filenameHits,
                attachment_controls: controls,
                url: location.href,
              };
            }""",
            {"token": token, "expected": expected},
        )

    def _dispatch_combobox_selection(
        self, operation: Operation, loc: Any, resolved: Any, started: int,
        evidence: dict[str, Any], effective_timeout_ms: int,
    ) -> ActionDispatchResult:
        from dingdongditch.contract.modes import TextMatchMode

        request = operation.action.combobox_selection
        assert request is not None
        target = loc.evaluate(
            """el => ({tag:(el.tagName||'').toLowerCase(), role:el.getAttribute('role'),
              aria_controls:el.getAttribute('aria-controls'), aria_expanded:el.getAttribute('aria-expanded'), read_only:!!el.readOnly,
              value:'value' in el ? String(el.value || '') : '',
              wrapper_text:(() => { const w=el.closest('[data-testid],label,[class*=field],fieldset') || el.parentElement || el;
                const c=w.cloneNode(true); c.querySelectorAll('[role=listbox],[role=option],[data-options],[data-listbox]').forEach(n=>n.remove());
                return (c.innerText||'').slice(0,500); })()})"""
        )
        pre_wrapper_text = target.pop("wrapper_text", "")
        target["wrapper_text_length"] = len(pre_wrapper_text)
        combo_evidence: dict[str, Any] = {
            "query": request.query, "expected_option": request.expected_option,
            "match_strategy": request.match.value, "target_state_before": target,
            "candidate_options": [], "selected_option": None,
            "verification_result": "not_verified", "timing": {"started_at_ms": started},
        }
        if target["tag"] == "select" or target["tag"] not in {"input", "textarea", "button", "div"}:
            return ActionDispatchResult(False, "unsupported custom combobox target", started, monotonic_ms(),
                match_count=1, resolution_trace=resolved.trace, failure_kind="unsupported_combobox",
                action_evidence={**evidence, "combobox": combo_evidence})
        try:
            loc.focus(timeout=min(effective_timeout_ms, request.dropdown_timeout_ms))
            if request.clear_existing and target["tag"] in {"input", "textarea"} and not target.get("read_only"):
                loc.fill("")
            if request.query:
                if target["tag"] in {"input", "textarea"}:
                    loc.fill(request.query)
                else:
                    loc.press(request.query)
            else:
                loc.click()
        except PlaywrightError:
            return ActionDispatchResult(False, "combobox query dispatch failed", started, monotonic_ms(),
                match_count=1, resolution_trace=resolved.trace, failure_kind="unsupported_combobox",
                action_evidence={**evidence, "combobox": combo_evidence})

        deadline = monotonic_ms() + min(effective_timeout_ms, request.dropdown_timeout_ms)
        candidates: list[tuple[Any, str]] = []
        while monotonic_ms() < deadline:
            controls = target.get("aria_controls")
            if controls:
                root = self.page.locator(f'[id="{controls.replace(chr(34), chr(92)+chr(34))}"]')
                option_set = root.locator('[role="option"], [data-option], [data-value], li')
            else:
                option_set = self.page.locator(
                    '[role="listbox"]:visible [role="option"], [role="option"]:visible, '
                    '[data-listbox]:visible [data-option], [data-options]:visible [data-option]'
                )
                if option_set.count() == 0:
                    option_set = loc.locator(
                        "xpath=following::*[@role='listbox' or @data-listbox or @data-options][1]"
                    ).locator('[role="option"], [data-option], [data-value], li')
            candidates = []
            for item in option_set.all()[:50]:
                try:
                    if item.is_visible():
                        label = (item.inner_text() or item.get_attribute("aria-label") or "").strip()
                        if label:
                            candidates.append((item, label[:200]))
                except PlaywrightError:
                    continue
            if candidates:
                break
            self.page.wait_for_timeout(100)
        combo_evidence["candidate_options"] = [label for _, label in candidates]
        combo_evidence["timing"]["options_observed_at_ms"] = monotonic_ms()
        if not candidates:
            try:
                dropdown_opened = loc.get_attribute("aria-expanded") == "true"
            except PlaywrightError:
                dropdown_opened = False
            combo_evidence["dropdown_opened"] = dropdown_opened
            return ActionDispatchResult(False, "combobox dropdown did not expose options", started, monotonic_ms(),
                match_count=0, resolution_trace=resolved.trace,
                failure_kind="no_matching_option" if dropdown_opened else "dropdown_not_opened",
                action_evidence={**evidence, "combobox": combo_evidence})
        expected = request.expected_option
        if request.match == TextMatchMode.EXACT:
            matches = [(item, label) for item, label in candidates if label == expected]
        else:
            matches = [(item, label) for item, label in candidates if expected in label]
        if not matches:
            return ActionDispatchResult(False, "no combobox option matched", started, monotonic_ms(),
                match_count=0, resolution_trace=resolved.trace, failure_kind="no_matching_option",
                action_evidence={**evidence, "combobox": combo_evidence})
        if len(matches) != 1:
            return ActionDispatchResult(False, "combobox option match was ambiguous", started, monotonic_ms(),
                match_count=len(matches), resolution_trace=resolved.trace, failure_kind="ambiguous_option",
                action_evidence={**evidence, "combobox": combo_evidence})
        option, observed_label = matches[0]
        try:
            if not option.is_visible() or (option.inner_text() or "").strip()[:200] != observed_label:
                raise RuntimeError("stale")
        except Exception:
            return ActionDispatchResult(False, "combobox options changed before selection", started, monotonic_ms(),
                match_count=1, resolution_trace=resolved.trace, failure_kind="stale_combobox_state",
                action_evidence={**evidence, "combobox": combo_evidence})
        try:
            option.click(timeout=min(effective_timeout_ms, request.dropdown_timeout_ms))
        except PlaywrightError:
            return ActionDispatchResult(False, "combobox option click failed", started, monotonic_ms(),
                match_count=1, resolution_trace=resolved.trace, failure_kind="option_click_failed",
                action_evidence={**evidence, "combobox": combo_evidence})
        combo_evidence["selected_option"] = observed_label
        persisted = False
        final_state: dict[str, Any] = {}
        verify_deadline = monotonic_ms() + min(2000, request.dropdown_timeout_ms)
        while monotonic_ms() < verify_deadline:
            fresh = self._resolve_scoped_target(
                operation.action.locator,
                frame=operation.action.frame,
                frame_path=operation.action.frame_path,
                cardinality=operation.cardinality,
            )
            if fresh.ok and fresh.playwright_locator is not None:
                try:
                    final_state = fresh.playwright_locator.evaluate(
                        """(el, expected) => { const wrapper=el.closest('[data-testid],label,[class*=field],fieldset')||el.parentElement||el;
                        const c=wrapper.cloneNode(true); c.querySelectorAll('[role=listbox],[role=option],[data-options],[data-listbox]').forEach(n=>n.remove());
                        return {value:'value' in el?String(el.value||''):'', aria_expanded:el.getAttribute('aria-expanded'),
                          wrapper_text:(c.innerText||'').slice(0,500), expected}; }""", expected)
                    value_ok = final_state["value"] == expected or (
                        request.match == TextMatchMode.CONTAINS and expected in final_state["value"]
                    )
                    final_wrapper_text = final_state.pop("wrapper_text", "")
                    text_changed = final_wrapper_text != pre_wrapper_text and expected in final_wrapper_text
                    final_state["wrapper_contains_selected_option"] = expected in final_wrapper_text
                    final_state["wrapper_text_length"] = len(final_wrapper_text)
                    closed = final_state["aria_expanded"] != "true"
                    persisted = bool(closed and (value_ok or text_changed))
                except PlaywrightError:
                    persisted = False
            if persisted:
                break
            self.page.wait_for_timeout(100)
        combo_evidence["final_state"] = final_state
        combo_evidence["verification_result"] = "pass" if persisted else "fail"
        combo_evidence["timing"]["completed_at_ms"] = monotonic_ms()
        if not persisted:
            return ActionDispatchResult(False, "combobox selection did not persist", started, monotonic_ms(),
                match_count=1, resolution_trace=resolved.trace, failure_kind="selection_not_persisted",
                action_evidence={**evidence, "combobox": combo_evidence})
        return ActionDispatchResult(True, None, started, monotonic_ms(), match_count=1,
            resolution_trace=resolved.trace, action_evidence={**evidence, "combobox": combo_evidence})

    def _dispatch_core(
        self,
        operation: Operation,
        *,
        collector: EvidenceCollector,
        plan_timing: Any | None = None,
    ) -> ActionDispatchResult:
        action = operation.action
        started = monotonic_ms()
        effective_timeout_ms = operation.timeout_ms
        if plan_timing is not None and plan_timing.plan_deadline_ms is not None:
            effective_timeout_ms = min(
                effective_timeout_ms,
                max(1, plan_timing.plan_deadline_ms - started),
            )
        recovery: list[dict[str, Any]] = []
        last_trace: TargetResolutionTrace | None = None
        try:
            if action.type == ActionType.NAVIGATE:
                self.page.goto(
                    operation.url,
                    wait_until="domcontentloaded",
                    timeout=effective_timeout_ms,
                )
                try:
                    self.page.wait_for_load_state(
                        "domcontentloaded", timeout=min(5_000, effective_timeout_ms)
                    )
                except Exception:
                    pass
                completed = monotonic_ms()
                evidence = {
                    "type": action.type.value,
                    "dispatched": True,
                    "already_satisfied": False,
                }
                collector.add(
                    kind=SignalKind.ACTION_RESULT,
                    collected_at_ms=completed,
                    payload={"ok": True, "action": action.type.value, **evidence},
                )
                return ActionDispatchResult(
                    ok=True,
                    error=None,
                    started_at_ms=started,
                    completed_at_ms=completed,
                    recovery_attempts=recovery,
                    action_evidence=evidence,
                )

            if action.type == ActionType.WAIT_FOR:
                return self._dispatch_wait_for(
                    operation,
                    collector=collector,
                    started=started,
                    plan_timing=plan_timing,
                )

            if action.type in (
                ActionType.SWITCH_TO_PAGE,
                ActionType.CLOSE_PAGE,
                ActionType.SWITCH_TO_OPENER,
            ):
                before_id = self.page_id
                try:
                    if action.type == ActionType.SWITCH_TO_PAGE:
                        assert action.page_id is not None
                        self._activate_page(action.page_id)
                    elif action.type == ActionType.SWITCH_TO_OPENER:
                        current = self._pages.get(str(self.page_id))
                        if current is None or current.opener_page_id is None:
                            raise ValueError("active page has no known opener")
                        self._activate_page(current.opener_page_id)
                    else:
                        assert action.page_id is not None
                        entry = self._pages.get(action.page_id)
                        if entry is None:
                            raise ValueError(f"unknown page_id: {action.page_id}")
                        if entry.page_id == self.page_id:
                            raise ValueError("close_page cannot close the active page")
                        entry.page.close()
                    completed = monotonic_ms()
                    evidence = {
                        "type": action.type.value,
                        "dispatched": True,
                        "active_page_id_before": before_id,
                        "selected_active_page_id": self.page_id,
                        "switching_occurred": before_id != self.page_id,
                        "page_registry": self.list_pages(),
                    }
                    return ActionDispatchResult(
                        ok=True,
                        error=None,
                        started_at_ms=started,
                        completed_at_ms=completed,
                        action_evidence=evidence,
                    )
                except ValueError as exc:
                    return ActionDispatchResult(
                        ok=False,
                        error=str(exc),
                        started_at_ms=started,
                        completed_at_ms=monotonic_ms(),
                        failure_kind="page_management_failed",
                        action_evidence={
                            "type": action.type.value,
                            "dispatched": False,
                            "active_page_id_before": before_id,
                            "selected_active_page_id": self.page_id,
                            "page_registry": self.list_pages(),
                        },
                    )

            if (
                action.type == ActionType.PRESS_KEY
                and action.resolved_key_scope() == KeyPressScope.ACTIVE_PAGE
            ):
                assert action.key is not None
                self.page.keyboard.press(action.key)
                completed = monotonic_ms()
                evidence = {
                    "type": "press_key",
                    "key": action.key,
                    "dispatch_scope": "active_page",
                    "dispatched": True,
                    "already_satisfied": False,
                    "target_resolved": False,
                }
                collector.add(
                    kind=SignalKind.ACTION_RESULT,
                    collected_at_ms=completed,
                    payload={"ok": True, **evidence},
                )
                return ActionDispatchResult(
                    ok=True,
                    error=None,
                    started_at_ms=started,
                    completed_at_ms=completed,
                    recovery_attempts=recovery,
                    action_evidence=evidence,
                )

            if action.type == ActionType.POINTER_MOVE:
                assert action.pointer_request is not None
                if action.pointer_request.origin == PointerOrigin.VIEWPORT:
                    assert action.pointer_request.x is not None
                    assert action.pointer_request.y is not None
                    return self._dispatch_pointer_move(
                        operation,
                        collector=collector,
                        started=started,
                        x=float(action.pointer_request.x),
                        y=float(action.pointer_request.y),
                        target_resolution=None,
                        match_count=None,
                        origin=PointerOrigin.VIEWPORT,
                    )

            assert action.locator is not None
            deadline = started + operation.locate_retry_ms
            if plan_timing is not None and plan_timing.plan_deadline_ms is not None:
                deadline = min(deadline, plan_timing.plan_deadline_ms)
            attempt = 0
            identity = None
            while True:
                attempt += 1
                if action.frame is None and not action.frame_path:
                    identity = resolve_target_identity(
                        self.page,
                        action.locator,
                        cardinality=operation.cardinality,
                        backend_identity=self.backend_identity,
                    )
                else:
                    framed = resolve_frame_path(
                        self.page,
                        action.frame_path or (action.frame,),
                        backend_identity=self.backend_identity,
                    )
                    if not framed.ok or framed.frame is None:
                        identity = ResolvedTarget(
                            ok=False,
                            playwright_locator=None,
                            match_count=framed.match_count,
                            error=framed.error,
                            failure_kind=framed.failure_kind,
                            trace=framed.trace,
                        )
                    else:
                        identity = resolve_target_identity(
                            framed.frame,
                            action.locator,
                            cardinality=operation.cardinality,
                            backend_identity=self.backend_identity,
                        )
                        identity.trace = merge_frame_trace(
                            framed.trace, identity.trace
                        )
                last_trace = identity.trace
                # Ambiguity may be intentionally resolved by a deferred
                # visibility/enabled constraint after preparation.
                if identity.match_count > 0:
                    break
                if identity.failure_kind in (
                    "zero_after_primary",
                    "zero_after_constraints",
                    "missing_container",
                    "missing_frame",
                    "detached_frame",
                ):
                    if monotonic_ms() >= deadline:
                        completed = monotonic_ms()
                        collector.add(
                            kind=SignalKind.ACTION_RESULT,
                            collected_at_ms=completed,
                            payload={
                                "ok": False,
                                "match_count": identity.match_count,
                                "failure_kind": identity.failure_kind,
                                "target_resolution": identity.trace.to_dict(),
                            },
                            availability=SignalAvailability.OBSERVED,
                            notes="target not found after locate retry window",
                        )
                        return ActionDispatchResult(
                            ok=False,
                            error=(
                                "target not found"
                                if identity.failure_kind
                                in ("zero_after_primary", "missing_container")
                                else (identity.error or "target not found")
                            ),
                            started_at_ms=started,
                            completed_at_ms=completed,
                            recovery_attempts=recovery,
                            match_count=identity.match_count,
                            resolution_trace=identity.trace,
                            failure_kind=identity.failure_kind,
                        )
                    recovery.append(
                        {
                            "reason": "locate_retry",
                            "attempt_index": attempt,
                            "occurred_at_ms": monotonic_ms(),
                            "detail": "target not found; retrying within locate_retry_ms",
                        }
                    )
                    self.page.wait_for_timeout(50)
                    continue

                break

            assert identity is not None
            preparation: dict[str, Any] = {
                "scroll_into_view": "not_applicable",
                "overlay_dismissals": [],
            }
            for overlay_locator in operation.target_preparation.dismiss_overlay_locators:
                overlay = resolve_target_identity(
                    self.page,
                    overlay_locator,
                    backend_identity=self.backend_identity,
                )
                entry = {
                    "locator": overlay_locator.describe(),
                    "match_count": overlay.match_count,
                    "dismissed": False,
                }
                if overlay.match_count == 0:
                    entry["result"] = "not_present"
                    preparation["overlay_dismissals"].append(entry)
                    continue
                if not overlay.ok or overlay.playwright_locator is None:
                    entry["result"] = "ambiguous"
                    preparation["overlay_dismissals"].append(entry)
                    return ActionDispatchResult(
                        ok=False,
                        error="permitted overlay dismissal target was ambiguous",
                        started_at_ms=started,
                        completed_at_ms=monotonic_ms(),
                        recovery_attempts=recovery,
                        match_count=overlay.match_count,
                        resolution_trace=identity.trace,
                        failure_kind="ambiguous_overlay_dismissal",
                        action_evidence={
                            "preparation": preparation,
                            "dispatched": False,
                        },
                    )
                if overlay.playwright_locator.is_visible():
                    overlay.playwright_locator.click(timeout=effective_timeout_ms)
                    entry["dismissed"] = True
                    entry["result"] = "dismissed"
                else:
                    entry["result"] = "not_visible"
                preparation["overlay_dismissals"].append(entry)
            if (
                identity.ok
                and identity.playwright_locator is not None
                and action.type not in (ActionType.SCROLL_TO_TARGET, ActionType.UPLOAD_FILE)
            ):
                already_in_viewport = bool(identity.playwright_locator.evaluate(
                    """el => {
                        const r = el.getBoundingClientRect();
                        return el.isConnected && r.width > 0 && r.height > 0 &&
                          r.bottom > 0 && r.right > 0 &&
                          r.top < window.innerHeight && r.left < window.innerWidth;
                    }"""
                ))
                if already_in_viewport:
                    preparation["scroll_into_view"] = "not_needed"
                else:
                    identity.playwright_locator.scroll_into_view_if_needed(
                        timeout=effective_timeout_ms
                    )
                    preparation["scroll_into_view"] = "completed"
                identity.trace.stages.append(
                    ResolutionStage(
                        stage="preparation",
                        candidates_before=1,
                        candidates_after=1,
                        timestamp_ms=monotonic_ms(),
                        notes="deterministic scroll_into_view_if_needed; no overlay dismissal permitted",
                    )
                )

            resolved = self._resolve_scoped_target(
                action.locator,
                frame=action.frame,
                frame_path=action.frame_path,
                cardinality=operation.cardinality,
            )
            for stage in resolved.trace.stages:
                stage.stage = f"actionability_{stage.stage}"
            resolved.trace.stages = (
                list(identity.trace.stages) + list(resolved.trace.stages)
            )
            last_trace = resolved.trace
            if not resolved.ok or resolved.playwright_locator is None:
                completed = monotonic_ms()
                return ActionDispatchResult(
                    ok=False,
                    error=resolved.error or "target is not actionable",
                    started_at_ms=started,
                    completed_at_ms=completed,
                    recovery_attempts=recovery,
                    match_count=resolved.match_count,
                    resolution_trace=resolved.trace,
                    failure_kind=resolved.failure_kind,
                    action_evidence={"preparation": preparation, "dispatched": False},
                )

            loc = resolved.playwright_locator
            actionability = loc.evaluate(
                """el => {
                  const r = el.getBoundingClientRect();
                  const s = getComputedStyle(el);
                  const visible = el.isConnected
                    && s.visibility !== 'hidden' && s.visibility !== 'collapse'
                    && r.width > 0 && r.height > 0;
                  let disabled = false;
                  try { disabled = el.matches(':disabled'); } catch (_) {}
                  for (let n = el; n; n = n.parentElement) {
                    if ((n.getAttribute('aria-disabled') || '').toLowerCase() === 'true') {
                      disabled = true;
                      break;
                    }
                  }
                  return {connected: el.isConnected, visible, enabled: !disabled};
                }"""
            )
            if action.type == ActionType.UPLOAD_FILE:
                # Hidden file inputs are standard; connected and enabled remain required.
                actionability["visible"] = True
            resolved.trace.stages.append(
                ResolutionStage(
                    stage="actionability",
                    candidates_before=1,
                    candidates_after=1 if all(actionability.values()) else 0,
                    timestamp_ms=monotonic_ms(),
                    notes=f"atomic state check: {actionability}",
                )
            )
            if not all(actionability.values()):
                resolved.trace.dispatch_permitted = False
                resolved.trace.failure_kind = "target_not_actionable"
                resolved.trace.failure_reason = "target failed actionability checks"
                return ActionDispatchResult(
                    ok=False,
                    error=resolved.trace.failure_reason,
                    started_at_ms=started,
                    completed_at_ms=monotonic_ms(),
                    recovery_attempts=recovery,
                    match_count=1,
                    resolution_trace=resolved.trace,
                    failure_kind=resolved.trace.failure_kind,
                    action_evidence={
                        "preparation": preparation,
                        "actionability": actionability,
                        "dispatched": False,
                    },
                )
            evidence: dict[str, Any] = {
                "type": action.type.value,
                "dispatched": True,
                "already_satisfied": False,
                "preparation": preparation,
                "actionability": actionability,
            }

            if action.type == ActionType.SELECT_COMBOBOX_OPTION:
                return self._dispatch_combobox_selection(
                    operation, loc, resolved, started, evidence, effective_timeout_ms
                )

            if action.type == ActionType.DOWNLOAD:
                assert action.download_request is not None
                assert self.browser_session_id is not None
                assert self._context is not None
                request = action.download_request
                deadline = DownloadDeadline.from_limits(
                    started_ms=started,
                    request_ms=request.timeout_ms,
                    operation_ms=operation.timeout_ms,
                    plan_deadline_ms=(
                        plan_timing.plan_deadline_ms
                        if plan_timing is not None else None
                    ),
                )
                try:
                    if self._download_store is None:
                        self._download_store = DownloadArtifactStore(
                            self.trusted_download_config,
                            self.browser_config.download_policy,
                            self.browser_session_id,
                        )
                        recovery_report = self._download_store.recover_abandoned_sessions(
                            deadline=deadline
                        )
                    else:
                        recovery_report = {"removed": [], "skipped": [], "failed": []}
                    store = self._download_store
                except PermissionError as exc:
                    return ActionDispatchResult(
                        ok=False, error=str(exc), started_at_ms=started,
                        completed_at_ms=monotonic_ms(), resolution_trace=resolved.trace,
                        failure_kind=DownloadFailureReason.PERMISSION_DENIED.value,
                        action_evidence={"download": {"state": DownloadLifecycleState.BLOCKED_BY_POLICY.value, "terminal": True, "failure_reason": DownloadFailureReason.PERMISSION_DENIED.value, "artifact": None}},
                    )
                except OSError as exc:
                    reason = DownloadFailureReason.STORAGE_EXHAUSTED if getattr(exc, "errno", None) == 28 else DownloadFailureReason.DESTINATION_REJECTED
                    return ActionDispatchResult(
                        ok=False, error=str(exc), started_at_ms=started,
                        completed_at_ms=monotonic_ms(), resolution_trace=resolved.trace,
                        failure_kind=reason.value,
                        action_evidence={"download": {"state": DownloadLifecycleState.BLOCKED_BY_POLICY.value, "terminal": True, "failure_reason": reason.value, "artifact": None}},
                    )
                # Resolve all host-controlled destination components before
                # any event listener is armed or trigger can execute.
                try:
                    store.resolver.subdirectory(request.destination_subdirectory)
                    if request.preferred_filename is not None:
                        store.resolver.filename(request.preferred_filename)
                except DownloadSecurityError as exc:
                    return ActionDispatchResult(
                        ok=False,
                        error=str(exc),
                        started_at_ms=started,
                        completed_at_ms=monotonic_ms(),
                        resolution_trace=resolved.trace,
                        failure_kind=exc.reason.value,
                        action_evidence={
                            "download": {
                                "state": DownloadLifecycleState.BLOCKED_BY_POLICY.value,
                                "terminal": True,
                                "failure_reason": exc.reason.value,
                                "artifact": None,
                                "lifecycle": [
                                    {"state": DownloadLifecycleState.PENDING.value, "at_ms": started},
                                    {"state": DownloadLifecycleState.BLOCKED_BY_POLICY.value, "at_ms": monotonic_ms()},
                                ],
                            }
                        },
                    )
                coordinator = DownloadCoordinator(store)
                expected_page_id = str(self.page_id)
                monitor = DownloadEventMonitor(expected_page_id)
                events: list[tuple[Page, Any]] = []
                attached: list[Page] = []
                download_callbacks: dict[int, Any] = {}
                pages_before = {
                    item["page_id"]: item for item in self.list_pages()
                    if item["lifecycle_state"] == PageLifecycleState.OPEN.value
                }
                url_before = self.page.url

                def on_download(download: Any, source: Page) -> None:
                    page_id = self._page_ids_by_object.get(id(source), "")
                    entry = self._pages.get(page_id)
                    correlated_page_id = (
                        expected_page_id
                        if page_id == expected_page_id
                        or (
                            entry is not None
                            and entry.triggering_operation_id == operation.operation_id
                        )
                        else page_id
                    )
                    monitor.record(
                        page_id=correlated_page_id,
                        suggested_filename=getattr(download, "suggested_filename", None),
                    )
                    events.append((source, download))

                def attach(page: Page) -> None:
                    if page in attached:
                        return
                    attached.append(page)
                    callback = lambda download, p=page: on_download(download, p)
                    download_callbacks[id(page)] = callback
                    page.on("download", callback)

                def on_new_page(page: Page) -> None:
                    attach(page)

                for existing_page in self._context.pages:
                    attach(existing_page)
                self._context.on("page", on_new_page)
                lifecycle = [{"state": DownloadLifecycleState.PENDING.value, "at_ms": started}]
                trigger_started = False
                trigger_completed = False
                timeout_phase: str | None = None
                cancellation_diagnostics: list[dict[str, Any]] = []

                def bounded(coro: Any, phase: str) -> Any:
                    remaining = deadline.remaining_ms(phase)
                    try:
                        return coro._sync(  # sync Playwright object owns this loop
                            asyncio.wait_for(coro._impl_obj, remaining / 1000)
                        )
                    except AttributeError:
                        raise RuntimeError("invalid bounded Playwright operation")

                def bounded_download(download: Any, method: str, phase: str, *args: Any) -> Any:
                    remaining = deadline.remaining_ms(phase)
                    impl_method = getattr(download._impl_obj, method)
                    return download._sync(
                        asyncio.wait_for(impl_method(*args), remaining / 1000)
                    )

                def cancel_download(download: Any, phase: str) -> None:
                    try:
                        remaining = max(
                            1, min(250, deadline.absolute_ms - monotonic_ms())
                        )
                        download._sync(
                            asyncio.wait_for(
                                download._impl_obj.cancel(), remaining / 1000
                            )
                        )
                        cancellation_diagnostics.append(
                            {"confirmed": True, "phase": phase}
                        )
                    except Exception as exc:
                        cancellation_diagnostics.append(
                            {
                                "confirmed": False,
                                "phase": phase,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )

                self._triggering_operation_id = operation.operation_id
                self._triggering_opener_page_id = self.page_id
                try:
                    lifecycle.append({"state": DownloadLifecycleState.WAITING_FOR_EVENT.value, "at_ms": monotonic_ms()})
                    trigger_started = True
                    try:
                        trigger_timeout = deadline.remaining_ms("trigger")
                        if request.trigger_action == DownloadTriggerAction.CLICK:
                            loc.click(timeout=trigger_timeout)
                        else:
                            assert request.trigger_key is not None
                            loc.press(request.trigger_key, timeout=trigger_timeout)
                        trigger_completed = True
                    except (PlaywrightTimeoutError, PlaywrightError) as exc:
                        return ActionDispatchResult(
                            ok=False,
                            error=str(exc),
                            started_at_ms=started,
                            completed_at_ms=monotonic_ms(),
                            resolution_trace=resolved.trace,
                            failure_kind=DownloadFailureReason.TRIGGER_FAILED.value,
                            action_evidence={
                                "download": {
                                    "state": DownloadLifecycleState.FAILED.value,
                                    "terminal": True,
                                    "failure_reason": DownloadFailureReason.TRIGGER_FAILED.value,
                                    "artifact": None,
                                    "trigger_started": trigger_started,
                                    "trigger_completed": False,
                                    "phase": "trigger",
                                    "lifecycle": lifecycle,
                                }
                            },
                        )
                    event_boundary = max(
                        monotonic_ms(),
                        deadline.absolute_ms - request.late_event_guard_ms,
                    )
                    while not events and monotonic_ms() < event_boundary:
                        self.page.wait_for_timeout(25)
                    if not events:
                        # The remaining fixed-deadline budget is a terminal late
                        # guard. Any attributable event is cancelled before the
                        # operation returns and before another operation starts.
                        while monotonic_ms() < deadline.absolute_ms:
                            self.page.wait_for_timeout(
                                min(25, max(1, deadline.absolute_ms - monotonic_ms()))
                            )
                            while events:
                                _, late = events.pop(0)
                                cancel_download(late, "late_event_cancellation")
                        raise DownloadTimeoutError("event_wait")
                    correlation_end = min(
                        deadline.absolute_ms,
                        monotonic_ms() + request.correlation_window_ms,
                    )
                    while monotonic_ms() < correlation_end:
                        self.page.wait_for_timeout(
                            min(25, max(1, correlation_end - monotonic_ms()))
                        )
                    if len(events) > request.expected_download_events:
                        for _, extra in events:
                            cancel_download(extra, "multiple_event_cancellation")
                    monitor.validate()
                    source_page, download = events[0]
                    lifecycle.append({"state": DownloadLifecycleState.STARTED.value, "at_ms": monotonic_ms()})
                    browser_failure = bounded_download(
                        download, "failure", "transfer_completion"
                    )
                    lifecycle.append({"state": DownloadLifecycleState.SAVING.value, "at_ms": monotonic_ms()})
                    response_mime = next(
                        (
                            record.content_type
                            for record in reversed(self._network)
                            if record.url == getattr(download, "url", None)
                        ),
                        None,
                    )
                    artifact = coordinator.complete(
                        save_to=lambda path: bounded_download(
                            download, "save_as", "save_as", path
                        ),
                        browser_failure=browser_failure,
                        suggested_filename=download.suggested_filename,
                        request=request,
                        response_mime=response_mime,
                        deadline=deadline,
                        phase_callback=lambda _: lifecycle.append(
                            {
                                "state": DownloadLifecycleState.VERIFYING.value,
                                "at_ms": monotonic_ms(),
                            }
                        ),
                    )
                    lifecycle.append({"state": DownloadLifecycleState.COMPLETED.value, "at_ms": monotonic_ms()})
                    pages_after = {
                        item["page_id"]: item for item in self.list_pages()
                        if item["lifecycle_state"] == PageLifecycleState.OPEN.value
                    }
                    created_ids = sorted(set(pages_after) - set(pages_before))
                    created_entries = [
                        entry for entry in self._pages.values()
                        if entry.page_id not in pages_before
                        and entry.triggering_operation_id == operation.operation_id
                    ]
                    transient = [entry.page_id for entry in created_entries if entry.page.is_closed()]
                    persistent = [entry.page_id for entry in created_entries if not entry.page.is_closed()]
                    navigated = self.page.url != url_before
                    effects = {
                        "created_page_ids": created_ids,
                        "transient_page_ids": transient,
                        "persistent_page_ids": persistent,
                        "navigation_occurred": navigated,
                        "active_page_id_before": expected_page_id,
                        "active_page_id_after": self.page_id,
                    }
                    policy = request.page_effect_policy
                    policy_ok = (
                        policy == DownloadPageEffectPolicy.ANY_DECLARED_PAGE_EFFECT
                        or (policy == DownloadPageEffectPolicy.NO_NEW_PAGE and not created_entries)
                        or (policy == DownloadPageEffectPolicy.ALLOW_TRANSIENT_PAGE and not persistent)
                        or (policy == DownloadPageEffectPolicy.ALLOW_ONE_PERSISTENT_PAGE and len(persistent) <= 1)
                    )
                    result = {
                        "state": DownloadLifecycleState.COMPLETED.value,
                        "terminal": True,
                        "failure_reason": (
                            None if policy_ok else DownloadFailureReason.PAGE_POLICY_VIOLATION.value
                        ),
                        "artifact": artifact.to_dict(),
                        "lifecycle": lifecycle,
                        "page_effects": effects,
                        "page_policy_passed": policy_ok,
                        "request": request.describe(),
                        "trigger_started": trigger_started,
                        "trigger_completed": trigger_completed,
                        "phase": "completed",
                        "recovery": recovery_report,
                        "cancellation": cancellation_diagnostics,
                    }
                    return ActionDispatchResult(
                        ok=policy_ok,
                        error=None if policy_ok else "download completed but page-effect policy was violated",
                        started_at_ms=started,
                        completed_at_ms=monotonic_ms(),
                        recovery_attempts=recovery,
                        match_count=1,
                        resolution_trace=resolved.trace,
                        failure_kind=None if policy_ok else DownloadFailureReason.PAGE_POLICY_VIOLATION.value,
                        action_evidence={"download": result, **evidence},
                    )
                except (DownloadTimeoutError, asyncio.TimeoutError) as exc:
                    timeout_phase = (
                        exc.phase
                        if isinstance(exc, DownloadTimeoutError)
                        else "playwright_operation"
                    )
                    for _, captured in events:
                        cancel_download(captured, "timeout_cancellation")
                    cancellation_failed = any(
                        not item["confirmed"] for item in cancellation_diagnostics
                    )
                    reason = (
                        DownloadFailureReason.CANCEL_REQUEST_FAILED
                        if cancellation_failed
                        else DownloadFailureReason.DOWNLOAD_EVENT_NOT_RECEIVED
                        if timeout_phase == "event_wait"
                        else DownloadFailureReason.DOWNLOAD_TIMEOUT
                    )
                    return ActionDispatchResult(
                        ok=False, error=str(exc), started_at_ms=started,
                        completed_at_ms=monotonic_ms(), resolution_trace=resolved.trace,
                        failure_kind=reason.value,
                        action_evidence={"download": {
                            "state": DownloadLifecycleState.TIMED_OUT.value,
                            "terminal": True,
                            "failure_reason": reason.value,
                            "artifact": None,
                            "phase": timeout_phase,
                            "trigger_started": trigger_started,
                            "trigger_completed": trigger_completed,
                            "cancellation": cancellation_diagnostics,
                            "lifecycle": lifecycle + [{
                                "state": DownloadLifecycleState.TIMED_OUT.value,
                                "at_ms": monotonic_ms(),
                                "phase": timeout_phase,
                            }],
                        }},
                    )
                except PlaywrightTimeoutError as exc:
                    return ActionDispatchResult(
                        ok=False, error=str(exc), started_at_ms=started,
                        completed_at_ms=monotonic_ms(), resolution_trace=resolved.trace,
                        failure_kind=DownloadFailureReason.TRIGGER_FAILED.value,
                        action_evidence={"download": {
                            "state": DownloadLifecycleState.FAILED.value,
                            "terminal": True,
                            "failure_reason": DownloadFailureReason.TRIGGER_FAILED.value,
                            "artifact": None,
                            "phase": "trigger",
                            "trigger_started": trigger_started,
                            "trigger_completed": False,
                            "lifecycle": lifecycle,
                        }},
                    )
                except DownloadSecurityError as exc:
                    state = (
                        DownloadLifecycleState.TIMED_OUT
                        if exc.reason == DownloadFailureReason.DOWNLOAD_EVENT_NOT_RECEIVED
                        else DownloadLifecycleState.BLOCKED_BY_POLICY
                        if exc.reason in {
                            DownloadFailureReason.DESTINATION_REJECTED,
                            DownloadFailureReason.FILENAME_REJECTED,
                            DownloadFailureReason.PATH_ESCAPE_DETECTED,
                            DownloadFailureReason.COLLISION_REJECTED,
                            DownloadFailureReason.SIZE_LIMIT_EXCEEDED,
                            DownloadFailureReason.EXTENSION_NOT_ALLOWED,
                            DownloadFailureReason.MIME_TYPE_NOT_ALLOWED,
                        }
                        else DownloadLifecycleState.FAILED
                    )
                    lifecycle.append({"state": state.value, "at_ms": monotonic_ms()})
                    return ActionDispatchResult(
                        ok=False, error=str(exc), started_at_ms=started,
                        completed_at_ms=monotonic_ms(), resolution_trace=resolved.trace,
                        failure_kind=exc.reason.value,
                        action_evidence={"download": {"state": state.value, "terminal": True, "failure_reason": exc.reason.value, "artifact": None, "lifecycle": lifecycle}},
                    )
                except Exception as exc:
                    return ActionDispatchResult(
                        ok=False, error=f"{type(exc).__name__}: {exc}", started_at_ms=started,
                        completed_at_ms=monotonic_ms(), resolution_trace=resolved.trace,
                        failure_kind=DownloadFailureReason.INTERNAL_ERROR.value,
                        action_evidence={"download": {"state": DownloadLifecycleState.FAILED.value, "terminal": True, "failure_reason": DownloadFailureReason.INTERNAL_ERROR.value, "artifact": None, "lifecycle": lifecycle}},
                    )
                finally:
                    self._triggering_operation_id = None
                    self._triggering_opener_page_id = None
                    try:
                        self._context.remove_listener("page", on_new_page)
                    except Exception:
                        pass
                    for attached_page in attached:
                        try:
                            attached_page.remove_listener(
                                "download", download_callbacks[id(attached_page)]
                            )
                        except Exception:
                            pass

            if action.type == ActionType.UPLOAD_FILE:
                from dingdongditch.contract.upload import accept_allows

                authorization = action.upload_authorization
                assert authorization is not None
                resolved_files = authorization.validate_and_resolve()
                safe = authorization.safe_evidence(resolved_files)
                expected_names = [path.name for path in resolved_files]
                upload_token = str(uuid.uuid4())
                pre_upload = self._upload_snapshot(loc, upload_token)
                pre_visible_text = pre_upload.pop("visible_text", "")
                pre_upload["existing_requested_filename_hits"] = [
                    name for name in expected_names if name in pre_visible_text
                ]
                pre_upload["visible_text_length"] = len(pre_visible_text)
                control = pre_upload["target"]
                upload_evidence = {
                    **safe,
                    "target_kind": control,
                    "pre_upload_evidence": pre_upload,
                    "dispatch_result": "not_attempted",
                    "execution_result": "not_dispatched",
                    "verification_result": "not_verified",
                    "dispatched": False,
                }
                if control.get("tag") != "input" or control.get("type") != "file":
                    return ActionDispatchResult(
                        ok=False, error="upload target is not an HTML input[type=file] element",
                        started_at_ms=started, completed_at_ms=monotonic_ms(),
                        match_count=1, resolution_trace=resolved.trace,
                        failure_kind="upload_target_not_file_input",
                        action_evidence={"upload": upload_evidence},
                    )
                if len(resolved_files) > 1 and not control.get("multiple"):
                    return ActionDispatchResult(
                        ok=False, error="multiple files requested but the upload target does not allow multiple files",
                        started_at_ms=started, completed_at_ms=monotonic_ms(),
                        match_count=1, resolution_trace=resolved.trace,
                        failure_kind="upload_multiple_not_allowed",
                        action_evidence={"upload": upload_evidence},
                    )
                rejected = [path.name for path in resolved_files if not accept_allows(path, control.get("accept"))]
                if rejected:
                    upload_evidence["accept_rejected_file_names"] = rejected
                    return ActionDispatchResult(
                        ok=False, error="one or more files do not match the target accept restriction",
                        started_at_ms=started, completed_at_ms=monotonic_ms(),
                        match_count=1, resolution_trace=resolved.trace,
                        failure_kind="upload_accept_mismatch",
                        action_evidence={"upload": upload_evidence},
                    )
                dispatch_error = None
                try:
                    loc.set_input_files([str(path) for path in resolved_files], timeout=effective_timeout_ms)
                    upload_evidence["dispatch_result"] = "succeeded"
                except PlaywrightError as exc:
                    dispatch_error = type(exc).__name__
                    upload_evidence["dispatch_result"] = "error"
                try:
                    post_upload = self._upload_post_snapshot(upload_token, expected_names)
                except PlaywrightError:
                    post_upload = {
                        "scope_retained": False, "replacement_input_count": 0,
                        "file_lists": [], "visible_filename_hits": [],
                        "attachment_controls": [], "post_state_unavailable": True,
                    }
                exact_file_list = any(names == expected_names for names in post_upload.get("file_lists", []))
                fresh_hits = [name for name in post_upload.get("visible_filename_hits", []) if name not in pre_visible_text]
                filename_confirmation = sorted(fresh_hits) == sorted(expected_names)
                attachment_confirmation = bool(filename_confirmation and post_upload.get("attachment_controls"))
                verified = bool(exact_file_list or filename_confirmation or attachment_confirmation)
                original_disappeared = not post_upload.get("scope_retained")
                upload_evidence.update({
                    "post_upload_evidence": post_upload,
                    "observed_file_names": expected_names if verified else [],
                    "observed_file_count": len(expected_names) if verified else 0,
                    "verification_signals": {
                        "file_list_match": exact_file_list,
                        "fresh_visible_filename": filename_confirmation,
                        "attachment_control": attachment_confirmation,
                        "original_input_disappeared": original_disappeared,
                    },
                })
                if dispatch_error is not None and not verified:
                    upload_evidence.update({"dispatched": False, "execution_result": "dispatch_failed", "verification_result": "fail", "dispatch_error_kind": dispatch_error})
                    return ActionDispatchResult(
                        ok=False, error="file upload dispatch failed without confirming post-state",
                        started_at_ms=started, completed_at_ms=monotonic_ms(),
                        match_count=1, resolution_trace=resolved.trace,
                        failure_kind="upload_dispatch_failed",
                        action_evidence={"upload": upload_evidence},
                    )
                upload_evidence["dispatched"] = True
                if verified:
                    upload_evidence.update({
                        "dispatch_result": "succeeded" if dispatch_error is None else "succeeded_inferred_from_post_state",
                        "execution_result": "verified", "verification_result": "pass",
                    })
                else:
                    indeterminate = bool(original_disappeared or post_upload.get("post_state_unavailable"))
                    upload_evidence.update({
                        "execution_result": "indeterminate" if indeterminate else "dispatch_succeeded_verification_failed",
                        "verification_result": "indeterminate" if indeterminate else "fail",
                    })
                    return ActionDispatchResult(
                        ok=False, error="upload dispatch succeeded but durable verification did not confirm attachment",
                        started_at_ms=started, completed_at_ms=monotonic_ms(), match_count=1,
                        resolution_trace=resolved.trace,
                        failure_kind="upload_verification_indeterminate" if indeterminate else "upload_verification_failed",
                        action_evidence={"upload": upload_evidence},
                    )
                evidence.update({"upload": upload_evidence, "dispatched": True})

            elif action.type == ActionType.CLICK:
                transition = operation.page_transition or PageTransition()
                page_ids_before = {
                    item["page_id"]
                    for item in self.list_pages()
                    if item["lifecycle_state"] == PageLifecycleState.OPEN.value
                }
                opener_id = self.page_id
                transition_timeout_ms = min(
                    transition.timeout_ms, effective_timeout_ms
                )
                self._triggering_operation_id = operation.operation_id
                self._triggering_opener_page_id = opener_id
                popup_event_fired = False
                try:
                    expects_new = transition.policy in {
                        PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH,
                        PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT,
                    }
                    if expects_new:
                        assert self._context is not None
                        try:
                            with self._context.expect_page(
                                timeout=transition_timeout_ms
                            ):
                                loc.click(timeout=effective_timeout_ms)
                            popup_event_fired = True
                        except PlaywrightTimeoutError:
                            completed = monotonic_ms()
                            deadline_expired = (
                                plan_timing is not None
                                and plan_timing.plan_deadline_ms is not None
                                and completed >= plan_timing.plan_deadline_ms
                            )
                            return ActionDispatchResult(
                                ok=False,
                                error=(
                                    "plan deadline expired while waiting for new page"
                                    if deadline_expired
                                    else "expected new page did not open"
                                ),
                                started_at_ms=started,
                                completed_at_ms=completed,
                                resolution_trace=resolved.trace,
                                failure_kind=(
                                    "plan_deadline_expired"
                                    if deadline_expired
                                    else "expected_new_page_not_opened"
                                ),
                                action_evidence={
                                    **evidence,
                                    "page_count_before": len(page_ids_before),
                                    "page_count_after": len(self.list_pages()),
                                    "opener_page_id": opener_id,
                                    "created_page_ids": [],
                                    "selected_active_page_id": self.page_id,
                                    "popup_event_fired": False,
                                    "switching_occurred": False,
                                    "unexpected_page_classification": None,
                                    "page_transition": transition.describe(),
                                    "page_registry": self.list_pages(),
                                },
                            )
                        except Exception:
                            # A popup may close before Playwright can return it.
                            # The context event registry remains authoritative.
                            if not any(
                                entry.triggering_operation_id == operation.operation_id
                                for entry in self._pages.values()
                            ):
                                raise
                            popup_event_fired = True
                    else:
                        assert self._context is not None
                        try:
                            with self._context.expect_page(
                                timeout=transition_timeout_ms
                            ):
                                loc.click(timeout=effective_timeout_ms)
                            popup_event_fired = True
                        except PlaywrightTimeoutError:
                            # SAME_PAGE and ALLOW_SAME_OR_NEW_PAGE both permit
                            # the deterministic observation window to end with
                            # no page creation.
                            pass
                    assert self._context is not None
                    for observed_page in self._context.pages:
                        if id(observed_page) not in self._page_ids_by_object:
                            self._register_page(
                                observed_page,
                                opener_page_id=opener_id,
                                triggering_operation_id=operation.operation_id,
                            )
                finally:
                    self._triggering_operation_id = None
                    self._triggering_opener_page_id = None

                created = [
                    entry
                    for entry in self._pages.values()
                    if entry.page_id not in page_ids_before
                    and entry.triggering_operation_id == operation.operation_id
                ]
                created_ids = [entry.page_id for entry in created]
                popup_event_fired = popup_event_fired or bool(created)
                evidence.update(
                    {
                        "page_count_before": len(page_ids_before),
                        "page_count_after": len(
                            [
                                item
                                for item in self.list_pages()
                                if item["lifecycle_state"]
                                == PageLifecycleState.OPEN.value
                            ]
                        ),
                        "opener_page_id": opener_id,
                        "created_page_ids": created_ids,
                        "popup_event_fired": popup_event_fired,
                        "page_transition": transition.describe(),
                        "unexpected_page_classification": None,
                    }
                )
                if transition.policy == PageTransitionPolicy.SAME_PAGE and created:
                    evidence["unexpected_page_classification"] = "unexpected_new_page"
                    evidence["selected_active_page_id"] = self.page_id
                    evidence["switching_occurred"] = False
                    evidence["page_registry"] = self.list_pages()
                    return ActionDispatchResult(
                        ok=False,
                        error="unexpected popup or new page opened",
                        started_at_ms=started,
                        completed_at_ms=monotonic_ms(),
                        resolution_trace=resolved.trace,
                        failure_kind="unexpected_new_page",
                        action_evidence=evidence,
                    )
                expects_exactly_one = transition.policy in {
                    PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH,
                    PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT,
                }
                if expects_exactly_one and len(created) != 1:
                    evidence["unexpected_page_classification"] = (
                        "multiple_new_pages" if len(created) > 1 else "missing_new_page"
                    )
                    evidence["selected_active_page_id"] = self.page_id
                    evidence["switching_occurred"] = False
                    evidence["page_registry"] = self.list_pages()
                    return ActionDispatchResult(
                        ok=False,
                        error=f"expected exactly one new page; observed {len(created)}",
                        started_at_ms=started,
                        completed_at_ms=monotonic_ms(),
                        resolution_trace=resolved.trace,
                        failure_kind=(
                            "multiple_new_pages_opened"
                            if len(created) > 1
                            else "expected_new_page_not_opened"
                        ),
                        action_evidence=evidence,
                    )
                new_page_results: list[dict[str, Any]] = []
                if created:
                    entry = created[0]
                    try:
                        new_page_closed = entry.page.is_closed()
                    except PlaywrightError:
                        new_page_closed = True
                    if new_page_closed:
                        evidence["page_registry"] = self.list_pages()
                        return ActionDispatchResult(
                            ok=False,
                            error="new page closed before verification",
                            started_at_ms=started,
                            completed_at_ms=monotonic_ms(),
                            resolution_trace=resolved.trace,
                            failure_kind="new_page_closed_before_verification",
                            action_evidence=evidence,
                        )
                    try:
                        new_page_results = self._verify_new_page(
                            entry.page,
                            transition.new_page_expectations,
                            timeout_ms=transition_timeout_ms,
                        )
                    except RuntimeError as exc:
                        evidence["page_registry"] = self.list_pages()
                        return ActionDispatchResult(
                            ok=False,
                            error=str(exc),
                            started_at_ms=started,
                            completed_at_ms=monotonic_ms(),
                            resolution_trace=resolved.trace,
                            failure_kind="new_page_closed_before_verification",
                            action_evidence=evidence,
                        )
                    evidence["new_page_verification_results"] = new_page_results
                    if any(not result["passed"] for result in new_page_results):
                        evidence["page_registry"] = self.list_pages()
                        return ActionDispatchResult(
                            ok=False,
                            error="new-page expectation failed",
                            started_at_ms=started,
                            completed_at_ms=monotonic_ms(),
                            resolution_trace=resolved.trace,
                            failure_kind="new_page_verification_failed",
                            action_evidence=evidence,
                        )
                    should_switch = (
                        transition.policy
                        == PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH
                        or (
                            transition.policy
                            == PageTransitionPolicy.ALLOW_SAME_OR_NEW_PAGE
                            and transition.activate_new_page_when_allowed
                        )
                    )
                    if should_switch:
                        self._activate_page(entry.page_id)
                evidence["selected_active_page_id"] = self.page_id
                evidence["switching_occurred"] = opener_id != self.page_id
                evidence["page_registry"] = self.list_pages()
            elif action.type == ActionType.FILL:
                if action.secret_reference is not None:
                    secret_receipt = self.authentication.inject(
                        loc,
                        action.secret_reference,
                        timeout_ms=action.secret_timeout_ms,
                    )
                    # Deliberately neutral key: generic evidence sanitizers
                    # redact values beneath keys containing "secret".
                    evidence["ephemeral_fill"] = secret_receipt.to_dict()
                else:
                    assert action.text is not None
                    loc.fill(action.text, timeout=effective_timeout_ms)
            elif action.type == ActionType.PRESS_KEY:
                assert action.key is not None
                loc.press(action.key, timeout=effective_timeout_ms)
                evidence.update(
                    {
                        "key": action.key,
                        "dispatch_scope": "target",
                        "target_resolved": True,
                    }
                )
            elif action.type == ActionType.SELECT_OPTION:
                kind = self._control_kind(loc)
                if kind.get("tag") != "select":
                    completed = monotonic_ms()
                    evidence.update(
                        {
                            "dispatched": False,
                            "control_kind": kind,
                            "failure_kind": "target_not_select",
                        }
                    )
                    return ActionDispatchResult(
                        ok=False,
                        error="target is not an HTML select element",
                        started_at_ms=started,
                        completed_at_ms=completed,
                        recovery_attempts=recovery,
                        match_count=1,
                        resolution_trace=resolved.trace,
                        failure_kind="target_not_select",
                        action_evidence=evidence,
                    )
                try:
                    is_multiple = bool(
                        loc.evaluate(
                            "(el) => !!(el instanceof HTMLSelectElement && el.multiple)"
                        )
                    )
                except Exception:
                    is_multiple = False
                evidence["select_multiple"] = is_multiple
                mode = action.select_mode()
                if mode == SelectMode.VALUES:
                    assert action.option_values is not None
                    if not is_multiple:
                        completed = monotonic_ms()
                        evidence.update(
                            {
                                "dispatched": False,
                                "failure_kind": "target_not_multi_select",
                            }
                        )
                        return ActionDispatchResult(
                            ok=False,
                            error="option_values requires a multiple select element",
                            started_at_ms=started,
                            completed_at_ms=completed,
                            recovery_attempts=recovery,
                            match_count=1,
                            resolution_trace=resolved.trace,
                            failure_kind="target_not_multi_select",
                            action_evidence=evidence,
                        )
                    values = list(action.option_values)
                    loc.select_option(value=values, timeout=effective_timeout_ms)
                    evidence["select_mode"] = "values"
                    evidence["requested"] = values
                elif mode == SelectMode.VALUE:
                    assert action.option_value is not None
                    loc.select_option(
                        value=action.option_value, timeout=effective_timeout_ms
                    )
                    evidence["select_mode"] = "value"
                    evidence["requested"] = action.option_value
                else:
                    assert action.option_label is not None
                    loc.select_option(
                        label=action.option_label, timeout=effective_timeout_ms
                    )
                    evidence["select_mode"] = "label"
                    evidence["requested"] = action.option_label
                try:
                    evidence["selected_value"] = loc.input_value()
                except PlaywrightError:
                    evidence["selected_value"] = None
                try:
                    evidence["selected_values"] = loc.evaluate(
                        """(el) => Array.from(el.selectedOptions || []).map(
                          (o) => o.value
                        )"""
                    )
                except Exception:
                    evidence["selected_values"] = None
                try:
                    evidence["selected_label"] = loc.evaluate(
                        """(el) => {
                          const opt = el.options[el.selectedIndex];
                          return opt ? opt.textContent : null;
                        }"""
                    )
                except Exception:
                    evidence["selected_label"] = None
            elif action.type == ActionType.SET_CHECKED:
                assert action.checked is not None
                kind = self._control_kind(loc)
                try:
                    input_type = loc.evaluate(
                        """(el) => {
                          if (!(el instanceof HTMLInputElement)) return null;
                          return el.type;
                        }"""
                    )
                except Exception:
                    input_type = None
                is_radio = input_type == "radio"
                is_checkbox = input_type == "checkbox"
                if not is_checkbox and not is_radio:
                    completed = monotonic_ms()
                    evidence.update(
                        {
                            "dispatched": False,
                            "control_kind": kind,
                            "failure_kind": "target_not_checkable",
                        }
                    )
                    return ActionDispatchResult(
                        ok=False,
                        error="target is not a checkbox or radio control",
                        started_at_ms=started,
                        completed_at_ms=completed,
                        recovery_attempts=recovery,
                        match_count=1,
                        resolution_trace=resolved.trace,
                        failure_kind="target_not_checkable",
                        action_evidence=evidence,
                    )
                if is_radio and action.checked is False:
                    completed = monotonic_ms()
                    evidence.update(
                        {
                            "dispatched": False,
                            "control_kind": kind,
                            "requested_checked": False,
                            "failure_kind": "unsupported_radio_uncheck",
                        }
                    )
                    return ActionDispatchResult(
                        ok=False,
                        error=(
                            "set_checked(checked=false) is not supported for radio "
                            "controls; declare a different radio option with "
                            "checked=true instead"
                        ),
                        started_at_ms=started,
                        completed_at_ms=completed,
                        recovery_attempts=recovery,
                        match_count=1,
                        resolution_trace=resolved.trace,
                        failure_kind="unsupported_radio_uncheck",
                        action_evidence=evidence,
                    )
                before = bool(loc.is_checked())
                evidence["checked_before"] = before
                evidence["requested_checked"] = action.checked
                evidence["control_kind"] = {**kind, "input_type": input_type}
                if before == action.checked:
                    evidence["dispatched"] = False
                    evidence["already_satisfied"] = True
                else:
                    loc.set_checked(action.checked, timeout=effective_timeout_ms)
                    evidence["dispatched"] = True
                    evidence["already_satisfied"] = False
                evidence["checked_after"] = bool(loc.is_checked())
            elif action.type == ActionType.HOVER:
                loc.hover(timeout=effective_timeout_ms)
            elif action.type == ActionType.SCROLL_TO_TARGET:
                before_vp = self._element_in_viewport(loc)
                evidence["in_viewport_before"] = before_vp
                if before_vp is True:
                    evidence["dispatched"] = False
                    evidence["already_satisfied"] = True
                else:
                    loc.scroll_into_view_if_needed(timeout=effective_timeout_ms)
                    evidence["dispatched"] = True
                    evidence["already_satisfied"] = False
                evidence["in_viewport_after"] = self._element_in_viewport(loc)
            elif action.type == ActionType.POINTER_MOVE:
                assert action.pointer_request is not None
                request = action.pointer_request
                scrolled = False
                try:
                    loc.scroll_into_view_if_needed(timeout=effective_timeout_ms)
                    scrolled = True
                except PlaywrightError:
                    pass
                box = loc.bounding_box(timeout=effective_timeout_ms)
                if box is None:
                    return ActionDispatchResult(
                        ok=False,
                        error="pointer target has no visible bounding box",
                        started_at_ms=started,
                        completed_at_ms=monotonic_ms(),
                        recovery_attempts=recovery,
                        match_count=1,
                        resolution_trace=resolved.trace,
                        failure_kind="pointer_target_not_visible",
                        action_evidence={
                            "type": action.type.value,
                            "dispatched": False,
                            "origin": request.origin.value,
                            "target_resolved": True,
                            "bounding_box": None,
                        },
                    )
                if request.origin == PointerOrigin.ELEMENT_CENTER:
                    x = float(box["x"]) + float(box["width"]) / 2
                    y = float(box["y"]) + float(box["height"]) / 2
                else:
                    assert request.x is not None and request.y is not None
                    x = float(box["x"]) + float(request.x)
                    y = float(box["y"]) + float(request.y)
                return self._dispatch_pointer_move(
                    operation,
                    collector=collector,
                    started=started,
                    x=x,
                    y=y,
                    target_resolution=resolved.trace,
                    match_count=1,
                    origin=request.origin,
                    bounding_box={key: float(value) for key, value in box.items()},
                    scrolled_into_view=scrolled,
                    recovery=recovery,
                )
            else:
                raise ValueError(f"unsupported action: {action.type}")

            completed = monotonic_ms()
            collector.add(
                kind=SignalKind.ACTION_RESULT,
                collected_at_ms=completed,
                payload={
                    "ok": True,
                    "action": action.type.value,
                    "match_count": 1,
                    "locator": action.locator.describe(),
                    "target_resolution": resolved.trace.to_dict(),
                    "action_evidence": evidence,
                },
            )
            return ActionDispatchResult(
                ok=True,
                error=None,
                started_at_ms=started,
                completed_at_ms=completed,
                recovery_attempts=recovery,
                match_count=1,
                resolution_trace=resolved.trace,
                action_evidence=evidence,
            )
        except AuthenticationError as exc:
            completed = monotonic_ms()
            collector.add(
                kind=SignalKind.ACTION_RESULT,
                collected_at_ms=completed,
                payload={"ok": False, "failure_kind": exc.kind.value},
                notes="secret provider or authentication boundary failed",
            )
            return ActionDispatchResult(
                ok=False,
                error="authentication boundary failed",
                started_at_ms=started,
                completed_at_ms=completed,
                recovery_attempts=recovery,
                resolution_trace=last_trace,
                failure_kind=exc.kind.value,
                action_evidence={
                    **evidence,
                    "authentication_failure": {"failure_kind": exc.kind.value},
                },
            )
        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            completed = monotonic_ms()
            msg = str(exc)
            failure_kind = "action_dispatch_failed"
            lower = msg.lower()
            if "option" in lower and "select" in lower:
                failure_kind = "option_not_found"
            collector.add(
                kind=SignalKind.ACTION_RESULT,
                collected_at_ms=completed,
                payload={"ok": False, "error": msg, "failure_kind": failure_kind},
                notes="playwright exception",
            )
            return ActionDispatchResult(
                ok=False,
                error=msg,
                started_at_ms=started,
                completed_at_ms=completed,
                recovery_attempts=recovery,
                resolution_trace=last_trace,
                failure_kind=failure_kind,
            )

    def _atomic_element_snapshot(
        self,
        handle: Any,
        *,
        target_resolution: dict[str, Any],
        attribute_names: tuple[str, ...] = (),
    ) -> ElementStateSnapshot:
        names = tuple(dict.fromkeys((*LEGACY_ATTRIBUTE_NAMES, *attribute_names)))[:24]
        raw = handle.evaluate(
            ATOMIC_ELEMENT_SNAPSHOT_JS,
            list(names),
        )
        if not isinstance(raw, dict) or raw.get("supported") is not True:
            reason = (
                raw.get("error", "atomic snapshot returned an invalid result")
                if isinstance(raw, dict)
                else "atomic snapshot returned a non-object result"
            )
            raise AtomicSnapshotUnsupported(str(reason))
        if raw.get("connected") is not True:
            self._atomic_snapshot_count += 1
            return ElementStateSnapshot(
                availability=SnapshotAvailability.UNAVAILABLE,
                match_count=1,
                exists=True,
                visible=None,
                enabled=None,
                in_viewport=None,
                checked=None,
                selected=None,
                focused=None,
                text=None,
                value=None,
                role=None,
                bounding_box=None,
                attributes={},
                target_resolution=target_resolution,
                collection_mode="atomic",
                error="element detached during atomic snapshot",
            )
        self._atomic_snapshot_count += 1
        box = raw.get("bounding_box")
        return ElementStateSnapshot(
            availability=SnapshotAvailability.AVAILABLE,
            match_count=1,
            exists=True,
            visible=bool(raw["visible"]),
            enabled=bool(raw["enabled"]),
            in_viewport=bool(raw["in_viewport"]),
            checked=raw.get("checked"),
            selected=raw.get("selected"),
            focused=raw.get("focused"),
            text=str(raw.get("text") or ""),
            value=raw.get("value"),
            tag=raw.get("tag"),
            role=raw.get("role"),
            ancestor_tags=tuple(str(item) for item in raw.get("ancestor_tags") or ()),
            child_element_count=(
                int(raw["child_element_count"])
                if isinstance(raw.get("child_element_count"), int)
                else None
            ),
            bounding_box=(
                {key: float(value) for key, value in box.items()}
                if isinstance(box, dict)
                else None
            ),
            attributes={
                name: value
                for name, value in dict(raw.get("attributes") or {}).items()
            },
            file_names=tuple(str(item) for item in raw.get("file_names") or ()),
            file_count=int(raw.get("file_count", 0)),
            target_resolution=target_resolution,
            collection_mode="atomic",
        )

    def _serial_element_snapshot(
        self,
        handle: Any,
        *,
        target_resolution: dict[str, Any],
        fallback_error: str,
        attribute_names: tuple[str, ...] = (),
    ) -> ElementStateSnapshot:
        """Compatibility fallback used only for explicit unsupported results."""
        visible = handle.is_visible()
        enabled = handle.is_enabled()
        text = handle.inner_text() if visible else handle.text_content() or ""
        attrs: dict[str, str | None] = {}
        for name in tuple(dict.fromkeys((*LEGACY_ATTRIBUTE_NAMES, *attribute_names)))[:24]:
            try:
                attrs[name] = handle.get_attribute(name)
            except PlaywrightError:
                attrs[name] = None
        value: str | None = None
        try:
            value = handle.input_value()
            attrs["value"] = value
        except PlaywrightError:
            pass
        checked: bool | None = None
        try:
            checked = bool(handle.is_checked())
        except PlaywrightError:
            checked = None
        file_names: tuple[str, ...] = ()
        try:
            raw_file_names = handle.evaluate(
                "el => Array.from(el.files || [], f => String(f.name))"
            )
            if isinstance(raw_file_names, list):
                file_names = tuple(str(item) for item in raw_file_names)
        except PlaywrightError:
            pass
        self._atomic_snapshot_fallback_count += 1
        self._event("atomic_element_snapshot_fallback", error=fallback_error)
        return ElementStateSnapshot(
            availability=SnapshotAvailability.AVAILABLE,
            match_count=1,
            exists=True,
            visible=visible,
            enabled=enabled,
            in_viewport=self._element_in_viewport(handle),
            checked=checked,
            text=text or "",
            value=value,
            attributes=attrs,
            target_resolution=target_resolution,
            collection_mode="serial_fallback",
            error=fallback_error,
            file_names=file_names,
            file_count=len(file_names),
        )

    def capture_element_snapshot(
        self,
        locator: Locator,
        *,
        frame: Locator | None = None,
        frame_path: tuple[Locator, ...] = (),
        attribute_names: tuple[str, ...] = (),
    ) -> ElementStateSnapshot:
        """Resolve once and capture one atomic, boundary-local DOM snapshot."""
        resolved = self._resolve_scoped_target(
            locator,
            frame=frame,
            frame_path=frame_path,
            cardinality=CardinalityPolicy.EXACTLY_ONE,
        )
        trace = resolved.trace.to_dict()
        if resolved.match_count == 0:
            return ElementStateSnapshot(
                availability=SnapshotAvailability.MISSING,
                match_count=0,
                exists=False,
                target_resolution=trace,
            )
        if resolved.match_count > 1 or not resolved.ok or resolved.playwright_locator is None:
            return ElementStateSnapshot(
                availability=SnapshotAvailability.AMBIGUOUS,
                match_count=resolved.match_count,
                exists=True,
                ambiguous=True,
                target_resolution=trace,
            )
        handle = resolved.playwright_locator
        try:
            return self._atomic_element_snapshot(
                handle,
                target_resolution=trace,
                attribute_names=attribute_names,
            )
        except AtomicSnapshotUnsupported as exc:
            return self._serial_element_snapshot(
                handle,
                target_resolution=trace,
                fallback_error=str(exc),
                attribute_names=attribute_names,
            )

    def read_element_state(
        self,
        locator: Locator,
        *,
        frame: Locator | None = None,
        frame_path: tuple[Locator, ...] = (),
        attribute_names: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return self.capture_element_snapshot(
            locator,
            frame=frame,
            frame_path=frame_path,
            attribute_names=attribute_names,
        ).to_legacy_state()
