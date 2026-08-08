"""Public stateful facade over the existing DingDongDitch execution runtime."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from dingdongditch.authentication import AuthenticationError
from dingdongditch.authentication import AuthenticationCapability
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import BrowserConfig, BrowserConfigError
from dingdongditch.contract.observation import (
    ObservationReference,
    PageObservation,
    PageObservationOptions,
)
from dingdongditch.contract.operation import Operation
from dingdongditch.contract.plan import ExecutionPlan, PlanReceipt
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.download import TrustedDownloadConfig
from dingdongditch.runtime.executor import execute_operation as _execute_operation
from dingdongditch.runtime.plan_executor import execute_plan as _execute_plan


def _now_ms() -> int:
    return int(time.time() * 1000)


class PublicSessionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"
    TERMINAL = "terminal"


class SessionFailureKind(str, Enum):
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_CLOSED = "session_closed"
    SESSION_EXPIRED = "session_expired"
    PROFILE_LOCKED = "profile_locked"
    BROWSER_STARTUP_FAILURE = "browser_startup_failure"
    INVALID_PAGE_ID = "invalid_page_id"
    TERMINAL_BROWSER_FAILURE = "terminal_browser_failure"
    OPERATION_REJECTED = "operation_rejected"
    CLEANUP_FAILURE = "cleanup_failure"
    SESSION_BUSY = "session_busy"
    SESSION_CONFIG_MISMATCH = "session_config_mismatch"


class StatefulSessionError(RuntimeError):
    def __init__(self, message: str, *, failure_kind: SessionFailureKind) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind

    def to_dict(self) -> dict[str, str]:
        return {"failure_kind": self.failure_kind.value, "message": str(self)}


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    status: PublicSessionStatus
    created_at_ms: int
    last_activity_at_ms: int
    idle_timeout_ms: int
    profile: str
    browser_engine: str
    headless: bool
    pages: tuple[dict[str, Any], ...]
    cleanup_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "created_at_ms": self.created_at_ms,
            "last_activity_at_ms": self.last_activity_at_ms,
            "idle_timeout_ms": self.idle_timeout_ms,
            "profile": self.profile,
            "browser_engine": self.browser_engine,
            "headless": self.headless,
            "pages": [dict(page) for page in self.pages],
            "cleanup_errors": list(self.cleanup_errors),
        }


@dataclass(frozen=True)
class SessionObservation:
    session_id: str
    page_id: str
    observation: PageObservation
    observed_at_ms: int

    def reference(self, element_id: str, *, expected: dict[str, Any] | None = None) -> ObservationReference:
        return ObservationReference(
            observation_id=self.observation.observation_id,
            element_id=element_id,
            expected=dict(expected or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "page_id": self.page_id,
            "observed_at_ms": self.observed_at_ms,
            "observation": self.observation.to_dict(),
        }


@dataclass(frozen=True)
class SessionOperationResult:
    session_id: str
    operation_id: str
    receipt: ExecutionReceipt
    verdict: str
    recoverable: bool
    terminal: bool
    page_state: tuple[dict[str, Any], ...]
    events: dict[str, Any]
    started_at_ms: int
    finished_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "operation_id": self.operation_id,
            "receipt": self.receipt.to_dict(),
            "verdict": self.verdict,
            "recoverable": self.recoverable,
            "terminal": self.terminal,
            "page_state": [dict(page) for page in self.page_state],
            "events": dict(self.events),
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "duration_ms": max(0, self.finished_at_ms - self.started_at_ms),
        }


@dataclass(frozen=True)
class SessionPlanResult:
    session_id: str
    receipt: PlanReceipt
    recoverable: bool
    terminal: bool
    page_state: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "receipt": self.receipt.to_dict(),
            "recoverable": self.recoverable,
            "terminal": self.terminal,
            "page_state": [dict(page) for page in self.page_state],
        }


@dataclass
class _SessionRecord:
    session_id: str
    backend: PlaywrightBackend | None
    config: BrowserConfig
    created_at_ms: int
    last_activity_at_ms: int
    idle_timeout_ms: int
    status: PublicSessionStatus = PublicSessionStatus.OPEN
    cleanup_errors: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class StatefulSessionRuntime:
    """Process-local owner of retained, isolated browser sessions."""

    def __init__(self, *, default_idle_timeout_ms: int = 30 * 60 * 1000) -> None:
        if not isinstance(default_idle_timeout_ms, int) or default_idle_timeout_ms <= 0:
            raise ValueError("default_idle_timeout_ms must be a positive integer")
        self.default_idle_timeout_ms = default_idle_timeout_ms
        self._records: dict[str, _SessionRecord] = {}
        self._registry_lock = threading.RLock()

    def open_session(
        self,
        browser_config: BrowserConfig | None = None,
        *,
        idle_timeout_ms: int | None = None,
        trusted_download_config: TrustedDownloadConfig | None = None,
        authentication: AuthenticationCapability | None = None,
    ) -> SessionInfo:
        config = browser_config or BrowserConfig()
        config.validate()
        timeout = self.default_idle_timeout_ms if idle_timeout_ms is None else idle_timeout_ms
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("idle_timeout_ms must be a positive integer")
        backend = PlaywrightBackend(
            browser_config=config,
            trusted_download_config=trusted_download_config,
            authentication=authentication,
        )
        try:
            backend.start()
        except BrowserConfigError as exc:
            kind = (
                SessionFailureKind.PROFILE_LOCKED
                if exc.failure_kind.value == "profile_in_use"
                else SessionFailureKind.BROWSER_STARTUP_FAILURE
            )
            raise StatefulSessionError(
                "browser session could not be started",
                failure_kind=kind,
            ) from exc
        except AuthenticationError as exc:
            raise StatefulSessionError(
                "browser session authentication setup failed",
                failure_kind=SessionFailureKind.BROWSER_STARTUP_FAILURE,
            ) from exc
        now = _now_ms()
        record = _SessionRecord(
            session_id=str(uuid.uuid4()),
            backend=backend,
            config=config,
            created_at_ms=now,
            last_activity_at_ms=now,
            idle_timeout_ms=timeout,
        )
        with self._registry_lock:
            self._records[record.session_id] = record
        return self._info(record)

    def get_session(self, session_id: str) -> SessionInfo:
        record = self._require_record(session_id, require_open=False)
        if record.status == PublicSessionStatus.OPEN:
            self._expire_if_idle(record)
        return self._info(record)

    def observe_page(
        self,
        session_id: str,
        options: PageObservationOptions | None = None,
        *,
        page_id: str | None = None,
    ) -> SessionObservation:
        record = self._access(session_id)
        with self._locked(record):
            backend = self._active_backend(record)
            if page_id is not None:
                self._select_backend_page(backend, page_id)
            observation = backend.observe_page(options)
            self._touch(record)
            return SessionObservation(
                session_id=record.session_id,
                page_id=str(backend.page_id),
                observation=observation,
                observed_at_ms=_now_ms(),
            )

    def execute_operation(
        self,
        session_id: str,
        operation: Operation,
        *,
        observation_reference: ObservationReference | None = None,
    ) -> SessionOperationResult:
        record = self._access(session_id)
        with self._locked(record):
            backend = self._active_backend(record)
            before_pages = backend.list_pages()
            before_dialogs = backend.list_dialog_history()
            started = _now_ms()
            receipt = _execute_operation(
                operation,
                backend=backend,
                browser_config=record.config,
                observation_reference=observation_reference,
            )
            finished = _now_ms()
            alive = backend.is_started
            if not alive:
                record.status = PublicSessionStatus.TERMINAL
            self._touch(record)
            after_pages = backend.list_pages() if alive else tuple()
            after_dialogs = backend.list_dialog_history() if alive else tuple()
            before_page_ids = {page["page_id"] for page in before_pages}
            new_pages = [page for page in after_pages if page["page_id"] not in before_page_ids]
            new_dialogs = list(after_dialogs[len(before_dialogs):])
            events = {
                "new_pages": new_pages,
                "dialogs": new_dialogs,
                "navigation_occurred": receipt.navigation_occurred,
                "active_page_id_before": next((p["page_id"] for p in before_pages if p.get("active")), None),
                "active_page_id_after": next((p["page_id"] for p in after_pages if p.get("active")), None),
                "download": (receipt.action_evidence or {}).get("download"),
            }
            return SessionOperationResult(
                session_id=record.session_id,
                operation_id=operation.operation_id,
                receipt=receipt,
                verdict=receipt.verdict.value,
                recoverable=alive,
                terminal=not alive,
                page_state=tuple(after_pages),
                events=events,
                started_at_ms=started,
                finished_at_ms=finished,
            )

    def execute_plan(self, session_id: str, plan: ExecutionPlan) -> SessionPlanResult:
        record = self._access(session_id)
        with self._locked(record):
            backend = self._active_backend(record)
            if plan.browser_config.describe() != record.config.describe():
                raise StatefulSessionError(
                    "plan browser configuration does not match the retained session",
                    failure_kind=SessionFailureKind.SESSION_CONFIG_MISMATCH,
                )
            receipt = _execute_plan(plan, backend=backend)
            alive = backend.is_started
            if not alive:
                record.status = PublicSessionStatus.TERMINAL
            self._touch(record)
            return SessionPlanResult(
                session_id=record.session_id,
                receipt=receipt,
                recoverable=alive,
                terminal=not alive,
                page_state=tuple(backend.list_pages() if alive else ()),
            )

    def inspect_pages(self, session_id: str) -> tuple[dict[str, Any], ...]:
        record = self._access(session_id)
        with self._locked(record):
            pages = tuple(self._active_backend(record).list_pages())
            self._touch(record)
            return pages

    def select_page(self, session_id: str, page_id: str) -> dict[str, Any]:
        record = self._access(session_id)
        with self._locked(record):
            backend = self._active_backend(record)
            self._select_backend_page(backend, page_id)
            self._touch(record)
            return next(page for page in backend.list_pages() if page["page_id"] == page_id)

    def inspect_dialogs(self, session_id: str) -> tuple[dict[str, Any], ...]:
        record = self._access(session_id)
        with self._locked(record):
            dialogs = tuple(self._active_backend(record).list_dialog_history())
            self._touch(record)
            return dialogs

    def close_session(self, session_id: str) -> SessionInfo:
        record = self._require_record(session_id, require_open=False)
        if record.status in (PublicSessionStatus.CLOSED, PublicSessionStatus.EXPIRED):
            return self._info(record)
        with self._locked(record):
            self._close_record(record, PublicSessionStatus.CLOSED)
            info = self._info(record)
            if record.cleanup_errors:
                raise StatefulSessionError(
                    "browser session closed with cleanup failures",
                    failure_kind=SessionFailureKind.CLEANUP_FAILURE,
                )
            return info

    def cleanup_expired_sessions(self) -> tuple[str, ...]:
        now = _now_ms()
        cleaned: list[str] = []
        with self._registry_lock:
            records = list(self._records.values())
        for record in records:
            if record.status != PublicSessionStatus.OPEN:
                continue
            if now - record.last_activity_at_ms < record.idle_timeout_ms:
                continue
            with self._locked(record):
                if record.status == PublicSessionStatus.OPEN and now - record.last_activity_at_ms >= record.idle_timeout_ms:
                    self._close_record(record, PublicSessionStatus.EXPIRED)
                    cleaned.append(record.session_id)
        return tuple(cleaned)

    def _info(self, record: _SessionRecord) -> SessionInfo:
        pages: tuple[dict[str, Any], ...] = ()
        if record.status == PublicSessionStatus.OPEN and record.backend is not None:
            try:
                pages = tuple(record.backend.list_pages())
            except Exception:
                pages = ()
        env = record.config.describe()
        return SessionInfo(
            session_id=record.session_id,
            status=record.status,
            created_at_ms=record.created_at_ms,
            last_activity_at_ms=record.last_activity_at_ms,
            idle_timeout_ms=record.idle_timeout_ms,
            profile=str(env["profile"]),
            browser_engine=str(env["engine"]),
            headless=bool(env["headless"]),
            pages=pages,
            cleanup_errors=tuple(record.cleanup_errors),
        )

    def _require_record(self, session_id: str, *, require_open: bool = True) -> _SessionRecord:
        if not isinstance(session_id, str) or not session_id:
            raise StatefulSessionError("session was not found", failure_kind=SessionFailureKind.SESSION_NOT_FOUND)
        with self._registry_lock:
            record = self._records.get(session_id)
        if record is None:
            raise StatefulSessionError("session was not found", failure_kind=SessionFailureKind.SESSION_NOT_FOUND)
        if require_open:
            if record.status == PublicSessionStatus.CLOSED:
                raise StatefulSessionError("session is closed", failure_kind=SessionFailureKind.SESSION_CLOSED)
            if record.status == PublicSessionStatus.EXPIRED:
                raise StatefulSessionError("session is expired", failure_kind=SessionFailureKind.SESSION_EXPIRED)
            if record.status == PublicSessionStatus.TERMINAL:
                raise StatefulSessionError("browser session is terminal", failure_kind=SessionFailureKind.TERMINAL_BROWSER_FAILURE)
        return record

    def _access(self, session_id: str) -> _SessionRecord:
        record = self._require_record(session_id)
        self._expire_if_idle(record)
        return self._require_record(session_id)

    def _expire_if_idle(self, record: _SessionRecord) -> None:
        if record.status == PublicSessionStatus.OPEN and _now_ms() - record.last_activity_at_ms >= record.idle_timeout_ms:
            with self._locked(record):
                if record.status == PublicSessionStatus.OPEN and _now_ms() - record.last_activity_at_ms >= record.idle_timeout_ms:
                    self._close_record(record, PublicSessionStatus.EXPIRED)

    def _active_backend(self, record: _SessionRecord) -> PlaywrightBackend:
        backend = record.backend
        if backend is None or not backend.is_started:
            record.status = PublicSessionStatus.TERMINAL
            raise StatefulSessionError("browser session is terminal", failure_kind=SessionFailureKind.TERMINAL_BROWSER_FAILURE)
        return backend

    def _select_backend_page(self, backend: PlaywrightBackend, page_id: str) -> None:
        page = backend.inspect_page(page_id)
        if page is None or page.get("lifecycle_state") != "open":
            raise StatefulSessionError("page ID is invalid or closed", failure_kind=SessionFailureKind.INVALID_PAGE_ID)
        backend._activate_page(page_id)

    def _touch(self, record: _SessionRecord) -> None:
        record.last_activity_at_ms = _now_ms()

    def _close_record(self, record: _SessionRecord, status: PublicSessionStatus) -> None:
        backend = record.backend
        if backend is not None:
            try:
                backend.stop()
            except Exception:
                record.cleanup_errors.append("browser cleanup failed")
            if backend.cleanup_errors and "browser cleanup reported errors" not in record.cleanup_errors:
                record.cleanup_errors.append("browser cleanup reported errors")
        record.backend = None
        record.status = status
        record.last_activity_at_ms = _now_ms()

    class _LockContext:
        def __init__(self, record: _SessionRecord) -> None:
            self.record = record
            self.acquired = False

        def __enter__(self) -> None:
            self.acquired = self.record.lock.acquire(blocking=False)
            if not self.acquired:
                raise StatefulSessionError("session is busy", failure_kind=SessionFailureKind.SESSION_BUSY)

        def __exit__(self, *_: Any) -> None:
            if self.acquired:
                self.record.lock.release()

    def _locked(self, record: _SessionRecord) -> "StatefulSessionRuntime._LockContext":
        return self._LockContext(record)


_default_runtime = StatefulSessionRuntime()


def open_session(*args: Any, **kwargs: Any) -> SessionInfo:
    return _default_runtime.open_session(*args, **kwargs)


def get_session(session_id: str) -> SessionInfo:
    return _default_runtime.get_session(session_id)


def observe_session_page(session_id: str, *args: Any, **kwargs: Any) -> SessionObservation:
    return _default_runtime.observe_page(session_id, *args, **kwargs)


def execute_session_operation(session_id: str, operation: Operation, **kwargs: Any) -> SessionOperationResult:
    return _default_runtime.execute_operation(session_id, operation, **kwargs)


def execute_session_plan(session_id: str, plan: ExecutionPlan) -> SessionPlanResult:
    return _default_runtime.execute_plan(session_id, plan)


def inspect_session_pages(session_id: str) -> tuple[dict[str, Any], ...]:
    return _default_runtime.inspect_pages(session_id)


def select_session_page(session_id: str, page_id: str) -> dict[str, Any]:
    return _default_runtime.select_page(session_id, page_id)


def inspect_session_dialogs(session_id: str) -> tuple[dict[str, Any], ...]:
    return _default_runtime.inspect_dialogs(session_id)


def close_session(session_id: str) -> SessionInfo:
    return _default_runtime.close_session(session_id)


def cleanup_expired_sessions() -> tuple[str, ...]:
    return _default_runtime.cleanup_expired_sessions()
