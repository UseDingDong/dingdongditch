"""Portable user/host-owned execution identities.

An identity says *who/what is acting*.  It is neither browser authority nor a
control lease, and it deliberately makes no reference to a model vendor or
reasoning engine.  The trusted host decides whether an identity is accepted.
"""

from __future__ import annotations

import base64
import hashlib
import time
import uuid
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from dingdongditch.contract.authority import canonical_json_bytes


IDENTITY_VERSION = "1.0"
IDENTITY_ALGORITHM = "ed25519"
_MAX_ASSERTION_MS = 24 * 60 * 60 * 1000
_MAX_IDENTITIES = 1024


class IdentityStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class IdentityError(ValueError):
    pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _token(name: str, value: str | None, *, required: bool = False, limit: int = 160) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not value or len(value) > limit or any(char.isspace() for char in value):
        raise IdentityError(f"{name} is invalid")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str, *, length: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise IdentityError("identity key or signature is invalid")
    try:
        result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise IdentityError("identity key or signature is invalid") from exc
    if len(result) != length:
        raise IdentityError("identity key or signature is invalid")
    return result


@dataclass(frozen=True)
class IdentityKey:
    key_id: str
    public_key: str
    algorithm: str = IDENTITY_ALGORITHM

    def validate(self) -> None:
        _token("identity key id", self.key_id, required=True)
        if self.algorithm != IDENTITY_ALGORITHM:
            raise IdentityError("identity key algorithm is unsupported")
        _decode(self.public_key, length=32)

    @property
    def fingerprint(self) -> str:
        self.validate()
        return hashlib.sha256(_decode(self.public_key, length=32)).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return {"key_id": self.key_id, "public_key": self.public_key, "algorithm": self.algorithm, "fingerprint": self.fingerprint}


@dataclass(frozen=True)
class AgentIdentity:
    """A portable public identity descriptor owned in the user/host domain."""

    identity_id: str
    owner_id: str
    issuer_id: str
    created_at_ms: int
    version: int
    keys: tuple[IdentityKey, ...]
    capability_references: tuple[str, ...] = ()
    status: IdentityStatus = IdentityStatus.ACTIVE

    def validate(self) -> None:
        _token("identity id", self.identity_id, required=True)
        _token("identity owner", self.owner_id, required=True)
        _token("identity issuer", self.issuer_id, required=True)
        if not isinstance(self.created_at_ms, int) or isinstance(self.created_at_ms, bool) or self.created_at_ms < 0:
            raise IdentityError("identity creation time is invalid")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or not 1 <= self.version <= 2**31 - 1:
            raise IdentityError("identity version is invalid")
        if not isinstance(self.status, IdentityStatus):
            raise IdentityError("identity status is invalid")
        if not self.keys or len(self.keys) > 8 or len({key.key_id for key in self.keys}) != len(self.keys):
            raise IdentityError("identity keys are invalid")
        for key in self.keys:
            if not isinstance(key, IdentityKey):
                raise IdentityError("identity keys are invalid")
            key.validate()
        if len(self.capability_references) > 32 or any(not isinstance(item, str) or not item or len(item) > 160 for item in self.capability_references):
            raise IdentityError("identity capability references are invalid")
        if len(set(self.capability_references)) != len(self.capability_references):
            raise IdentityError("identity capability references contain duplicates")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "identity_id": self.identity_id,
            "owner_id": self.owner_id,
            "issuer_id": self.issuer_id,
            "created_at_ms": self.created_at_ms,
            "version": self.version,
            "keys": [key.to_dict() for key in self.keys],
            "capability_references": list(self.capability_references),
            "status": self.status.value,
        }


