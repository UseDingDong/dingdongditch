from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import urlsplit

from dingdongditch.runtime.file_lease import FileLease
from .callbacks import AuthEvent, AuthenticationCallbacks
from .errors import AuthenticationError, AuthenticationFailureKind
from .profiles import ProfileManager
from .secrets import SecretProvider

_SESSION_SCHEMA = 1


def validate_session_state(raw: object) -> dict[str, Any]:
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
        parsed = urlsplit(origin["origin"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AuthenticationError("session file contains an unsafe storage origin", kind=AuthenticationFailureKind.SESSION_INVALID)
        if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("value"), str) for item in origin["localStorage"]):
            raise AuthenticationError("session file contains invalid local storage entries", kind=AuthenticationFailureKind.SESSION_INVALID)
    return state


class AuthenticationCapability:
    """Sole owner of named profiles, session state, secrets and auth callbacks."""
    def __init__(self, *, profiles: ProfileManager | None = None, secrets: SecretProvider | None = None, callbacks: AuthenticationCallbacks | None = None) -> None:
        self.profiles = profiles or ProfileManager()
        self.secrets = secrets
        self.callbacks = callbacks or AuthenticationCallbacks()
        self._lease: FileLease | None = None
        self._context: Any = None
        self._profile_name: str | None = None

    def acquire_profile(self, name: str) -> Path:
        if self._lease is not None:
            raise AuthenticationError("authentication capability already owns a profile", kind=AuthenticationFailureKind.PROFILE_IN_USE)
        info = self.profiles.require(name)
        self._lease = self.profiles.acquire(name)
        self._profile_name = name
        return info.path / "browser-data"

    def bind_context(self, context: Any) -> None:
        self._context = context

    def verify_ready(self, page: Any) -> None:
        try:
            if page is None or page.is_closed():
                raise RuntimeError("page is closed")
            page.evaluate("() => document.readyState")
        except Exception as exc:
            raise AuthenticationError("browser profile started but did not become ready", kind=AuthenticationFailureKind.NOT_READY, recovery="Retry the run; if it repeats, recreate the profile.") from exc

    def inject(self, locator: Any, secret_name: str) -> None:
        if self.secrets is None:
            raise AuthenticationError("no application SecretProvider is configured", kind=AuthenticationFailureKind.SECRET_NOT_FOUND)
        with self.secrets.get(secret_name) as secret:
            try:
                locator.fill(secret.reveal())
            except Exception as exc:
                raise AuthenticationError("secret injection browser operation failed", kind=AuthenticationFailureKind.SESSION_IO_ERROR, recovery="Check the target and retry.") from exc

    def emit(self, event: AuthEvent) -> list[object]:
        return self.callbacks.emit(event)

    def export_session(self, destination: Path) -> None:
        context = self._require_context()
        try:
            state = context.storage_state()
            validate_session_state({"schema_version": _SESSION_SCHEMA, "storage_state": state})
            self._atomic_json(destination.resolve(), {"schema_version": _SESSION_SCHEMA, "storage_state": state})
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("session export failed", kind=AuthenticationFailureKind.SESSION_IO_ERROR, recovery="Check the destination and retry.") from exc

    def import_session(self, source: Path) -> None:
        context = self._require_context()
        try:
            if source.stat().st_size > 10 * 1024 * 1024:
                raise AuthenticationError("session file exceeds the 10 MiB safety limit", kind=AuthenticationFailureKind.SESSION_INVALID)
            raw = json.loads(source.read_text(encoding="utf-8"))
            state = validate_session_state(raw)
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
        except AuthenticationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthenticationError("session file is unreadable or corrupt", kind=AuthenticationFailureKind.SESSION_INVALID, recovery="Use a valid exported session file.") from exc
        except Exception as exc:
            raise AuthenticationError("session import failed safely", kind=AuthenticationFailureKind.SESSION_IO_ERROR, recovery="Clear the profile session and retry.") from exc

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
