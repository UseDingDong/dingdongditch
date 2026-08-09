from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import multiprocessing as mp
import time

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dingdongditch import (
    AssuranceLevel,
    AttesterTrustRegistry,
    ExecutionAttestation,
    ExternalAttesterAdapter,
    HostEd25519Attester,
    make_execution_attestation_statement,
    make_receipt_chain_checkpoint,
    parse_execution_attestation,
    chain_receipt,
)
from dingdongditch.contract.attestation import AttestationError


def _receipts(session_id: str = "session-a"):
    first = chain_receipt({"schema_version": "1.8.0", "operation_id": "one", "verdict": "VERIFIED", "action_type": "click", "browser": {"browser_session_id": "b", "context_id": "c"}}, session_id=session_id)
    second = chain_receipt({"schema_version": "1.8.0", "operation_id": "two", "verdict": "VERIFIED", "action_type": "click", "browser": {"browser_session_id": "b", "context_id": "c"}}, previous_receipt_hash=first["receipt_chain"]["receipt_hash"], session_id=session_id)
    return (first, second)


def _statement(*, attester_id: str, level: AssuranceLevel, receipts=None, nonce="challenge"):
    receipts = receipts or _receipts()
    checkpoint = make_receipt_chain_checkpoint(receipts, session_id="session-a", timestamp_ms=100)
    now = int(time.time() * 1000)
    return make_execution_attestation_statement(
        plan_hash="a" * 64, signed_plan_reference={"plan_hash": "a" * 64, "status": "verified"},
        session_id="session-a", identity_reference={"identity_id": "identity-x"}, authority_policy_hash="b" * 64,
        checkpoint=checkpoint, receipt_chain_head=receipts[-1]["receipt_chain"]["receipt_hash"], receipt_count=len(receipts),
        quorum_verdict="VERIFIED", artifact_manifest_hash=None, runtime_version="0.4.1", contract_version="1.0.0",
        browser={"engine": "chromium"}, attester_id=attester_id, assurance_level=level,
        issued_at_ms=now - 10, expires_at_ms=now + 60_000, nonce=nonce,
    )


def test_host_attestation_verifies_offline_and_detects_receipt_checkpoint_tampering():
    receipts = _receipts()
    attester = HostEd25519Attester.generate("host-attester")
    statement = _statement(attester_id="host-attester", level=AssuranceLevel.HOST_ATTESTED, receipts=receipts)
    attestation = attester.sign(statement)
    registry = AttesterTrustRegistry({"host-attester": (attester.public_key_bytes(), AssuranceLevel.HOST_ATTESTED)})
    assert registry.verify(attestation, receipts=receipts, expected_nonce="challenge") == (True, None)
    assert parse_execution_attestation(attestation.to_dict()) == attestation
    modified = list(receipts)
    modified[-1] = deepcopy(modified[-1]); modified[-1]["operation_id"] = "changed"
    assert registry.verify(attestation, receipts=tuple(modified))[1] == "receipt_checkpoint_mismatch"
    assert registry.verify(attestation, receipts=receipts[:-1])[1] == "receipt_checkpoint_mismatch"
    assert registry.verify(attestation, receipts=receipts, expected_nonce="other")[1] == "challenge_mismatch"
    assert "private" not in str(attestation.to_dict()).lower()


def test_attestation_context_and_challenge_replay_are_checked_without_browser_access():
    receipts = _receipts()
    attester = HostEd25519Attester.generate("host-attester")
    statement = _statement(attester_id="host-attester", level=AssuranceLevel.HOST_ATTESTED, receipts=receipts)
    attestation = attester.sign(statement)
    registry = AttesterTrustRegistry({"host-attester": (attester.public_key_bytes(), AssuranceLevel.HOST_ATTESTED)})
    assert registry.verify(
        attestation, receipts=receipts, expected_plan_hash="a" * 64,
        expected_session_id="session-a", expected_policy_hash="b" * 64,
        expected_quorum_verdict="VERIFIED", expected_browser={"engine": "chromium"},
        expected_contract_version="1.0.0", consume_challenge=True,
    ) == (True, None)
    assert registry.verify(attestation, receipts=receipts, consume_challenge=True)[1] == "challenge_replayed"
    assert registry.verify(attestation, receipts=receipts, expected_plan_hash="c" * 64)[1] == "plan_hash_mismatch"
    altered = replace(attestation, statement=replace(statement, browser={"engine": "firefox"}))
    assert registry.verify(altered, receipts=receipts)[1] == "signature_invalid"


def test_attestation_rejects_unbounded_reference_metadata_before_signing():
    statement = _statement(attester_id="host-attester", level=AssuranceLevel.HOST_ATTESTED)
    oversized = replace(statement, browser={str(index): "x" for index in range(9)})
    with pytest.raises(AttestationError):
        oversized.validate()


def test_untrusted_wrong_assurance_stale_and_cross_session_attestations_fail():
    receipts = _receipts()
    attester = HostEd25519Attester.generate("host-attester")
    statement = _statement(attester_id="host-attester", level=AssuranceLevel.HOST_ATTESTED, receipts=receipts)
    attestation = attester.sign(statement)
    assert AttesterTrustRegistry({}).verify(attestation, receipts=receipts)[1] == "untrusted_attester"
    wrong_level = AttesterTrustRegistry({"host-attester": (attester.public_key_bytes(), AssuranceLevel.INDEPENDENT_ATTESTER)})
    assert wrong_level.verify(attestation, receipts=receipts)[1] == "assurance_level_mismatch"
    assert AttesterTrustRegistry({"host-attester": (attester.public_key_bytes(), AssuranceLevel.HOST_ATTESTED)}).verify(attestation, receipts=receipts, now_ms=statement.expires_at_ms)[1] == "attestation_expired_or_not_yet_valid"
    assert AttesterTrustRegistry({"host-attester": (attester.public_key_bytes(), AssuranceLevel.HOST_ATTESTED)}).verify(attestation, receipts=_receipts("session-b"))[1] == "receipt_checkpoint_mismatch"


def _attester_process(connection):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    connection.send(public)
    while True:
        message = connection.recv()
        if message is None:
            return
        connection.send(private.sign(message))


class _PipeTransport:
    def __init__(self, connection):
        self.connection = connection

    def sign_statement(self, canonical_statement: bytes) -> bytes:
        self.connection.send(canonical_statement)
        return self.connection.recv()


def test_independent_adapter_uses_external_process_key_boundary():
    parent, child = mp.Pipe()
    process = mp.Process(target=_attester_process, args=(child,))
    process.start()
    try:
        public = parent.recv()
        adapter = ExternalAttesterAdapter("independent-process", _PipeTransport(parent))
        receipts = _receipts()
        statement = _statement(attester_id="independent-process", level=AssuranceLevel.INDEPENDENT_ATTESTER, receipts=receipts)
        attestation = adapter.sign(statement)
        registry = AttesterTrustRegistry({"independent-process": (public, AssuranceLevel.INDEPENDENT_ATTESTER)})
        assert registry.verify(attestation, receipts=receipts) == (True, None)
    finally:
        parent.send(None)
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
