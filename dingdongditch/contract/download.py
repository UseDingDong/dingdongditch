"""Backend-independent download contracts and secure artifact storage."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import stat
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from dingdongditch.runtime.publication import publish_json


class DownloadCollisionPolicy(str, Enum):
    UNIQUIFY = "uniquify"
    REJECT = "reject"
    REPLACE = "replace"


class DownloadChecksumPolicy(str, Enum):
    SHA256 = "sha256"
    NONE = "none"


class DownloadPageEffectPolicy(str, Enum):
    NO_NEW_PAGE = "no_new_page"
    ALLOW_TRANSIENT_PAGE = "allow_transient_page"
    ALLOW_ONE_PERSISTENT_PAGE = "allow_one_persistent_page"
    ANY_DECLARED_PAGE_EFFECT = "any_declared_page_effect"


class DownloadTriggerAction(str, Enum):
    CLICK = "click"
    PRESS_KEY = "press_key"


class DownloadMimeSource(str, Enum):
    RESPONSE_HEADER = "response_header"
    CONTENT_SIGNATURE = "content_signature"
    EXTENSION = "extension"
    UNKNOWN = "unknown"


class DownloadLifecycleState(str, Enum):
    PENDING = "pending"
    WAITING_FOR_EVENT = "waiting_for_event"
    STARTED = "started"
    SAVING = "saving"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    BLOCKED_BY_POLICY = "blocked_by_policy"

    @property
    def terminal(self) -> bool:
        return self in {
            self.COMPLETED, self.CANCELLED, self.TIMED_OUT, self.FAILED,
            self.INTERRUPTED, self.BLOCKED_BY_POLICY,
        }


class DownloadFailureReason(str, Enum):
    DOWNLOAD_EVENT_NOT_RECEIVED = "download_event_not_received"
    MULTIPLE_DOWNLOAD_EVENTS = "multiple_download_events"
    WRONG_PAGE_DOWNLOAD_EVENT = "wrong_page_download_event"
    TRIGGER_FAILED = "trigger_failed"
    BROWSER_REPORTED_FAILURE = "browser_reported_failure"
    SAVE_FAILED = "save_failed"
    ATOMIC_COMMIT_FAILED = "atomic_commit_failed"
    DESTINATION_REJECTED = "destination_rejected"
    FILENAME_REJECTED = "filename_rejected"
    PATH_ESCAPE_DETECTED = "path_escape_detected"
    COLLISION_REJECTED = "collision_rejected"
    SIZE_LIMIT_EXCEEDED = "size_limit_exceeded"
    EXTENSION_NOT_ALLOWED = "extension_not_allowed"
    MIME_TYPE_NOT_ALLOWED = "mime_type_not_allowed"
    CHECKSUM_FAILED = "checksum_failed"
    PAGE_POLICY_VIOLATION = "page_policy_violation"
    SESSION_TERMINATED = "session_terminated"
    CONTEXT_TERMINATED = "context_terminated"
    CANCEL_REQUEST_FAILED = "cancel_request_failed"
    PERMISSION_DENIED = "permission_denied"
    STORAGE_EXHAUSTED = "storage_exhausted"
    INTERNAL_ERROR = "internal_error"
    DOWNLOAD_TIMEOUT = "download_timeout"


@dataclass(frozen=True)
class DownloadPolicy:
    max_filename_length: int = 180
    max_subdirectory_depth: int = 8
    allow_unknown_mime: bool = False
    allow_extension_derived_mime: bool = False

    def validate(self) -> None:
        if self.max_filename_length < 32:
            raise ValueError("max_filename_length must be >= 32")
        if not 0 <= self.max_subdirectory_depth <= 32:
            raise ValueError("max_subdirectory_depth must be between 0 and 32")
        if not isinstance(self.allow_unknown_mime, bool):
            raise ValueError("allow_unknown_mime must be bool")
        if not isinstance(self.allow_extension_derived_mime, bool):
            raise ValueError("allow_extension_derived_mime must be bool")

    def describe(self) -> dict[str, Any]:
        return {
            "max_filename_length": self.max_filename_length,
            "max_subdirectory_depth": self.max_subdirectory_depth,
            "allow_unknown_mime": self.allow_unknown_mime,
            "allow_extension_derived_mime": self.allow_extension_derived_mime,
        }


@dataclass(frozen=True)
class TrustedDownloadConfig:
    """Host-injected storage authority; never serialized from a plan."""

    artifact_root: str = "artifacts"
    recovery_stale_after_seconds: int = 86_400

    def validate(self) -> None:
        if not isinstance(self.artifact_root, str) or not self.artifact_root or "\x00" in self.artifact_root:
            raise ValueError("trusted artifact_root must be a non-empty path")
        if (
            not isinstance(self.recovery_stale_after_seconds, int)
            or isinstance(self.recovery_stale_after_seconds, bool)
            or self.recovery_stale_after_seconds < 60
        ):
            raise ValueError("recovery_stale_after_seconds must be >= 60")


@dataclass(frozen=True)
class DownloadRequest:
    trigger_action: DownloadTriggerAction = DownloadTriggerAction.CLICK
    trigger_key: str | None = None
    preferred_filename: str | None = None
    destination_subdirectory: str | None = None
    collision_policy: DownloadCollisionPolicy = DownloadCollisionPolicy.UNIQUIFY
    timeout_ms: int = 30_000
    checksum_policy: DownloadChecksumPolicy = DownloadChecksumPolicy.SHA256
    minimum_bytes: int | None = None
    maximum_bytes: int | None = None
    allowed_extensions: tuple[str, ...] = ()
    allowed_mime_types: tuple[str, ...] = ()
    page_effect_policy: DownloadPageEffectPolicy = DownloadPageEffectPolicy.NO_NEW_PAGE
    expected_download_events: int = 1
    correlation_window_ms: int = 750
    late_event_guard_ms: int = 250

    def validate(self) -> None:
        if self.timeout_ms < 100 or self.timeout_ms > 3_600_000:
            raise ValueError("download timeout_ms must be between 100 and 3600000")
        if self.expected_download_events != 1:
            raise ValueError("only exactly one expected download event is supported")
        if not 50 <= self.correlation_window_ms <= self.timeout_ms:
            raise ValueError("correlation_window_ms must be between 50 and timeout_ms")
        if not 0 <= self.late_event_guard_ms < self.timeout_ms:
            raise ValueError("late_event_guard_ms must be non-negative and below timeout_ms")
        if self.trigger_action == DownloadTriggerAction.PRESS_KEY and not self.trigger_key:
            raise ValueError("download press_key trigger requires trigger_key")
        if self.trigger_action == DownloadTriggerAction.CLICK and self.trigger_key is not None:
            raise ValueError("download click trigger must not declare trigger_key")
        for name, value in (("minimum_bytes", self.minimum_bytes), ("maximum_bytes", self.maximum_bytes)):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError(f"{name} must be a non-negative int")
        if self.minimum_bytes is not None and self.maximum_bytes is not None and self.minimum_bytes > self.maximum_bytes:
            raise ValueError("minimum_bytes must not exceed maximum_bytes")
        for ext in self.allowed_extensions:
            if not re.fullmatch(r"\.[A-Za-z0-9]{1,20}", ext):
                raise ValueError("allowed_extensions entries must be dot-prefixed simple extensions")
        for mime in self.allowed_mime_types:
            if not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", mime):
                raise ValueError("invalid allowed MIME type")

    def describe(self) -> dict[str, Any]:
        return {
            "trigger_action": self.trigger_action.value,
            "trigger_key": self.trigger_key,
            "preferred_filename": self.preferred_filename,
            "destination_subdirectory": self.destination_subdirectory,
            "collision_policy": self.collision_policy.value,
            "timeout_ms": self.timeout_ms,
            "checksum_policy": self.checksum_policy.value,
            "minimum_bytes": self.minimum_bytes,
            "maximum_bytes": self.maximum_bytes,
            "allowed_extensions": list(self.allowed_extensions),
            "allowed_mime_types": list(self.allowed_mime_types),
            "page_effect_policy": self.page_effect_policy.value,
            "expected_download_events": self.expected_download_events,
            "correlation_window_ms": self.correlation_window_ms,
            "late_event_guard_ms": self.late_event_guard_ms,
        }


@dataclass
class DownloadArtifact:
    final_path: str
    relative_path: str
    filename: str
    byte_size: int
    mime_type: str | None
    mime_source: str
    mime_evidence: dict[str, Any]
    checksum_algorithm: str | None
    checksum: str | None
    suggested_filename: str | None
    preferred_filename: str | None
    filename_sanitized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "filename": self.filename,
            "byte_size": self.byte_size,
            "mime_type": self.mime_type,
            "mime_source": self.mime_source,
            "mime_evidence": self.mime_evidence,
            "checksum_algorithm": self.checksum_algorithm,
            "checksum": self.checksum,
            "suggested_filename": self.suggested_filename,
            "preferred_filename": self.preferred_filename,
            "filename_sanitized": self.filename_sanitized,
        }


@dataclass
class DownloadResult:
    state: DownloadLifecycleState
    failure_reason: DownloadFailureReason | None = None
    error: str | None = None
    artifact: DownloadArtifact | None = None
    lifecycle: list[dict[str, Any]] = field(default_factory=list)
    page_effects: dict[str, Any] = field(default_factory=dict)
    page_policy_passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "terminal": self.state.terminal,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "error": self.error,
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "lifecycle": list(self.lifecycle),
            "page_effects": dict(self.page_effects),
            "page_policy_passed": self.page_policy_passed,
        }


class DownloadSecurityError(ValueError):
    def __init__(self, message: str, reason: DownloadFailureReason) -> None:
        super().__init__(message)
        self.reason = reason


class DownloadDeadline:
    """One monotonic deadline shared by every lifecycle phase."""

    def __init__(self, absolute_ms: int) -> None:
        self.absolute_ms = absolute_ms

    @classmethod
    def from_limits(
        cls, *, started_ms: int, request_ms: int, operation_ms: int,
        plan_deadline_ms: int | None,
    ) -> "DownloadDeadline":
        values = [started_ms + request_ms, started_ms + operation_ms]
        if plan_deadline_ms is not None:
            values.append(plan_deadline_ms)
        return cls(min(values))

    def remaining_ms(self, phase: str) -> int:
        remaining = self.absolute_ms - int(time.monotonic() * 1000)
        if remaining <= 0:
            raise DownloadTimeoutError(phase)
        return remaining

    def check(self, phase: str) -> None:
        self.remaining_ms(phase)


class DownloadTimeoutError(TimeoutError):
    def __init__(self, phase: str) -> None:
        super().__init__(f"download deadline expired during {phase}")
        self.phase = phase


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")


class SafeFilenameResolver:
    def __init__(self, policy: DownloadPolicy) -> None:
        self.policy = policy

    def filename(self, value: str) -> tuple[str, bool]:
        if not isinstance(value, str):
            raise DownloadSecurityError("filename must be a string", DownloadFailureReason.FILENAME_REJECTED)
        original = value
        value = unicodedata.normalize("NFC", unquote(value or ""))
        if not value or value in {".", ".."} or _CONTROL.search(value):
            raise DownloadSecurityError("unsafe or empty filename", DownloadFailureReason.FILENAME_REJECTED)
        if "/" in value or "\\" in value or _DRIVE.match(value) or value.startswith(("//", "\\\\")):
            raise DownloadSecurityError("filename contains path components", DownloadFailureReason.FILENAME_REJECTED)
        if ":" in value:
            raise DownloadSecurityError("filename contains alternate-stream/device separator", DownloadFailureReason.FILENAME_REJECTED)
        value = value.rstrip(" .")
        if not value or value.strip(".") == "":
            raise DownloadSecurityError("filename normalizes to empty", DownloadFailureReason.FILENAME_REJECTED)
        stem = value.split(".", 1)[0].upper()
        if stem in _RESERVED:
            raise DownloadSecurityError("reserved platform filename", DownloadFailureReason.FILENAME_REJECTED)
        suffix = Path(value).suffix
        if len(value) > self.policy.max_filename_length:
            stem_capacity = self.policy.max_filename_length - len(suffix)
            if stem_capacity < 1:
                raise DownloadSecurityError("filename suffix leaves no safe stem", DownloadFailureReason.FILENAME_REJECTED)
            value = value[:stem_capacity] + suffix
        if len(value) > self.policy.max_filename_length or len(value.encode("utf-8")) > 255:
            raise DownloadSecurityError("filename exceeds platform-safe length", DownloadFailureReason.FILENAME_REJECTED)
        return value, value != original

    def subdirectory(self, value: str | None) -> Path:
        if not value:
            return Path()
        if not isinstance(value, str):
            raise DownloadSecurityError("destination must be a string", DownloadFailureReason.DESTINATION_REJECTED)
        decoded = unicodedata.normalize("NFC", unquote(value))
        if "\x00" in decoded or _DRIVE.match(decoded) or decoded.startswith(("/", "\\", "//", "\\\\")):
            raise DownloadSecurityError("absolute/device destination rejected", DownloadFailureReason.DESTINATION_REJECTED)
        parts = re.split(r"[\\/]", decoded)
        if len(parts) > self.policy.max_subdirectory_depth:
            raise DownloadSecurityError("destination too deep", DownloadFailureReason.DESTINATION_REJECTED)
        safe: list[str] = []
        for part in parts:
            if not part or part in {".", ".."} or _CONTROL.search(part) or ":" in part or part.rstrip(" .") != part:
                raise DownloadSecurityError("unsafe destination component", DownloadFailureReason.PATH_ESCAPE_DETECTED)
            if part.split(".", 1)[0].upper() in _RESERVED:
                raise DownloadSecurityError("reserved destination component", DownloadFailureReason.DESTINATION_REJECTED)
            safe.append(part)
        return Path(*safe)


class CollisionResolver:
    @staticmethod
    def select(path: Path, policy: DownloadCollisionPolicy) -> Path:
        if not path.exists():
            return path
        if policy == DownloadCollisionPolicy.REJECT:
            raise DownloadSecurityError("destination already exists", DownloadFailureReason.COLLISION_REJECTED)
        if policy == DownloadCollisionPolicy.REPLACE:
            return path
        for index in range(1, 10_000):
            candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
            if not candidate.exists():
                return candidate
        raise DownloadSecurityError("unable to select collision-safe path", DownloadFailureReason.COLLISION_REJECTED)


class DownloadIntegrityVerifier:
    @staticmethod
    def _signature_mime(prefix: bytes) -> str | None:
        signatures = (
            (b"MZ", "application/x-msdownload"),
            (b"\x7fELF", "application/x-executable"),
            (b"%PDF-", "application/pdf"),
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"PK\x03\x04", "application/zip"),
            (b"\xff\xd8\xff", "image/jpeg"),
        )
        for magic, mime in signatures:
            if prefix.startswith(magic):
                return mime
        if prefix and b"\x00" not in prefix:
            try:
                prefix.decode("utf-8")
                return "text/plain"
            except UnicodeDecodeError:
                pass
        return None

    @staticmethod
    def normalize_mime(value: str | None) -> str | None:
        if not value or not isinstance(value, str):
            return None
        normalized = value.split(";", 1)[0].strip().lower()
        if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", normalized):
            return None
        return normalized

    @classmethod
    def verify_handle(
        cls,
        fd: int,
        request: DownloadRequest,
        policy: DownloadPolicy,
        *,
        logical_filename: str,
        response_mime: str | None,
        deadline: DownloadDeadline,
    ) -> tuple[
        int, str | None, str, dict[str, Any], str | None,
        tuple[int, int, int, int, int], str,
    ]:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise DownloadSecurityError("staging object is not a regular file", DownloadFailureReason.CHECKSUM_FAILED)
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        size = before.st_size
        if request.minimum_bytes is not None and size < request.minimum_bytes:
            raise DownloadSecurityError("download is below minimum byte size", DownloadFailureReason.SIZE_LIMIT_EXCEEDED)
        if request.maximum_bytes is not None and size > request.maximum_bytes:
            raise DownloadSecurityError("download exceeds maximum byte size", DownloadFailureReason.SIZE_LIMIT_EXCEEDED)
        filename = logical_filename
        ext = Path(filename).suffix.lower()
        if request.allowed_extensions and ext not in {e.lower() for e in request.allowed_extensions}:
            raise DownloadSecurityError("download extension is not allowed", DownloadFailureReason.EXTENSION_NOT_ALLOWED)
        extension_mime = cls.normalize_mime(mimetypes.guess_type(filename)[0])
        normalized_response = cls.normalize_mime(response_mime)
        digest = hashlib.sha256()
        os.lseek(fd, 0, os.SEEK_SET)
        prefix = b""
        try:
            while True:
                deadline.check("hash_verification")
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                if len(prefix) < 4096:
                    prefix += chunk[: 4096 - len(prefix)]
                digest.update(chunk)
        except OSError as exc:
            raise DownloadSecurityError(f"checksum failed: {exc}", DownloadFailureReason.CHECKSUM_FAILED) from exc
        after = os.fstat(fd)
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) != identity:
            raise DownloadSecurityError("staging object changed during verification", DownloadFailureReason.CHECKSUM_FAILED)
        signature_mime = cls._signature_mime(prefix)
        conflicts = len({m for m in (normalized_response, signature_mime, extension_mime) if m}) > 1
        if normalized_response:
            mime, source = normalized_response, DownloadMimeSource.RESPONSE_HEADER
        elif signature_mime:
            mime, source = signature_mime, DownloadMimeSource.CONTENT_SIGNATURE
        elif policy.allow_extension_derived_mime and extension_mime:
            mime, source = extension_mime, DownloadMimeSource.EXTENSION
        else:
            mime, source = None, DownloadMimeSource.UNKNOWN
        allowed = {m.lower() for m in request.allowed_mime_types}
        if allowed:
            if mime is None and not policy.allow_unknown_mime:
                raise DownloadSecurityError("authoritative MIME evidence is unavailable", DownloadFailureReason.MIME_TYPE_NOT_ALLOWED)
            if mime is not None and mime not in allowed:
                raise DownloadSecurityError("download MIME type is not allowed", DownloadFailureReason.MIME_TYPE_NOT_ALLOWED)
            if conflicts and signature_mime and signature_mime not in allowed:
                raise DownloadSecurityError("MIME evidence conflicts with content signature", DownloadFailureReason.MIME_TYPE_NOT_ALLOWED)
        evidence = {
            "response_header": normalized_response,
            "content_signature": signature_mime,
            "extension": extension_mime,
            "conflict": conflicts,
        }
        internal_checksum = digest.hexdigest()
        receipt_checksum = (
            internal_checksum
            if request.checksum_policy == DownloadChecksumPolicy.SHA256
            else None
        )
        return size, mime, source.value, evidence, receipt_checksum, identity, internal_checksum


def _is_link_or_reparse(path: Path) -> bool:
    info = os.lstat(path)
    attrs = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & reparse)


def _path_identity(path: Path) -> tuple[int, int, int]:
    info = os.lstat(path)
    return (
        info.st_dev,
        info.st_ino,
        getattr(info, "st_file_attributes", 0),
    )


class _DirectoryGuard:
    """Pins a directory identity and blocks Windows delete/substitution."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if _is_link_or_reparse(path) or not path.is_dir():
            raise DownloadSecurityError("unsafe directory component", DownloadFailureReason.PATH_ESCAPE_DETECTED)
        self.identity = _path_identity(path)
        self.fd: int | None = None
        self.handle: int | None = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            create_file = ctypes.windll.kernel32.CreateFileW
            create_file.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
            ]
            create_file.restype = wintypes.HANDLE
            handle = create_file(
                str(path), 0x80000000, 0x1 | 0x2, None, 3,
                0x02000000 | 0x00200000, None,
            )
            if handle == wintypes.HANDLE(-1).value:
                raise DownloadSecurityError("cannot pin destination directory", DownloadFailureReason.DESTINATION_REJECTED)
            self.handle = int(handle)
        else:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            self.fd = os.open(path, flags)
        self.assert_stable()

    def assert_stable(self) -> None:
        try:
            if _is_link_or_reparse(self.path) or _path_identity(self.path) != self.identity:
                raise DownloadSecurityError("directory identity changed", DownloadFailureReason.PATH_ESCAPE_DETECTED)
        except FileNotFoundError as exc:
            raise DownloadSecurityError("directory was substituted", DownloadFailureReason.PATH_ESCAPE_DETECTED) from exc

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.handle is not None:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "_DirectoryGuard":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class DownloadArtifactStore:
    def __init__(
        self,
        trusted_config: TrustedDownloadConfig,
        policy: DownloadPolicy,
        session_id: str,
    ) -> None:
        trusted_config.validate()
        policy.validate()
        self.trusted_config = trusted_config
        self.policy = policy
        self.artifact_root = Path(trusted_config.artifact_root).expanduser().absolute()
        self._secure_create_chain(self.artifact_root)
        self.downloads_root = self.artifact_root / "downloads"
        self._secure_create_chain(self.downloads_root)
        self.root = self.downloads_root / session_id
        self.staging = self.root / "staging"
        self.completed = self.root / "completed"
        self.resolver = SafeFilenameResolver(policy)
        self._transaction_lock = threading.RLock()
        self._secure_create_chain(self.root)
        self._secure_create_chain(self.staging)
        self._secure_create_chain(self.completed)
        self._assert_contained(self.staging)
        self._assert_contained(self.completed)
        marker = self.root / ".ddd-session.json"
        if not marker.exists():
            publish_json(
                marker,
                {"session_id": session_id, "created_at": time.time()},
            )
        self._active_marker = self.root / ".active"
        self._active_marker.touch(exist_ok=True)
        self._active_lock = self._lock_file(self._active_marker, blocking=True)

    @staticmethod
    def _lock_file(path: Path, *, blocking: bool) -> Any:
        handle = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                handle.seek(0)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), mode, 1)
            else:
                import fcntl
                flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(), flags)
            return handle
        except Exception:
            handle.close()
            raise

    def close(self) -> None:
        handle = getattr(self, "_active_lock", None)
        if handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
                self._active_lock = None

    @staticmethod
    def _secure_create_chain(target: Path) -> None:
        absolute = target.absolute()
        missing_names: list[str] = []
        cursor = absolute
        while not cursor.exists():
            missing_names.append(cursor.name)
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
        if cursor.exists() and (_is_link_or_reparse(cursor) or not cursor.is_dir()):
            raise DownloadSecurityError("unsafe existing ancestor", DownloadFailureReason.PATH_ESCAPE_DETECTED)
        for parent in reversed(list(cursor.parents)):
            if parent.exists() and _is_link_or_reparse(parent):
                raise DownloadSecurityError("unsafe ancestor", DownloadFailureReason.PATH_ESCAPE_DETECTED)
        created: list[Path] = []
        try:
            current = cursor
            guard = _DirectoryGuard(current)
            try:
                for name in reversed(missing_names):
                    if os.name != "nt" and guard.fd is not None:
                        os.mkdir(name, 0o700, dir_fd=guard.fd)
                    else:
                        (current / name).mkdir()
                    current = current / name
                    created.append(current)
                    next_guard = _DirectoryGuard(current)
                    guard.close()
                    guard = next_guard
            finally:
                guard.close()
        except Exception:
            for component in reversed(created):
                try:
                    component.rmdir()
                except OSError:
                    pass
            raise

    def _assert_contained(self, path: Path) -> None:
        root = self.root.resolve(strict=True)
        resolved = path.resolve(strict=False)
        if resolved != root and root not in resolved.parents:
            raise DownloadSecurityError("path escaped download root", DownloadFailureReason.PATH_ESCAPE_DETECTED)
        cursor = resolved
        while cursor != root.parent:
            if cursor.exists() and _is_link_or_reparse(cursor):
                raise DownloadSecurityError("symlink destination rejected", DownloadFailureReason.PATH_ESCAPE_DETECTED)
            if cursor == root:
                break
            cursor = cursor.parent

    def new_staging_path(self) -> Path:
        path = self.staging / f"{uuid.uuid4().hex}.part"
        with _DirectoryGuard(self.staging) as guard:
            guard.assert_stable()
            flags = (
                os.O_CREAT | os.O_EXCL | os.O_WRONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_BINARY", 0)
            )
            fd = os.open(path, flags, 0o600)
            os.close(fd)
        return path

    def commit(
        self, staging: Path, requested_name: str, request: DownloadRequest,
        suggested: str | None, *, response_mime: str | None,
        deadline: DownloadDeadline,
    ) -> DownloadArtifact:
        with self._transaction_lock:
            return self._commit(
                staging, requested_name, request, suggested,
                response_mime=response_mime, deadline=deadline,
            )

    def _commit(
        self, staging: Path, requested_name: str, request: DownloadRequest,
        suggested: str | None, *, response_mime: str | None,
        deadline: DownloadDeadline,
    ) -> DownloadArtifact:
        deadline.check("destination_validation")
        safe_name, changed = self.resolver.filename(requested_name)
        subdir = self.resolver.subdirectory(request.destination_subdirectory)
        destination_dir = self.completed / subdir
        self._secure_create_chain(destination_dir)
        self._assert_contained(destination_dir)
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0)
        )
        try:
            staging_fd = os.open(staging, flags)
            with _DirectoryGuard(self.staging) as staging_guard, _DirectoryGuard(destination_dir) as destination_guard:
                deadline.check("integrity_verification")
                (
                    size, mime, mime_source, mime_evidence, checksum,
                    identity, internal_checksum,
                ) = DownloadIntegrityVerifier.verify_handle(
                    staging_fd, request, self.policy,
                    logical_filename=safe_name,
                    response_mime=response_mime,
                    deadline=deadline,
                )
                staging_guard.assert_stable()
                destination_guard.assert_stable()
                destination = CollisionResolver.select(
                    destination_dir / safe_name, request.collision_policy
                )
                self._assert_contained(destination)
                deadline.check("atomic_commit")
                # Never hard-link producer-owned staging into completed
                # storage. A producer may retain a writable handle after its
                # save call returns; a hard link would let later writes mutate
                # an already receipted artifact. Copy verified bytes into a
                # new runtime-owned inode, verify the copy, then publish it.
                commit_name = f".{uuid.uuid4().hex}.commit"
                commit_path = destination_dir / commit_name
                create_flags = (
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_BINARY", 0)
                )
                if os.name != "nt" and destination_guard.fd is not None:
                    commit_fd = os.open(
                        commit_name, create_flags, 0o600,
                        dir_fd=destination_guard.fd,
                    )
                else:
                    commit_fd = os.open(commit_path, create_flags, 0o600)
                copied_digest = hashlib.sha256()
                try:
                    os.lseek(staging_fd, 0, os.SEEK_SET)
                    while True:
                        deadline.check("atomic_commit")
                        chunk = os.read(staging_fd, 1024 * 1024)
                        if not chunk:
                            break
                        view = memoryview(chunk)
                        while view:
                            deadline.check("atomic_commit")
                            written = os.write(commit_fd, view)
                            if written <= 0:
                                raise OSError("short write while committing download")
                            view = view[written:]
                        copied_digest.update(chunk)
                    os.fsync(commit_fd)
                finally:
                    os.close(commit_fd)
                staging_after_copy = os.fstat(staging_fd)
                copied_identity = (
                    staging_after_copy.st_dev,
                    staging_after_copy.st_ino,
                    staging_after_copy.st_size,
                    staging_after_copy.st_mtime_ns,
                    staging_after_copy.st_ctime_ns,
                )
                if (
                    copied_identity != identity
                    or copied_digest.hexdigest() != internal_checksum
                ):
                    try:
                        commit_path.unlink()
                    except OSError:
                        pass
                    raise DownloadSecurityError(
                        "staging object changed before atomic commit",
                        DownloadFailureReason.CHECKSUM_FAILED,
                    )
                # Validate the runtime-owned inode completely before it becomes
                # visible under the destination name.  A published artifact is
                # therefore terminal and is never withdrawn after publication.
                candidate_fd = os.open(commit_path, flags)
                try:
                    (
                        candidate_size, _, _, _, _, _, candidate_checksum,
                    ) = DownloadIntegrityVerifier.verify_handle(
                        candidate_fd, request, self.policy,
                        logical_filename=safe_name,
                        response_mime=response_mime,
                        deadline=deadline,
                    )
                finally:
                    os.close(candidate_fd)
                if (
                    candidate_size != size
                    or candidate_checksum != internal_checksum
                ):
                    raise DownloadSecurityError(
                        "commit candidate integrity mismatch",
                        DownloadFailureReason.CHECKSUM_FAILED,
                    )
                destination_guard.assert_stable()
                if request.collision_policy == DownloadCollisionPolicy.REPLACE:
                    destination_guard.assert_stable()
                    if os.name != "nt" and destination_guard.fd is not None:
                        os.replace(
                            commit_name, destination.name,
                            src_dir_fd=destination_guard.fd,
                            dst_dir_fd=destination_guard.fd,
                        )
                    else:
                        os.replace(commit_path, destination)
                else:
                    if os.name != "nt" and destination_guard.fd is not None:
                        os.link(
                            commit_name, destination.name,
                            src_dir_fd=destination_guard.fd,
                            dst_dir_fd=destination_guard.fd,
                            follow_symlinks=False,
                        )
                        os.unlink(commit_name, dir_fd=destination_guard.fd)
                    else:
                        os.link(commit_path, destination, follow_symlinks=False)
                        commit_path.unlink()
                try:
                    staging.unlink()
                except OSError:
                    pass
        except DownloadTimeoutError:
            raise
        except DownloadSecurityError:
            raise
        except PermissionError as exc:
            raise DownloadSecurityError(str(exc), DownloadFailureReason.PERMISSION_DENIED) from exc
        except FileExistsError as exc:
            raise DownloadSecurityError(str(exc), DownloadFailureReason.COLLISION_REJECTED) from exc
        except OSError as exc:
            raise DownloadSecurityError(str(exc), DownloadFailureReason.ATOMIC_COMMIT_FAILED) from exc
        finally:
            if "commit_path" in locals() and commit_path.exists():
                try:
                    commit_path.unlink()
                except OSError:
                    pass
            if "staging_fd" in locals():
                os.close(staging_fd)
        return DownloadArtifact(
            final_path=str(destination),
            relative_path=str(destination.relative_to(self.root)),
            filename=destination.name,
            byte_size=size,
            mime_type=mime,
            mime_source=mime_source,
            mime_evidence=mime_evidence,
            checksum_algorithm="sha256" if checksum else None,
            checksum=checksum,
            suggested_filename=suggested,
            preferred_filename=request.preferred_filename,
            filename_sanitized=changed,
        )

    def recover_staging(self) -> list[str]:
        with self._transaction_lock:
            removed: list[str] = []
            for item in self.staging.glob("*.part"):
                try:
                    item.unlink()
                    removed.append(str(item))
                except OSError:
                    pass
            return removed

    def recover_abandoned_sessions(self, *, deadline: DownloadDeadline) -> dict[str, list[str]]:
        result = {"removed": [], "skipped": [], "failed": []}
        cutoff = time.time() - self.trusted_config.recovery_stale_after_seconds
        with _DirectoryGuard(self.downloads_root):
            for session in list(self.downloads_root.iterdir())[:10_000]:
                deadline.check("staging_recovery")
                if session == self.root:
                    result["skipped"].append(str(session))
                    continue
                try:
                    if _is_link_or_reparse(session) or not session.is_dir():
                        result["skipped"].append(str(session))
                        continue
                    marker = session / ".ddd-session.json"
                    active = session / ".active"
                    staging = session / "staging"
                    completed = session / "completed"
                    if not marker.is_file() or not staging.is_dir() or not completed.is_dir():
                        result["skipped"].append(str(session))
                        continue
                    if any(_is_link_or_reparse(p) for p in (marker, staging, completed)):
                        result["skipped"].append(str(session))
                        continue
                    if marker.stat().st_mtime > cutoff:
                        result["skipped"].append(str(session))
                        continue
                    active.touch(exist_ok=True)
                    try:
                        lock = self._lock_file(active, blocking=False)
                    except OSError:
                        result["skipped"].append(str(session))
                        continue
                    try:
                        with _DirectoryGuard(staging):
                            for item in staging.iterdir():
                                deadline.check("staging_recovery")
                                if item.is_file() and not _is_link_or_reparse(item) and re.fullmatch(r"[0-9a-f]{32}\.part", item.name):
                                    item.unlink()
                                    result["removed"].append(str(item))
                    finally:
                        lock.close()
                except (OSError, DownloadSecurityError) as exc:
                    result["failed"].append(f"{session}:{type(exc).__name__}")
        return result