@dataclass(frozen=True)
class IdentityAssertion:
    """Proof of possession for a registered identity key, bounded in time."""

    identity_id: str
    identity_version: int
    key_id: str
    issued_at_ms: int
    expires_at_ms: int
    assertion_id: str
    signature: str
    controller_scope: str | None = None
    version: str = IDENTITY_VERSION
    algorithm: str = IDENTITY_ALGORITHM

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "algorithm": self.algorithm,
            "identity_id": self.identity_id,
            "identity_version": self.identity_version,
            "key_id": self.key_id,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "assertion_id": self.assertion_id,
            "controller_scope": self.controller_scope,
        }

    def validate(self) -> None:
        if self.version != IDENTITY_VERSION or self.algorithm != IDENTITY_ALGORITHM:
            raise IdentityError("identity assertion version or algorithm is unsupported")
        _token("identity id", self.identity_id, required=True)
        _token("identity key id", self.key_id, required=True)
        _token("identity assertion id", self.assertion_id, required=True)
        _token("controller scope", self.controller_scope)
        if not isinstance(self.identity_version, int) or isinstance(self.identity_version, bool) or self.identity_version < 1:
            raise IdentityError("identity assertion version is invalid")
        if not isinstance(self.issued_at_ms, int) or isinstance(self.issued_at_ms, bool) or self.issued_at_ms < 0:
            raise IdentityError("identity assertion issue time is invalid")
        if not isinstance(self.expires_at_ms, int) or isinstance(self.expires_at_ms, bool) or self.expires_at_ms <= self.issued_at_ms or self.expires_at_ms - self.issued_at_ms > _MAX_ASSERTION_MS:
            raise IdentityError("identity assertion lifetime is invalid")
        _decode(self.signature, length=64)

    def signing_bytes(self) -> bytes:
        self.validate()
        return b"DINGDONGDITCH:IDENTITY_ASSERTION:v1\x00" + canonical_json_bytes(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature": self.signature}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IdentityAssertion":
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise IdentityError("identity assertion contains unknown fields")
        required = {"identity_id", "identity_version", "key_id", "issued_at_ms", "expires_at_ms", "assertion_id", "signature"}
        if any(key not in value for key in required):
            raise IdentityError("identity assertion is missing a required field")
        assertion = cls(
            identity_id=value["identity_id"], identity_version=value["identity_version"], key_id=value["key_id"],
            issued_at_ms=value["issued_at_ms"], expires_at_ms=value["expires_at_ms"], assertion_id=value["assertion_id"],
            signature=value["signature"], controller_scope=value.get("controller_scope"),
            version=value.get("version", IDENTITY_VERSION), algorithm=value.get("algorithm", IDENTITY_ALGORITHM),
        )
        assertion.validate()
        return assertion


class IdentitySigner:
    """Private-key holder for a user/host identity; never serializes its key."""

    def __init__(self, identity: AgentIdentity, key_id: str, private_key: Ed25519PrivateKey | bytes) -> None:
        identity.validate()
        if isinstance(private_key, bytes):
            if len(private_key) != 32:
                raise IdentityError("Ed25519 private key is invalid")
            private_key = Ed25519PrivateKey.from_private_bytes(private_key)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError("identity private key must be an Ed25519 key or 32 private bytes")
        if key_id not in {key.key_id for key in identity.keys}:
            raise IdentityError("identity key is not declared")
        public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        expected = next(key for key in identity.keys if key.key_id == key_id)
        if expected.public_key != _b64(public):
            raise IdentityError("identity private key does not match declared public key")
        self.identity = identity
        self.key_id = key_id
        self._private_key = private_key

    @classmethod
    def generate(
        cls, *, identity_id: str, owner_id: str, issuer_id: str, key_id: str = "primary", created_at_ms: int | None = None,
    ) -> "IdentitySigner":
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        identity = AgentIdentity(identity_id, owner_id, issuer_id, _now_ms() if created_at_ms is None else created_at_ms, 1, (IdentityKey(key_id, _b64(public)),))
        return cls(identity, key_id, private)

    def assert_identity(
        self, *, expires_at_ms: int, issued_at_ms: int | None = None, assertion_id: str | None = None, controller_scope: str | None = None,
    ) -> IdentityAssertion:
        issued = _now_ms() if issued_at_ms is None else issued_at_ms
        base = IdentityAssertion(
            identity_id=self.identity.identity_id, identity_version=self.identity.version, key_id=self.key_id,
            issued_at_ms=issued, expires_at_ms=expires_at_ms, assertion_id=assertion_id or uuid.uuid4().hex,
            signature="A" * 86, controller_scope=controller_scope,
        )
        signature = _b64(self._private_key.sign(base.signing_bytes()))
        result = IdentityAssertion(**{**base.to_dict(), "signature": signature})
        result.validate()
        return result


class IdentityRegistry:
    """Trusted-host identity trust/revocation store; capability refs grant nothing."""

    def __init__(self) -> None:
        self._identities: dict[str, AgentIdentity] = {}
        self._revoked: set[str] = set()
        self._lock = threading.RLock()

    def register(self, identity: AgentIdentity) -> None:
        identity.validate()
        with self._lock:
            current = self._identities.get(identity.identity_id)
            if current is None and len(self._identities) >= _MAX_IDENTITIES:
                raise IdentityError("identity registry capacity is exhausted")
            if current is not None and identity.version <= current.version:
                raise IdentityError("identity version must increase on replacement")
            self._identities[identity.identity_id] = identity
            if identity.status is IdentityStatus.REVOKED:
                self._revoked.add(identity.identity_id)

    def revoke(self, identity_id: str) -> None:
        _token("identity id", identity_id, required=True)
        with self._lock:
            if identity_id not in self._identities:
                raise IdentityError("identity is not registered")
            self._revoked.add(identity_id)

    def verify(self, assertion: IdentityAssertion, *, controller_id: str | None = None, now_ms: int | None = None) -> AgentIdentity:
        assertion.validate()
        with self._lock:
            identity = self._identities.get(assertion.identity_id)
            revoked = assertion.identity_id in self._revoked
        if identity is None or revoked or identity.status is IdentityStatus.REVOKED:
            raise IdentityError("identity is not trusted or has been revoked")
        if assertion.identity_version != identity.version:
            raise IdentityError("identity assertion is stale")
        current = _now_ms() if now_ms is None else now_ms
        if not isinstance(current, int) or isinstance(current, bool) or assertion.issued_at_ms > current or current >= assertion.expires_at_ms:
            raise IdentityError("identity assertion is not currently valid")
        if assertion.controller_scope is not None and assertion.controller_scope != controller_id:
            raise IdentityError("identity assertion controller scope does not match")
        key = next((item for item in identity.keys if item.key_id == assertion.key_id), None)
        if key is None:
            raise IdentityError("identity assertion key is not trusted")
        try:
            Ed25519PublicKey.from_public_bytes(_decode(key.public_key, length=32)).verify(_decode(assertion.signature, length=64), assertion.signing_bytes())
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise IdentityError("identity assertion signature is invalid") from exc
        return identity


def identity_reference(identity: AgentIdentity, assertion: IdentityAssertion) -> dict[str, Any]:
    """Receipt-safe attribution without public key material or private keys."""
    identity.validate()
    assertion.validate()
    return {
        "identity_id": identity.identity_id,
        "owner_id": identity.owner_id,
        "issuer_id": identity.issuer_id,
        "identity_version": identity.version,
        "assertion_id": hashlib.sha256(assertion.assertion_id.encode("utf-8")).hexdigest()[:24],
        "key_fingerprint": next(key.fingerprint for key in identity.keys if key.key_id == assertion.key_id),
    }
