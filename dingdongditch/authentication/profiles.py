from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from dingdongditch.runtime.file_lease import FileLease, LeaseUnavailableError, acquire_file_lease
from .errors import AuthenticationError, AuthenticationFailureKind

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SCHEMA = 1
_RESERVED_PROFILE_NAMES = frozenset({"benchmark", "dingdong", "default"})


def profile_root() -> Path:
    override = os.environ.get("DINGDONGDITCH_PROFILE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return (base / "DingDongDitch" / "browser-profiles").resolve()


def validate_profile_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name) or name in {".", ".."}:
        raise AuthenticationError(
            "profile name must be 1-64 ASCII letters, digits, '.', '_' or '-' and start with a letter or digit",
            kind=AuthenticationFailureKind.INVALID_PROFILE_NAME,
            recovery="Choose a simple name such as 'work' or 'test-1'.",
        )
    if name in _RESERVED_PROFILE_NAMES:
        raise AuthenticationError(f"profile name '{name}' is reserved", kind=AuthenticationFailureKind.INVALID_PROFILE_NAME, recovery="Choose a different profile name.")
    return name


@dataclass(frozen=True)
class ProfileInfo:
    name: str
    path: Path
    created_at: str


class ProfileManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or profile_root()).resolve()

    def path_for(self, name: str) -> Path:
        name = validate_profile_name(name)
        candidate = (self.root / name).resolve()
        if candidate.parent != self.root:
            raise AuthenticationError("profile path escapes profile root", kind=AuthenticationFailureKind.INVALID_PROFILE_NAME)
        return candidate

    def _read(self, name: str) -> ProfileInfo:
        path = self.path_for(name)
        return self._read_path(path)

    def _read_path(self, path: Path) -> ProfileInfo:
        """Read one enumerated profile without validating a caller-supplied name."""
        path = path.resolve()
        if path.parent != self.root:
            raise AuthenticationError(
                "enumerated profile path escapes profile root",
                kind=AuthenticationFailureKind.PROFILE_CORRUPT,
            )
        name = path.name
        manifest = path / "profile.json"
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            kind = AuthenticationFailureKind.PROFILE_CORRUPT if path.exists() else AuthenticationFailureKind.PROFILE_NOT_FOUND
            raise AuthenticationError(f"profile '{name}' is {'missing metadata' if path.exists() else 'not found'}", kind=kind, recovery="Recreate or remove the profile.") from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthenticationError(f"profile '{name}' metadata is corrupt", kind=AuthenticationFailureKind.PROFILE_CORRUPT, recovery="Remove and recreate the profile.") from exc
        if raw.get("schema_version") != _SCHEMA or raw.get("name") != name or not isinstance(raw.get("created_at"), str):
            raise AuthenticationError(f"profile '{name}' metadata is invalid", kind=AuthenticationFailureKind.PROFILE_CORRUPT, recovery="Remove and recreate the profile.")
        return ProfileInfo(name, path, raw["created_at"])

    def create(self, name: str) -> ProfileInfo:
        path = self.path_for(name)
        self.root.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise AuthenticationError(f"profile '{name}' already exists", kind=AuthenticationFailureKind.PROFILE_EXISTS)
        created = datetime.now(timezone.utc).isoformat()
        try:
            path.mkdir(mode=0o700)
            (path / "browser-data").mkdir(mode=0o700)
            self._atomic_json(path / "profile.json", {"schema_version": _SCHEMA, "name": name, "created_at": created})
        except FileExistsError as exc:
            raise AuthenticationError(f"profile '{name}' already exists or is being created", kind=AuthenticationFailureKind.PROFILE_EXISTS, recovery="Choose another name or retry after the other process finishes.") from exc
        except Exception:
            shutil.rmtree(path, ignore_errors=True)
            raise
        return ProfileInfo(name, path, created)

    def list(self) -> list[ProfileInfo]:
        if not self.root.exists():
            return []
        paths = (
            path
            for path in sorted(self.root.iterdir(), key=lambda item: item.name)
            if path.is_dir()
            and not path.name.startswith(".")
            and path.name not in _RESERVED_PROFILE_NAMES
        )
        return [self._read_path(path) for path in paths]

    def require(self, name: str) -> ProfileInfo:
        return self._read(name)

    def acquire(self, name: str) -> FileLease:
        info = self.require(name)
        try:
            return acquire_file_lease(self.root / ".locks" / f"{name}.lock")
        except LeaseUnavailableError as exc:
            raise AuthenticationError(f"profile '{name}' is already in use", kind=AuthenticationFailureKind.PROFILE_IN_USE, recovery="Wait for the other DingDongDitch process to finish.") from exc

    def remove(self, name: str) -> None:
        info = self.require(name)
        lease = self.acquire(name)
        try:
            shutil.rmtree(info.path)
        except OSError as exc:
            raise AuthenticationError(f"could not remove profile '{name}'", kind=AuthenticationFailureKind.SESSION_IO_ERROR) from exc
        finally:
            lease.close()

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
