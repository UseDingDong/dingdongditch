from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from dingdongditch.runtime.file_lease import FileLease
from .callbacks import AuthEvent, AuthenticationCallbacks
from .errors import AuthenticationError, AuthenticationFailureKind
from .profiles import ProfileManager
from .secrets import (
    SecretBinding,
    SecretProvider,
    SecretReference,
    SecretResolutionReceipt,
    bind_secret,
    assert_secret_binding,
    resolve_bound_secret,
    resolve_secret,
)
from .portable_state import (
    DEFAULT_PORTABLE_STATE_MAX_AGE_MS,
    MAX_PORTABLE_STATE_BYTES,
    PORTABLE_STATE_SCHEMA_VERSION,
    PortableStatePolicy,
    PortableStateReceipt,
    build_portable_state,
    validate_portable_document,
)
from .webauthn import (
    WebAuthnParticipationReceipt,
    WebAuthnParticipationRequest,
    WebAuthnTransport,
    execute_webauthn_transport,
)

_SESSION_SCHEMA = 1


def validate_session_state(raw: object) -> dict[str, Any]:
    """Compatibility validation for legacy v1 cookie/localStorage documents.

    New exports use the portable-state v2 document below.  Existing callers
    retain their old import behavior, while new documents gain timestamps,
    feature declarations, and explicit IndexedDB boundaries.
    """
    if not isinstance(raw, dict) or raw.get("schema_version") != _SESSION_SCHEMA:
        raise AuthenticationError("session file has an unsupported or missing schema_version", kind=AuthenticationFailureKind.SESSION_INVALID, recovery="Export a new session with this DingDongDitch version.")
    state = raw.get("storage_state")
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
        raise AuthenticationError("session file must contain Playwright cookies and origins arrays", kind=AuthenticationFailureKind.SESSION_INVALID)
    for cookie in state["cookies"]:
        if not isinstance(cookie, dict) or not all(isinstance(cookie.get(key), str) for key in ("name", "value", "domain", "path")):
            raise AuthenticationError("session file contains an invalid cookie", kind=AuthenticationFailureKind.SESSION_INVALID)
    for origin in state["origins"]:
        if not isinstance(origin, dict) or not isinstance(origin.get("origin"), str) or not isinstance(origin.get("localStorage"), list):
            raise AuthenticationError("session file contains invalid origin storage", kind=AuthenticationFailureKind.SESSION_INVALID)
        from .portable_state import _safe_origin
        try:
            _safe_origin(origin["origin"])
        except AuthenticationError:
            raise AuthenticationError("session file contains an unsafe storage origin", kind=AuthenticationFailureKind.SESSION_INVALID)
        if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("value"), str) for item in origin["localStorage"]):
            raise AuthenticationError("session file contains invalid local storage entries", kind=AuthenticationFailureKind.SESSION_INVALID)
    return state


