"""Atomic file queue with explicit publication, claim, and completion ownership."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dingdongditch.runtime.publication import publish_json, read_published_json
from dingdongditch.runtime.file_lease import acquire_file_lease


@dataclass(frozen=True)
class ClaimedMessage:
    message_id: str
    path: Path
    payload: dict[str, Any]


class AtomicFileQueue:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pending = root / "pending"
        self.claimed = root / "claimed"
        self.completed = root / "completed"
        for path in (self.pending, self.claimed, self.completed):
            path.mkdir(parents=True, exist_ok=True)

    def publish(self, payload: dict[str, Any], *, message_id: str | None = None) -> str:
        message_id = message_id or uuid.uuid4().hex
        if not message_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in message_id):
            raise ValueError("invalid queue message_id")
        destination = self.pending / f"{message_id}.json"
        encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.pending, prefix=".publishing-",
                suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            # Hard-link publication is atomic and exclusive: an immutable queue
            # identifier can never overwrite an earlier producer's message.
            os.link(temporary, destination)
            temporary.unlink()
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return message_id

    def claim(self) -> ClaimedMessage | None:
        lease = acquire_file_lease(self.root / ".claim.lock", blocking=True)
        try:
            for pending in sorted(self.pending.glob("*.json")):
                message_id = pending.stem
                payload = read_published_json(pending)
                claimed = self.claimed / f"{message_id}.{uuid.uuid4().hex}.json"
                try:
                    os.replace(pending, claimed)
                except FileNotFoundError:
                    continue
                return ClaimedMessage(message_id, claimed, payload)
            return None
        finally:
            lease.close()

    def complete(self, claim: ClaimedMessage, result: dict[str, Any]) -> Path:
        if claim.path.parent != self.claimed or not claim.path.is_file():
            raise RuntimeError("queue claim is not owned by this queue")
        destination = self.completed / f"{claim.message_id}.json"
        publish_json(destination, result)
        claim.path.unlink()
        return destination
