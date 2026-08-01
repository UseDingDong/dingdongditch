"""Fail-fast cross-process leases for exclusive runtime resources."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class LeaseUnavailableError(RuntimeError):
    pass


@dataclass
class FileLease:
    path: Path
    handle: BinaryIO

    def close(self) -> None:
        if self.handle.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def acquire_file_lease(path: Path, *, blocking: bool = False) -> FileLease:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            msvcrt.locking(handle.fileno(), mode, 1)
        else:
            import fcntl
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), flags)
    except (OSError, BlockingIOError) as exc:
        handle.close()
        raise LeaseUnavailableError(f"resource is already leased: {path}") from exc
    return FileLease(path=path, handle=handle)
