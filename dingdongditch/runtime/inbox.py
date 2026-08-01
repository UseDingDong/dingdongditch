"""Atomic publication primitives for file-backed runtime inboxes."""

from __future__ import annotations

from pathlib import Path

from dingdongditch.runtime.publication import (
    PublicationUnavailableError,
    publish_text as _publish_text,
    read_published_text as _read_published_text,
)


def publish_text(path: Path, text: str) -> None:
    """Publish one complete, non-empty UTF-8 message with an atomic replace."""
    _publish_text(path, text, require_nonempty=True)


def read_published_text(path: Path) -> str | None:
    """Return a complete published message, or None when none is published."""
    try:
        return _read_published_text(path, encoding="utf-8-sig")
    except PublicationUnavailableError:
        return None
