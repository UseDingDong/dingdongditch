"""Cryptographic execution statements, distinct from receipt chaining.

Receipt chaining is tamper-evident relative to a retained checkpoint.  This
module signs a bounded statement *about* that material.  An in-process signer
is explicitly host-attested; independent assurance requires an external
transport/key boundary and is never inferred from a signature alone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from dingdongditch.contract.authority import canonical_json_bytes
from dingdongditch.contract.receipt_chain import ReceiptChainCheckpoint, verify_receipt_chain_against_checkpoint


ATTESTATION_VERSION = "1.0"
ATTESTATION_ALGORITHM = "ed25519"


class AssuranceLevel(str, Enum):
    HOST_ATTESTED = "host_attested"
    INDEPENDENT_ATTESTER = "independent_attester"


class AttestationError(ValueError):
    pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str, length: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise AttestationError("attestation key or signature is invalid")
    try:
        result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise AttestationError("attestation key or signature is invalid") from exc
    if len(result) != length:
        raise AttestationError("attestation key or signature is invalid")
    return result


def _token(name: str, value: str | None, *, required: bool = False, limit: int = 192) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not value or len(value) > limit or any(char.isspace() for char in value):
        raise AttestationError(f"{name} is invalid")


def _hash(name: str, value: str | None, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or len(value) != 64:
        raise AttestationError(f"{name} is invalid")
    try:
        int(value, 16)
    except ValueError as exc:
        raise AttestationError(f"{name} is invalid") from exc


@dataclass(frozen=True)
class ExecutionAttestationStatement:
    version: str
    plan_hash: str | None
    signed_plan_reference: dict[str, Any] | None
    session_id: str
    identity_reference: dict[str, Any] | None
    authority_policy_hash: str | None
    checkpoint: ReceiptChainCheckpoint
    receipt_chain_head: str | None
    receipt_count: int
    quorum_verdict: str | None
    artifact_manifest_hash: str | None
    runtime_version: str
    contract_version: str
    browser: dict[str, Any] | None
    speculation_reference: dict[str, Any] | None
    issued_at_ms: int
    expires_at_ms: int
    nonce: str
    attester_id: str
    assurance_level: AssuranceLevel

    def validate(self) -> None:
        if self.version != ATTESTATION_VERSION:
            raise AttestationError("attestation version is unsupported")
        _hash("plan hash", self.plan_hash, nullable=True)
        _token("session id", self.session_id, required=True)
        _hash("authority policy hash", self.authority_policy_hash, nullable=True)
        self.checkpoint.validate()
        if self.checkpoint.session_id != self.session_id:
            raise AttestationError("checkpoint session does not match attestation session")
        _hash("receipt chain head", self.receipt_chain_head, nullable=True)
        if not isinstance(self.receipt_count, int) or isinstance(self.receipt_count, bool) or self.receipt_count < self.checkpoint.chain_length:
            raise AttestationError("attestation receipt count is invalid")
        if self.receipt_count == 0 and self.receipt_chain_head is not None:
            raise AttestationError("empty attestation cannot have receipt chain head")
        if self.receipt_count > 0 and self.receipt_chain_head is None:
            raise AttestationError("non-empty attestation requires receipt chain head")
        if self.receipt_count == self.checkpoint.chain_length and self.receipt_chain_head != self.checkpoint.chain_head_hash:
            raise AttestationError("checkpoint must match an equally long attested chain")
        _hash("artifact manifest hash", self.artifact_manifest_hash, nullable=True)
        _token("runtime version", self.runtime_version, required=True, limit=64)
        _token("contract version", self.contract_version, required=True, limit=64)
        _token("nonce", self.nonce, required=True)
        _token("attester id", self.attester_id, required=True)
        if not isinstance(self.assurance_level, AssuranceLevel):
            raise AttestationError("assurance level is invalid")
        if not isinstance(self.issued_at_ms, int) or isinstance(self.issued_at_ms, bool) or not isinstance(self.expires_at_ms, int) or isinstance(self.expires_at_ms, bool):
            raise AttestationError("attestation times are invalid")
        if self.expires_at_ms <= self.issued_at_ms or self.expires_at_ms - self.issued_at_ms > 24 * 60 * 60 * 1000:
            raise AttestationError("attestation lifetime is invalid")
        for name, value, maximum in (
            ("signed plan reference", self.signed_plan_reference, 8),
            ("identity reference", self.identity_reference, 8),
            ("browser metadata", self.browser, 8),
            ("speculation reference", self.speculation_reference, 4),
        ):
            if value is not None:
                if not isinstance(value, dict) or len(value) > maximum:
                    raise AttestationError(f"{name} is invalid")
                if any(
                    not isinstance(key, str) or len(key) > 96
                    or not isinstance(item, (str, int, bool, type(None)))
                    or (isinstance(item, str) and len(item) > 256)
                    for key, item in value.items()
                ):
                    raise AttestationError(f"{name} is invalid")
        if self.signed_plan_reference is not None:
            plan_reference_hash = self.signed_plan_reference.get("plan_hash")
            if self.plan_hash is None or plan_reference_hash != self.plan_hash:
                raise AttestationError("signed plan reference does not bind plan hash")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "version": self.version, "plan_hash": self.plan_hash,
            "signed_plan_reference": self.signed_plan_reference, "session_id": self.session_id,
            "identity_reference": self.identity_reference, "authority_policy_hash": self.authority_policy_hash,
            "checkpoint": self.checkpoint.to_dict(), "receipt_chain_head": self.receipt_chain_head,
            "receipt_count": self.receipt_count, "quorum_verdict": self.quorum_verdict,
            "artifact_manifest_hash": self.artifact_manifest_hash, "runtime_version": self.runtime_version,
            "contract_version": self.contract_version, "browser": self.browser,
            "speculation_reference": self.speculation_reference,
            "issued_at_ms": self.issued_at_ms, "expires_at_ms": self.expires_at_ms,
            "nonce": self.nonce, "attester_id": self.attester_id,
            "assurance_level": self.assurance_level.value,
        }

    def canonical_bytes(self) -> bytes:
        return b"DINGDONGDITCH:EXECUTION_ATTESTATION:v1\x00" + canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionAttestationStatement":
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise AttestationError("attestation statement contains unknown fields")
        required = allowed
        if any(key not in value for key in required):
            raise AttestationError("attestation statement is missing a required field")
        checkpoint_value = value["checkpoint"]
        if not isinstance(checkpoint_value, Mapping):
            raise AttestationError("attestation checkpoint is invalid")
        try:
            checkpoint = ReceiptChainCheckpoint(
                session_id=checkpoint_value["session_id"], chain_length=checkpoint_value["chain_length"],
                chain_head_hash=checkpoint_value["chain_head_hash"], timestamp_ms=checkpoint_value["timestamp_ms"],
                chain_version=checkpoint_value.get("chain_version", "3"), runtime_version=checkpoint_value.get("runtime_version"),
            )
            result = cls(
                version=value["version"], plan_hash=value["plan_hash"], signed_plan_reference=value["signed_plan_reference"],
                session_id=value["session_id"], identity_reference=value["identity_reference"], authority_policy_hash=value["authority_policy_hash"],
                checkpoint=checkpoint, receipt_chain_head=value["receipt_chain_head"], receipt_count=value["receipt_count"],
                quorum_verdict=value["quorum_verdict"], artifact_manifest_hash=value["artifact_manifest_hash"],
                runtime_version=value["runtime_version"], contract_version=value["contract_version"], browser=value["browser"],
                speculation_reference=value["speculation_reference"],
                issued_at_ms=value["issued_at_ms"], expires_at_ms=value["expires_at_ms"], nonce=value["nonce"],
                attester_id=value["attester_id"], assurance_level=AssuranceLevel(value["assurance_level"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AttestationError("attestation statement is invalid") from exc
        result.validate()
        return result


@dataclass(frozen=True)
class ExecutionAttestation:
    statement: ExecutionAttestationStatement
    algorithm: str
    signature: str

    def validate(self) -> None:
        self.statement.validate()
        if self.algorithm != ATTESTATION_ALGORITHM:
            raise AttestationError("attestation algorithm is unsupported")
        _decode(self.signature, 64)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"statement": self.statement.to_dict(), "algorithm": self.algorithm, "signature": self.signature}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionAttestation":
        if not isinstance(value, Mapping) or set(value) != {"statement", "algorithm", "signature"}:
            raise AttestationError("attestation contains unknown or missing fields")
        result = cls(ExecutionAttestationStatement.from_dict(value["statement"]), value["algorithm"], value["signature"])
        result.validate()
        return result


class Attester(Protocol):
    attester_id: str
    assurance_level: AssuranceLevel

    def sign(self, statement: ExecutionAttestationStatement) -> ExecutionAttestation: ...


class HostEd25519Attester:
    """Host-attested signer. Its same-process key is expressly not independent."""

    assurance_level = AssuranceLevel.HOST_ATTESTED

    def __init__(self, attester_id: str, private_key: Ed25519PrivateKey | bytes) -> None:
        _token("attester id", attester_id, required=True)
        if isinstance(private_key, bytes):
            if len(private_key) != 32:
                raise AttestationError("attester private key is invalid")
            private_key = Ed25519PrivateKey.from_private_bytes(private_key)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError("attester private key must be Ed25519")
        self.attester_id = attester_id
        self._private_key = private_key

    @classmethod
    def generate(cls, attester_id: str) -> "HostEd25519Attester":
        return cls(attester_id, Ed25519PrivateKey.generate())

    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def sign(self, statement: ExecutionAttestationStatement) -> ExecutionAttestation:
        if statement.attester_id != self.attester_id or statement.assurance_level is not self.assurance_level:
            raise AttestationError("statement attester binding is invalid")
        return ExecutionAttestation(statement, ATTESTATION_ALGORITHM, _b64(self._private_key.sign(statement.canonical_bytes())))


class AttesterTransport(Protocol):
    """Transport-neutral external signing boundary; it returns signature bytes."""

    def sign_statement(self, canonical_statement: bytes) -> bytes: ...


class ExternalAttesterAdapter:
    """Independent label only for an externally owned signing transport/key."""

    assurance_level = AssuranceLevel.INDEPENDENT_ATTESTER

    def __init__(self, attester_id: str, transport: AttesterTransport) -> None:
        _token("attester id", attester_id, required=True)
        self.attester_id = attester_id
        self._transport = transport

    def sign(self, statement: ExecutionAttestationStatement) -> ExecutionAttestation:
        if statement.attester_id != self.attester_id or statement.assurance_level is not self.assurance_level:
            raise AttestationError("statement attester binding is invalid")
        signature = self._transport.sign_statement(statement.canonical_bytes())
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise AttestationError("external attester returned an invalid signature")
        return ExecutionAttestation(statement, ATTESTATION_ALGORITHM, _b64(signature))


class AttesterTrustRegistry:
    def __init__(self, trusted_attesters: Mapping[str, tuple[Ed25519PublicKey | bytes, AssuranceLevel]]) -> None:
        self._trusted: dict[str, tuple[Ed25519PublicKey, AssuranceLevel]] = {}
        self._consumed_challenges: dict[tuple[str, str], int] = {}
        for identifier, pair in trusted_attesters.items():
            _token("attester id", identifier, required=True)
            public, level = pair
            if isinstance(public, bytes):
                if len(public) != 32:
                    raise AttestationError("attester public key is invalid")
                public = Ed25519PublicKey.from_public_bytes(public)
            if not isinstance(public, Ed25519PublicKey) or not isinstance(level, AssuranceLevel):
                raise AttestationError("trusted attester metadata is invalid")
            self._trusted[identifier] = (public, level)

    def verify(
        self, attestation: ExecutionAttestation, *, receipts: tuple[Any, ...] | None = None,
        expected_nonce: str | None = None, now_ms: int | None = None,
        expected_plan_hash: str | None = None, expected_session_id: str | None = None,
        expected_identity_reference: Mapping[str, Any] | None = None,
        expected_policy_hash: str | None = None, expected_speculation_reference: Mapping[str, Any] | None = None,
        expected_quorum_verdict: str | None = None, expected_runtime_version: str | None = None,
        expected_contract_version: str | None = None, expected_browser: Mapping[str, Any] | None = None,
        consume_challenge: bool = False,
    ) -> tuple[bool, str | None]:
        try:
            attestation.validate()
        except (TypeError, ValueError):
            return False, "malformed_attestation"
        statement = attestation.statement
        trusted = self._trusted.get(statement.attester_id)
        if trusted is None:
            return False, "untrusted_attester"
        public, expected_level = trusted
        if statement.assurance_level is not expected_level:
            return False, "assurance_level_mismatch"
        current = _now_ms() if now_ms is None else now_ms
        if statement.issued_at_ms > current or current >= statement.expires_at_ms:
            return False, "attestation_expired_or_not_yet_valid"
        if expected_nonce is not None and statement.nonce != expected_nonce:
            return False, "challenge_mismatch"
        if expected_plan_hash is not None and not hmac.compare_digest(statement.plan_hash or "", expected_plan_hash):
            return False, "plan_hash_mismatch"
        if expected_session_id is not None and not hmac.compare_digest(statement.session_id, expected_session_id):
            return False, "session_mismatch"
        if expected_policy_hash is not None and not hmac.compare_digest(statement.authority_policy_hash or "", expected_policy_hash):
            return False, "authority_policy_mismatch"
        if expected_identity_reference is not None and canonical_json_bytes(statement.identity_reference) != canonical_json_bytes(dict(expected_identity_reference)):
            return False, "identity_reference_mismatch"
        if expected_speculation_reference is not None and canonical_json_bytes(statement.speculation_reference) != canonical_json_bytes(dict(expected_speculation_reference)):
            return False, "speculation_reference_mismatch"
        if expected_quorum_verdict is not None and statement.quorum_verdict != expected_quorum_verdict:
            return False, "quorum_verdict_mismatch"
        if expected_runtime_version is not None and statement.runtime_version != expected_runtime_version:
            return False, "runtime_version_mismatch"
        if expected_contract_version is None:
            from dingdongditch.machine_contract import MACHINE_CONTRACT_VERSION
            expected_contract_version = MACHINE_CONTRACT_VERSION
        if statement.contract_version != expected_contract_version:
            return False, "contract_version_mismatch"
        if expected_browser is not None and canonical_json_bytes(statement.browser) != canonical_json_bytes(dict(expected_browser)):
            return False, "browser_metadata_mismatch"
        try:
            public.verify(_decode(attestation.signature, 64), statement.canonical_bytes())
        except (InvalidSignature, ValueError, TypeError):
            return False, "signature_invalid"
        if receipts is not None:
            checked = verify_receipt_chain_against_checkpoint(receipts, statement.checkpoint)
            if not checked.valid:
                return False, "receipt_checkpoint_mismatch"
            if len(receipts) != statement.receipt_count or checked.head != statement.receipt_chain_head:
                return False, "receipt_chain_head_or_count_mismatch"
        if consume_challenge:
            # Offline verification may safely be repeated; challenge-response
            # consumers opt into one-shot acceptance.  Bound retained state by
            # expiry and a hard ceiling to resist nonce-table exhaustion.
            for key, expiry in tuple(self._consumed_challenges.items()):
                if expiry <= current:
                    del self._consumed_challenges[key]
            key = (statement.attester_id, statement.nonce)
            if key in self._consumed_challenges:
                return False, "challenge_replayed"
            if len(self._consumed_challenges) >= 4096:
                return False, "challenge_replay_cache_full"
            self._consumed_challenges[key] = statement.expires_at_ms
        return True, None


def make_execution_attestation_statement(
    *, plan_hash: str | None, signed_plan_reference: dict[str, Any] | None, session_id: str,
    identity_reference: dict[str, Any] | None, authority_policy_hash: str | None,
    checkpoint: ReceiptChainCheckpoint, receipt_chain_head: str | None, receipt_count: int,
    quorum_verdict: str | None, artifact_manifest_hash: str | None, runtime_version: str,
    contract_version: str, browser: dict[str, Any] | None, attester_id: str,
    assurance_level: AssuranceLevel, expires_at_ms: int, issued_at_ms: int | None = None,
    nonce: str | None = None, speculation_reference: dict[str, Any] | None = None,
) -> ExecutionAttestationStatement:
    return ExecutionAttestationStatement(
        ATTESTATION_VERSION, plan_hash, signed_plan_reference, session_id, identity_reference,
        authority_policy_hash, checkpoint, receipt_chain_head, receipt_count, quorum_verdict,
        artifact_manifest_hash, runtime_version, contract_version, browser, speculation_reference,
        _now_ms() if issued_at_ms is None else issued_at_ms, expires_at_ms,
        nonce or uuid.uuid4().hex, attester_id, assurance_level,
    )
