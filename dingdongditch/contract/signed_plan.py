"""Trusted, exact-plan authorization using standard Ed25519 signatures.

This module deliberately separates three facts that are often accidentally
collapsed: hashing the canonical plan, a signature over an authorization
statement, and host configuration of trusted signing identities.  A valid
signature is never an authority grant by itself.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from dingdongditch.contract.authority import canonical_json_bytes


SIGNED_PLAN_VERSION = "1.0"
SIGNED_PLAN_ALGORITHM = "ed25519"
_MAX_LIFETIME_MS = 24 * 60 * 60 * 1000
_MAX_EXECUTIONS = 1024
_MAX_TRUSTED_SIGNERS = 128
_MAX_REPLAY_ENTRIES = 4096


class SignedPlanError(ValueError):
    """A bounded, secret-safe signed-plan validation failure."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise SignedPlanError("signature encoding is invalid")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise SignedPlanError("signature encoding is invalid") from exc


def _token(name: str, value: str | None, *, required: bool = False, limit: int = 160) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not value or len(value) > limit or any(char.isspace() for char in value):
        raise SignedPlanError(f"{name} is invalid")


def _hash_hex(name: str, value: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise SignedPlanError(f"{name} is invalid")
    try:
        int(value, 16)
    except ValueError as exc:
        raise SignedPlanError(f"{name} is invalid") from exc


def canonical_plan_hash(document: Any) -> str:
    """Hash the normative PlanDocument representation, never a Python repr.

    The import is intentionally local: machine-contract serialization depends
    on contract modules, while this helper is also useful to hosts that do not
    import the public facade during process startup.
    """
    from dingdongditch.contract.plan import ExecutionPlan
    from dingdongditch.machine_contract import serialize_plan_document

    plan = getattr(document, "plan", document)
    if not isinstance(plan, ExecutionPlan):
        raise SignedPlanError("plan document is invalid")
    try:
        plan.validate()
        serialized = serialize_plan_document(document)
    except Exception as exc:
        raise SignedPlanError("plan document is invalid") from exc
    return hashlib.sha256(canonical_json_bytes(serialized)).hexdigest()


@dataclass(frozen=True)
class SignedPlanAuthority:
    """Public authorization statement for one exact canonical plan.

    This is a signed wrapper around a PlanDocument, not a field in it.  Keeping
    it separate prevents a planner from changing the object that is hashed by
    adding an ostensibly harmless authorization field.
    """

    version: str
    algorithm: str
    plan_hash: str
    contract_version: str
    authority_envelope_hash: str
    signer_id: str
    issued_at_ms: int
    expires_at_ms: int
    nonce: str
    signature: str
    session_scope: str | None = None
    agent_identity_id: str | None = None
    allowed_execution_count: int = 1
    policy_version: str | None = None

    def validate(self) -> None:
        if self.version != SIGNED_PLAN_VERSION:
            raise SignedPlanError("signed plan version is unsupported")
        if self.algorithm != SIGNED_PLAN_ALGORITHM:
            raise SignedPlanError("signed plan algorithm is unsupported")
        _hash_hex("plan_hash", self.plan_hash)
        _hash_hex("authority_envelope_hash", self.authority_envelope_hash)
        _token("contract_version", self.contract_version, required=True, limit=48)
        _token("signer_id", self.signer_id, required=True)
        _token("nonce", self.nonce, required=True)
        _token("session_scope", self.session_scope)
        _token("agent_identity_id", self.agent_identity_id)
        _token("policy_version", self.policy_version, limit=96)
        if not isinstance(self.issued_at_ms, int) or isinstance(self.issued_at_ms, bool) or self.issued_at_ms < 0:
            raise SignedPlanError("signed plan issuance time is invalid")
        if not isinstance(self.expires_at_ms, int) or isinstance(self.expires_at_ms, bool):
            raise SignedPlanError("signed plan expiration time is invalid")
        if self.expires_at_ms <= self.issued_at_ms or self.expires_at_ms - self.issued_at_ms > _MAX_LIFETIME_MS:
            raise SignedPlanError("signed plan lifetime is invalid")
        if (
            not isinstance(self.allowed_execution_count, int)
            or isinstance(self.allowed_execution_count, bool)
            or not 1 <= self.allowed_execution_count <= _MAX_EXECUTIONS
        ):
            raise SignedPlanError("allowed execution count is invalid")
        if len(_b64decode(self.signature)) != 64:
            raise SignedPlanError("signature is invalid")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "algorithm": self.algorithm,
            "plan_hash": self.plan_hash,
            "contract_version": self.contract_version,
            "authority_envelope_hash": self.authority_envelope_hash,
            "signer_id": self.signer_id,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "nonce": self.nonce,
            "session_scope": self.session_scope,
            "agent_identity_id": self.agent_identity_id,
            "allowed_execution_count": self.allowed_execution_count,
            "policy_version": self.policy_version,
        }

    def signing_bytes(self) -> bytes:
        self.validate()
        # Ed25519 does not provide a context parameter here.  Prefixing a
        # fixed protocol label prevents these bytes being valid as an identity
        # assertion or execution attestation in another DingDongDitch domain.
        return b"DINGDONGDITCH:SIGNED_PLAN_AUTHORITY:v1\x00" + canonical_json_bytes(self.unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature": self.signature}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignedPlanAuthority":
        allowed = {
            "version", "algorithm", "plan_hash", "contract_version",
            "authority_envelope_hash", "signer_id", "issued_at_ms",
            "expires_at_ms", "nonce", "signature", "session_scope",
            "agent_identity_id", "allowed_execution_count", "policy_version",
        }
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise SignedPlanError("signed plan contains unknown fields")
        required = {
            "version", "algorithm", "plan_hash", "contract_version",
            "authority_envelope_hash", "signer_id", "issued_at_ms",
            "expires_at_ms", "nonce", "signature",
        }
        if any(key not in value for key in required):
            raise SignedPlanError("signed plan is missing a required field")
        result = cls(
            version=value["version"], algorithm=value["algorithm"], plan_hash=value["plan_hash"],
            contract_version=value["contract_version"], authority_envelope_hash=value["authority_envelope_hash"],
            signer_id=value["signer_id"], issued_at_ms=value["issued_at_ms"], expires_at_ms=value["expires_at_ms"],
            nonce=value["nonce"], signature=value["signature"], session_scope=value.get("session_scope"),
            agent_identity_id=value.get("agent_identity_id"),
            allowed_execution_count=value.get("allowed_execution_count", 1),
            policy_version=value.get("policy_version"),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class SignedPlanVerification:
    valid: bool
    reason: str | None
    signer_id: str | None = None
    plan_hash: str | None = None
    replay_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "signer_id": self.signer_id,
            "plan_hash": self.plan_hash,
            "replay_count": self.replay_count,
        }


class TrustedPlanSigner:
    """Trusted-host-only Ed25519 signer; its private key is never serialized."""

    def __init__(self, signer_id: str, private_key: Ed25519PrivateKey | bytes) -> None:
        _token("signer_id", signer_id, required=True)
        if isinstance(private_key, bytes):
            if len(private_key) != 32:
                raise SignedPlanError("Ed25519 private key bytes are invalid")
            private_key = Ed25519PrivateKey.from_private_bytes(private_key)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError("private_key must be Ed25519PrivateKey or 32 private bytes")
        self.signer_id = signer_id
        self._private_key = private_key

    @classmethod
    def generate(cls, signer_id: str) -> "TrustedPlanSigner":
        return cls(signer_id, Ed25519PrivateKey.generate())

    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )

    def public_metadata(self) -> dict[str, str]:
        public = self.public_key_bytes()
        return {
            "signer_id": self.signer_id,
            "algorithm": SIGNED_PLAN_ALGORITHM,
            "public_key_fingerprint": hashlib.sha256(public).hexdigest(),
        }

    def sign(
        self,
        document: Any,
        *,
        authority_envelope_hash: str,
        expires_at_ms: int,
        issued_at_ms: int | None = None,
        nonce: str | None = None,
        session_scope: str | None = None,
        agent_identity_id: str | None = None,
        allowed_execution_count: int = 1,
        policy_version: str | None = None,
    ) -> SignedPlanAuthority:
        from dingdongditch.machine_contract import MACHINE_CONTRACT_VERSION

        issued = _now_ms() if issued_at_ms is None else issued_at_ms
        statement = SignedPlanAuthority(
            version=SIGNED_PLAN_VERSION,
            algorithm=SIGNED_PLAN_ALGORITHM,
            plan_hash=canonical_plan_hash(document),
            contract_version=MACHINE_CONTRACT_VERSION,
            authority_envelope_hash=authority_envelope_hash,
            signer_id=self.signer_id,
            issued_at_ms=issued,
            expires_at_ms=expires_at_ms,
            nonce=nonce or uuid.uuid4().hex,
            signature="A" * 86,  # placeholder solely to validate unsigned fields
            session_scope=session_scope,
            agent_identity_id=agent_identity_id,
            allowed_execution_count=allowed_execution_count,
            policy_version=policy_version,
        )
        signature = _b64encode(self._private_key.sign(statement.signing_bytes()))
        signed = SignedPlanAuthority(**{**statement.to_dict(), "signature": signature})
        signed.validate()
        return signed


