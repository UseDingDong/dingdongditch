"""Explicit, fail-closed file-upload authorization and safe evidence helpers."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class UploadValidationError(ValueError):
    def __init__(self, message: str, *, failure_kind: str) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


def _absolute_path(value: str, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise UploadValidationError(
            f"{field} entries must be non-empty strings",
            failure_kind="invalid_upload_path",
        )
    path = Path(value)
    if not path.is_absolute():
        raise UploadValidationError(
            f"{field} entries must be absolute paths",
            failure_kind="upload_path_not_absolute",
        )
    return path


def safe_file_identifier(path: Path) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return f"file-{digest}"


@dataclass(frozen=True)
class UploadAuthorization:
    """Exact requested files and the host authority under which they may be read."""

    file_paths: tuple[str, ...]
    allowed_files: tuple[str, ...] = ()
    allowed_roots: tuple[str, ...] = ()

    def validate_and_resolve(self) -> tuple[Path, ...]:
        if not self.file_paths:
            raise UploadValidationError(
                "upload_file requires at least one file path",
                failure_kind="upload_files_empty",
            )
        if not self.allowed_files and not self.allowed_roots:
            raise UploadValidationError(
                "upload_file requires explicit allowed_files or allowed_roots authorization",
                failure_kind="upload_authorization_missing",
            )

        resolved_allowed_files: set[Path] = set()
        for value in self.allowed_files:
            path = _absolute_path(value, field="allowed_files")
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise UploadValidationError(
                    "an authorized file does not exist",
                    failure_kind="upload_allowed_file_missing",
                ) from exc
            if not resolved.is_file():
                raise UploadValidationError(
                    "allowed_files entries must be files",
                    failure_kind="upload_allowed_file_not_file",
                )
            resolved_allowed_files.add(resolved)

        resolved_roots: list[Path] = []
        for value in self.allowed_roots:
            path = _absolute_path(value, field="allowed_roots")
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise UploadValidationError(
                    "an authorized root does not exist",
                    failure_kind="upload_allowed_root_missing",
                ) from exc
            if not resolved.is_dir():
                raise UploadValidationError(
                    "allowed_roots entries must be directories",
                    failure_kind="upload_allowed_root_not_directory",
                )
            resolved_roots.append(resolved)

        result: list[Path] = []
        seen: set[Path] = set()
        for value in self.file_paths:
            path = _absolute_path(value, field="file_paths")
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise UploadValidationError(
                    f"upload file does not exist: {path.name or '<unnamed>'}",
                    failure_kind="upload_file_missing",
                ) from exc
            if not resolved.is_file():
                raise UploadValidationError(
                    f"upload path is not a file: {resolved.name or '<unnamed>'}",
                    failure_kind="upload_path_not_file",
                )
            authorized = resolved in resolved_allowed_files or any(
                resolved.is_relative_to(root) for root in resolved_roots
            )
            if not authorized:
                raise UploadValidationError(
                    f"upload file is outside the explicit allowlist: {resolved.name}",
                    failure_kind="upload_path_not_authorized",
                )
            if resolved in seen:
                raise UploadValidationError(
                    f"duplicate upload file: {resolved.name}",
                    failure_kind="duplicate_upload_file",
                )
            seen.add(resolved)
            result.append(resolved)
        return tuple(result)

    def safe_evidence(self, resolved: Iterable[Path] | None = None) -> dict[str, object]:
        paths = tuple(resolved) if resolved is not None else tuple(Path(p) for p in self.file_paths)
        return {
            "requested_file_names": [path.name for path in paths],
            "file_identifiers": [safe_file_identifier(path) for path in paths],
            "file_count": len(paths),
        }


def accept_allows(path: Path, accept: str | None) -> bool:
    """Apply the HTML accept hint conservatively for extensions and MIME types."""
    if not accept or not accept.strip():
        return True
    suffix = path.suffix.lower()
    mime = (mimetypes.guess_type(path.name)[0] or "").lower()
    for raw in accept.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token.startswith(".") and suffix == token:
            return True
        if token.endswith("/*") and mime.startswith(token[:-1]):
            return True
        if "/" in token and mime == token:
            return True
    return False