class AuthenticationCapability:
    """Sole owner of named profiles, session state, secrets and auth callbacks."""
    def __init__(
        self,
        *,
        profiles: ProfileManager | None = None,
        secrets: SecretProvider | None = None,
        callbacks: AuthenticationCallbacks | None = None,
        webauthn_transport: WebAuthnTransport | None = None,
    ) -> None:
        self.profiles = profiles or ProfileManager()
        self.secrets = secrets
        self.callbacks = callbacks or AuthenticationCallbacks()
        self.webauthn_transport = webauthn_transport
        self._lease: FileLease | None = None
        self._context: Any = None
        self._profile_name: str | None = None
        self._pending_portable_state: dict[str, Any] | None = None
        self._pending_portable_receipt: PortableStateReceipt | None = None

    def acquire_profile(self, name: str, *, engine: str = "chromium") -> Path:
        if self._lease is not None:
            raise AuthenticationError("authentication capability already owns a profile", kind=AuthenticationFailureKind.PROFILE_IN_USE)
        info = self.profiles.require(name)
        self._lease = self.profiles.acquire(name)
        self._profile_name = name
        if engine not in {"chromium", "firefox", "webkit"}:
            raise AuthenticationError(
                "requested browser engine has no persistent-profile mapping",
                kind=AuthenticationFailureKind.SESSION_UNSUPPORTED,
            )
        # Keep Chromium's established on-disk location intact.  Other engines
        # receive explicit subdirectories; their profile formats are not
        # interchangeable and are never silently shared.
        data_dir = info.path / "browser-data"
        if engine != "chromium":
            data_dir = data_dir / engine
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    def bind_context(self, context: Any) -> None:
        self._context = context

    def verify_ready(self, page: Any) -> None:
        try:
            if page is None or page.is_closed():
                raise RuntimeError("page is closed")
            page.evaluate("() => document.readyState")
        except Exception as exc:
            raise AuthenticationError("browser profile started but did not become ready", kind=AuthenticationFailureKind.NOT_READY, recovery="Retry the run; if it repeats, recreate the profile.") from exc

    def inject(
        self,
        locator: Any,
        secret_reference: SecretReference | str,
        *,
        timeout_ms: int = 5_000,
    ) -> SecretResolutionReceipt:
        """Resolve and fill one secret without retaining or reporting its value."""
        secret, receipt = resolve_secret(
            self.secrets, secret_reference, timeout_ms=timeout_ms
        )
        with secret:
            try:
                locator.fill(secret.reveal())
            except Exception as exc:
                raise AuthenticationError(
                    "secret injection browser operation failed",
                    kind=AuthenticationFailureKind.SESSION_IO_ERROR,
                    recovery="Check the target and retry.",
                ) from exc
        return receipt

    def bind_secret(self, secret_reference: SecretReference | str) -> SecretBinding:
        """Bind a provider generation for a pending two-phase operation."""
        return bind_secret(self.secrets, secret_reference)

    def assert_secret_binding(self, secret_reference: SecretReference | str, binding: SecretBinding) -> None:
        assert_secret_binding(self.secrets, secret_reference, binding)

    def inject_bound(
        self,
        locator: Any,
        secret_reference: SecretReference | str,
        binding: SecretBinding,
        *,
        timeout_ms: int = 5_000,
    ) -> SecretResolutionReceipt:
        secret, receipt = resolve_bound_secret(
            self.secrets, secret_reference, binding, timeout_ms=timeout_ms
        )
        with secret:
            try:
                locator.fill(secret.reveal())
            except Exception as exc:
                raise AuthenticationError(
                    "secret injection browser operation failed",
                    kind=AuthenticationFailureKind.SESSION_IO_ERROR,
                    recovery="Check the target and retry.",
                ) from exc
        return receipt

    def emit(self, event: AuthEvent) -> list[object]:
        return self.callbacks.emit(event)

    def participate_webauthn(
        self,
        request: WebAuthnParticipationRequest,
        *,
        browser_engine: str,
        page_origin: str | None,
    ) -> WebAuthnParticipationReceipt:
        return execute_webauthn_transport(
            self.webauthn_transport,
            request,
            browser_engine=browser_engine,
            page_origin=page_origin,
        )

    def export_session(
        self,
        destination: Path,
        *,
        policy: PortableStatePolicy | None = None,
    ) -> PortableStateReceipt:
        context = self._require_context()
        selected_policy = policy or PortableStatePolicy()
        try:
            selected_policy.validate()
            try:
                state = context.storage_state(indexed_db=selected_policy.include_indexed_db)
            except TypeError as exc:
                if selected_policy.include_indexed_db:
                    raise AuthenticationError(
                        "this Playwright backend cannot export IndexedDB state",
                        kind=AuthenticationFailureKind.SESSION_UNSUPPORTED,
                    ) from exc
                state = context.storage_state()
            document, receipt = build_portable_state(state, policy=selected_policy)
            self._atomic_json(destination.resolve(), document)
            return receipt
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("session export failed", kind=AuthenticationFailureKind.SESSION_IO_ERROR, recovery="Check the destination and retry.") from exc

    def import_session(
        self,
        source: Path,
        *,
        max_age_ms: int = DEFAULT_PORTABLE_STATE_MAX_AGE_MS,
    ) -> PortableStateReceipt:
        context = self._require_context()
        try:
            if source.stat().st_size > MAX_PORTABLE_STATE_BYTES:
                raise AuthenticationError("session file exceeds the 10 MiB safety limit", kind=AuthenticationFailureKind.SESSION_INVALID)
            raw = json.loads(source.read_text(encoding="utf-8"))
            if raw.get("schema_version") == _SESSION_SCHEMA and "kind" not in raw:
                # Legacy state remains readable for backward compatibility.
                state = validate_session_state(raw)
                receipt = PortableStateReceipt(
                    schema_version=_SESSION_SCHEMA,
                    direction="import",
                    status="completed_legacy",
                    included_features=("cookies", "local_storage"),
                    excluded_features=("indexed_db",),
                    cookie_count=len(state["cookies"]),
                    origin_count=len(state["origins"]),
                    limitations=("legacy_state_has_no_staleness_timestamp",),
                )
            else:
                # Existing contexts can safely import cookies/localStorage only.
                state, receipt = validate_portable_document(
                    raw, max_age_ms=max_age_ms, allow_indexed_db=False
                )
            context.clear_cookies()
            if state["cookies"]:
                context.add_cookies(state["cookies"])
            for origin in state["origins"]:
                page = context.new_page()
                try:
                    page.goto(origin["origin"], wait_until="domcontentloaded")
                    page.evaluate("items => { localStorage.clear(); for (const i of items) localStorage.setItem(i.name, i.value); }", origin["localStorage"])
                finally:
                    page.close()
            return receipt
        except AuthenticationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthenticationError("session file is unreadable or corrupt", kind=AuthenticationFailureKind.SESSION_INVALID, recovery="Use a valid exported session file.") from exc
        except Exception as exc:
            raise AuthenticationError("session import failed safely", kind=AuthenticationFailureKind.SESSION_IO_ERROR, recovery="Clear the profile session and retry.") from exc

    def prepare_session_import(
        self,
        source: Path,
        *,
        max_age_ms: int = DEFAULT_PORTABLE_STATE_MAX_AGE_MS,
    ) -> PortableStateReceipt:
        """Validate state for deterministic injection into a *new* context.

        This is the only path that supports Playwright's IndexedDB storage
        state.  The browser backend consumes it at new-context construction;
        a running context is never patched with IndexedDB JavaScript.
        """
        try:
            if source.stat().st_size > MAX_PORTABLE_STATE_BYTES:
                raise AuthenticationError("session file exceeds the 10 MiB safety limit", kind=AuthenticationFailureKind.SESSION_INVALID)
            raw = json.loads(source.read_text(encoding="utf-8"))
            state, receipt = validate_portable_document(
                raw, max_age_ms=max_age_ms, allow_indexed_db=True
            )
            self._pending_portable_state = state
            self._pending_portable_receipt = receipt
            return receipt
        except AuthenticationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthenticationError("session file is unreadable or corrupt", kind=AuthenticationFailureKind.SESSION_INVALID) from exc

    def pending_initial_storage_state(self) -> dict[str, Any] | None:
        """Backend-only read; values never enter plans or receipts."""
        return self._pending_portable_state

    def confirm_pending_initial_storage_state(self) -> None:
        self._pending_portable_state = None
        self._pending_portable_receipt = None

    def clear_session(self) -> None:
        context = self._require_context()
        try:
            context.clear_cookies()
            origins = [item["origin"] for item in context.storage_state().get("origins", [])]
            for origin in origins:
                page = context.new_page()
                try:
                    page.goto(origin, wait_until="domcontentloaded")
                    page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
                finally:
                    page.close()
            for page in list(context.pages):
                page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (_) {} }")
        except Exception as exc:
            raise AuthenticationError("session clear failed", kind=AuthenticationFailureKind.SESSION_IO_ERROR) from exc

    def close(self) -> None:
        self._context = None
        if self._lease is not None:
            self._lease.close()
            self._lease = None
        self._profile_name = None
        self._pending_portable_state = None
        self._pending_portable_receipt = None
        clear = getattr(self.secrets, "clear", None)
        if clear is not None:
            clear()

    def _require_context(self) -> Any:
        if self._context is None:
            raise AuthenticationError("session operation requires a running browser profile", kind=AuthenticationFailureKind.NOT_READY)
        return self._context

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try: os.unlink(temporary)
            except FileNotFoundError: pass
