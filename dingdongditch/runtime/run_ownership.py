"""Generation-scoped ownership for file-backed runtime runs."""

from __future__ import annotations

import os
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dingdongditch.runtime.publication import publish_json, publish_text


@dataclass
class RunDirectoryLease:
    root: Path
    generation_id: str
    path: Path
    _handle: Any
    _finished: bool = False

    def finish(self, outcome: str, **detail: Any) -> None:
        if outcome not in {"completed", "failed", "stopped"}:
            raise ValueError("invalid run outcome")
        if self._finished:
            raise RuntimeError("run generation is already terminal")
        publish_json(
            self.path / "completion.json",
            {
                "generation_id": self.generation_id,
                "state": "terminal",
                "outcome": outcome,
                "finished_at_epoch": time.time(),
                "detail": detail,
            },
            sort_keys=True,
        )
        self._finished = True

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            if not self._finished:
                self.finish("stopped", reason="owner_closed_without_outcome")
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "RunDirectoryLease":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _lock(path: Path) -> Any:
    handle = path.open("a+b")
    try:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except Exception:
        handle.close()
        raise


def acquire_run_generation(root: Path, *, generation_id: str | None = None) -> RunDirectoryLease:
    """Create and exclusively own one fully initialized run generation."""
    root = root.resolve()
    generations = root / "generations"
    generations.mkdir(parents=True, exist_ok=True)
    generation_id = generation_id or uuid.uuid4().hex
    if not generation_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in generation_id):
        raise ValueError("invalid run generation_id")

    staging = generations / f".building-{generation_id}-{uuid.uuid4().hex}"
    destination = generations / generation_id
    staging.mkdir(parents=False, exist_ok=False)
    try:
        owner = {
            "generation_id": generation_id,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "created_at_epoch": time.time(),
        }
        owner_path = staging / "owner.json"
        publish_json(owner_path, owner, sort_keys=True)
        publish_json(
            staging / "manifest.json",
            {
                "generation_id": generation_id,
                "state": "active",
                "published_at_epoch": time.time(),
            },
            sort_keys=True,
        )
        lease_path = staging / ".lease"
        with lease_path.open("wb") as handle:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, destination)
    except Exception:
        for item in staging.iterdir() if staging.exists() else ():
            item.unlink(missing_ok=True)
        if staging.exists():
            staging.rmdir()
        raise

    lease = RunDirectoryLease(root, generation_id, destination, _lock(destination / ".lease"))
    publish_text(root / "current", generation_id)
    return lease