class TrustedPlanVerifier:
    """Host-configured signer trust plus bounded nonce replay accounting."""

    def __init__(self, trusted_signers: Mapping[str, Ed25519PublicKey | bytes]) -> None:
        if len(trusted_signers) > _MAX_TRUSTED_SIGNERS:
            raise SignedPlanError("too many trusted signing identities")
        self._trusted: dict[str, Ed25519PublicKey] = {}
        self._uses: dict[tuple[str, str], tuple[int, int]] = {}
        self._revoked: set[str] = set()
        for signer_id, public in trusted_signers.items():
            _token("signer_id", signer_id, required=True)
            if isinstance(public, bytes):
                if len(public) != 32:
                    raise SignedPlanError("Ed25519 public key bytes are invalid")
                public = Ed25519PublicKey.from_public_bytes(public)
            if not isinstance(public, Ed25519PublicKey):
                raise TypeError("trusted signer values must be Ed25519 public keys or 32 public bytes")
            self._trusted[signer_id] = public

    def revoke_signer(self, signer_id: str) -> None:
        """Trusted-host revocation; it never comes from the planner contract."""
        _token("signer_id", signer_id, required=True)
        if signer_id not in self._trusted:
            raise SignedPlanError("signer is not trusted")
        self._revoked.add(signer_id)

    def replace_signer(self, signer_id: str, public: Ed25519PublicKey | bytes) -> None:
        """Trusted-host rotation that preserves nonce replay accounting."""
        _token("signer_id", signer_id, required=True)
        if isinstance(public, bytes):
            if len(public) != 32:
                raise SignedPlanError("Ed25519 public key bytes are invalid")
            public = Ed25519PublicKey.from_public_bytes(public)
        if not isinstance(public, Ed25519PublicKey):
            raise TypeError("trusted signer value must be an Ed25519 public key or 32 public bytes")
        self._trusted[signer_id] = public
        self._revoked.discard(signer_id)

    def verify(
        self,
        authority: SignedPlanAuthority,
        document: Any,
        *,
        authority_envelope_hash: str,
        session_scope: str | None = None,
        agent_identity_id: str | None = None,
        now_ms: int | None = None,
        consume: bool = False,
    ) -> SignedPlanVerification:
        try:
            authority.validate()
        except (TypeError, ValueError) as exc:
            return SignedPlanVerification(False, "malformed_signed_plan")
        from dingdongditch.machine_contract import MACHINE_CONTRACT_VERSION
        if authority.contract_version != MACHINE_CONTRACT_VERSION:
            return SignedPlanVerification(False, "contract_version_mismatch", authority.signer_id, authority.plan_hash)
        if authority.signer_id not in self._trusted:
            return SignedPlanVerification(False, "untrusted_signer", authority.signer_id, authority.plan_hash)
        if authority.signer_id in self._revoked:
            return SignedPlanVerification(False, "revoked_signer", authority.signer_id, authority.plan_hash)
        try:
            observed_plan_hash = canonical_plan_hash(document)
        except SignedPlanError:
            return SignedPlanVerification(False, "plan_invalid", authority.signer_id, authority.plan_hash)
        if authority.plan_hash != observed_plan_hash:
            return SignedPlanVerification(False, "plan_hash_mismatch", authority.signer_id, authority.plan_hash)
        if authority.authority_envelope_hash != authority_envelope_hash:
            return SignedPlanVerification(False, "authority_hash_mismatch", authority.signer_id, authority.plan_hash)
        current = _now_ms() if now_ms is None else now_ms
        if not isinstance(current, int) or isinstance(current, bool):
            return SignedPlanVerification(False, "verification_time_invalid", authority.signer_id, authority.plan_hash)
        if authority.issued_at_ms > current:
            return SignedPlanVerification(False, "not_yet_valid", authority.signer_id, authority.plan_hash)
        if current >= authority.expires_at_ms:
            return SignedPlanVerification(False, "expired", authority.signer_id, authority.plan_hash)
        if authority.session_scope is not None and authority.session_scope != session_scope:
            return SignedPlanVerification(False, "session_scope_mismatch", authority.signer_id, authority.plan_hash)
        if authority.agent_identity_id is not None and authority.agent_identity_id != agent_identity_id:
            return SignedPlanVerification(False, "identity_scope_mismatch", authority.signer_id, authority.plan_hash)
        try:
            self._trusted[authority.signer_id].verify(_b64decode(authority.signature), authority.signing_bytes())
        except (InvalidSignature, ValueError, TypeError):
            return SignedPlanVerification(False, "signature_invalid", authority.signer_id, authority.plan_hash)
        for cached_key, (_, expiry) in tuple(self._uses.items()):
            if expiry <= current:
                del self._uses[cached_key]
        key = (authority.signer_id, authority.nonce)
        entry = self._uses.get(key)
        uses = entry[0] if entry is not None else 0
        if uses >= authority.allowed_execution_count:
            return SignedPlanVerification(False, "replay_limit_exhausted", authority.signer_id, authority.plan_hash, uses)
        if consume:
            if entry is None and len(self._uses) >= _MAX_REPLAY_ENTRIES:
                return SignedPlanVerification(False, "replay_cache_full", authority.signer_id, authority.plan_hash, uses)
            self._uses[key] = (uses + 1, authority.expires_at_ms)
            uses += 1
        return SignedPlanVerification(True, None, authority.signer_id, authority.plan_hash, uses)


def public_signed_plan_reference(authority: SignedPlanAuthority) -> dict[str, str | int | None]:
    """Bounded receipt-safe reference; the signature stays out of core receipts."""
    authority.validate()
    return {
        "status": "verified",
        "plan_hash": authority.plan_hash,
        "signer_id": authority.signer_id,
        "nonce_id": hashlib.sha256(authority.nonce.encode("utf-8")).hexdigest()[:24],
        "expires_at_ms": authority.expires_at_ms,
    }
