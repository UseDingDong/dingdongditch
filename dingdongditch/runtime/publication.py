"""Shared atomic publication contract for externally visible artifacts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class PublicationUnavailableError(FileNotFoundError):
    """The publication is absent or transiently inaccessible during replacement."""


_append_locks: dict[Path, threading.Lock] = {}
_append_locks_guard = threading.Lock()
_publication_locks: dict[Path, threading.Lock] = {}
_publication_locks_guard = threading.Lock()


@contextmanager
def _publication_guard(path: Path):
    resolved = path.resolve()
    with _publication_locks_guard:
        thread_lock = _publication_locks.setdefault(resolved, threading.Lock())
    with thread_lock:
        from dingdongditch.runtime.file_lease import acquire_file_lease
        lease = acquire_file_lease(
            path.parent / f".{path.name}.publication.lock", blocking=True
        )
        try:
            yield
        finally:
            lease.close()


def atomic_replace(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def commit_file(source: Path, destination: Path) -> None:
    """Fsync and atomically publish a complete same-filesystem file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Windows requires a writable descriptor for fsync/FlushFileBuffers.
    # The file contents are not changed here.
    with source.open("r+b") as handle:
        os.fsync(handle.fileno())
    atomic_replace(source, destination)


def publish_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    with _publication_guard(path):
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            atomic_replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def publish_text(path: Path, text: str, *, require_nonempty: bool = False) -> None:
    if require_nonempty and not text:
        raise ValueError("published text is required")
    publish_bytes(path, text.encode("utf-8"))


def publish_json(path: Path, value: Any, *, indent: int = 2, sort_keys: bool = False) -> None:
    publish_text(
        path,
        json.dumps(value, indent=indent, sort_keys=sort_keys, ensure_ascii=False),
    )


def read_published_text(path: Path, *, encoding: str = "utf-8") -> str:
    with _publication_guard(path):
        payload = _read_shared_bytes(path)
        if not payload:
            raise PublicationUnavailableError(str(path))
        return payload.decode(encoding)


def _read_shared_bytes(path: Path) -> bytes | None:
    if sys.platform != "win32":
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path), 0x80000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None, 3, 0x00000080, None,
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        if error in {2, 3, 5, 32}:
            return None
        raise OSError(error, ctypes.FormatError(error), str(path))
    try:
        size = ctypes.c_longlong()
        if not kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
            error = ctypes.get_last_error()
            raise OSError(error, ctypes.FormatError(error), str(path))
        if size.value == 0:
            return b""
        buffer = ctypes.create_string_buffer(size.value)
        count = wintypes.DWORD()
        if not kernel32.ReadFile(handle, buffer, size.value, ctypes.byref(count), None):
            error = ctypes.get_last_error()
            raise OSError(error, ctypes.FormatError(error), str(path))
        return buffer.raw[:count.value]
    finally:
        kernel32.CloseHandle(handle)


def read_published_json(path: Path) -> Any:
    try:
        return json.loads(read_published_text(path))
    except json.JSONDecodeError as exc:
        raise PublicationUnavailableError(str(path)) from exc


def append_json_line(path: Path, value: Any) -> None:
    """Atomically publish a complete JSONL generation after adding one record."""
    resolved = path.resolve()
    with _append_locks_guard:
        lock = _append_locks.setdefault(resolved, threading.Lock())
    line = json.dumps(value, ensure_ascii=False) + "\n"
    with lock:
        from dingdongditch.runtime.file_lease import acquire_file_lease
        lease = acquire_file_lease(
            path.parent / f".{path.name}.append.lock", blocking=True
        )
        try:
            try:
                existing = read_published_text(path)
            except PublicationUnavailableError:
                existing = ""
            publish_text(path, existing + line)
        finally:
            lease.close()