class StagingRecoveryManager:
    def __init__(self, store: DownloadArtifactStore) -> None:
        self.store = store

    def recover(self) -> list[str]:
        return self.store.recover_staging()


class DownloadEventMonitor:
    """Backend-neutral event correlation ledger populated by browser adapters."""
    def __init__(self, expected_page_id: str) -> None:
        self.expected_page_id = expected_page_id
        self.events: list[dict[str, Any]] = []

    def record(self, *, page_id: str, suggested_filename: str | None) -> None:
        self.events.append({"page_id": page_id, "suggested_filename": suggested_filename})

    def validate(self) -> None:
        if not self.events:
            raise DownloadSecurityError("download event was not received", DownloadFailureReason.DOWNLOAD_EVENT_NOT_RECEIVED)
        if len(self.events) > 1:
            raise DownloadSecurityError("multiple download events received", DownloadFailureReason.MULTIPLE_DOWNLOAD_EVENTS)
        if self.events[0]["page_id"] != self.expected_page_id:
            raise DownloadSecurityError("download came from an unexpected page", DownloadFailureReason.WRONG_PAGE_DOWNLOAD_EVENT)


class DownloadCoordinator:
    """Coordinates browser-provided save callbacks with trusted storage."""
    def __init__(self, store: DownloadArtifactStore) -> None:
        self.store = store

    def complete(
        self,
        *,
        save_to: Any,
        browser_failure: str | None,
        suggested_filename: str | None,
        request: DownloadRequest,
        response_mime: str | None,
        deadline: DownloadDeadline,
        phase_callback: Any | None = None,
    ) -> DownloadArtifact:
        deadline.check("browser_failure")
        if browser_failure:
            raise DownloadSecurityError(browser_failure, DownloadFailureReason.BROWSER_REPORTED_FAILURE)
        staging = self.store.new_staging_path()
        try:
            deadline.check("staging_persistence")
            save_to(str(staging))
        except PermissionError as exc:
            raise DownloadSecurityError(str(exc), DownloadFailureReason.PERMISSION_DENIED) from exc
        except OSError as exc:
            reason = DownloadFailureReason.STORAGE_EXHAUSTED if getattr(exc, "errno", None) == 28 else DownloadFailureReason.SAVE_FAILED
            raise DownloadSecurityError(str(exc), reason) from exc
        except Exception as exc:
            raise DownloadSecurityError(str(exc), DownloadFailureReason.SAVE_FAILED) from exc
        name = request.preferred_filename or suggested_filename
        if not name:
            raise DownloadSecurityError("browser supplied no meaningful filename", DownloadFailureReason.FILENAME_REJECTED)
        try:
            deadline.check("staging_persistence")
            if phase_callback is not None:
                phase_callback("verifying")
            return self.store.commit(
                staging, name, request, suggested_filename,
                response_mime=response_mime, deadline=deadline,
            )
        finally:
            if staging.exists():
                try:
                    staging.unlink()
                except OSError:
                    pass
