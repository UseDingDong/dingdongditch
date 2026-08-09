"""Deterministic, tamper-evident receipt hashing and chaining (no signing)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from dingdongditch.contract.authority import canonical_json_bytes


RECEIPT_CHAIN_VERSION = "3"


def _as_dict(receipt: Any) -> dict[str, Any]:
    if hasattr(receipt, "to_dict"):
        return receipt.to_dict()
    if isinstance(receipt, Mapping):
        return dict(receipt)
    raise TypeError("receipt must be an ExecutionReceipt or mapping")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _legacy_digest(value: Any) -> str:
    """Pre-v3 canonical bytes retained solely for historic chain verification."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _artifact_hashes_v2(receipt: Mapping[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in receipt.get("artifacts") or []:
        if not isinstance(item, Mapping):
            continue
        checksum = item.get("sha256") or item.get("checksum") or item.get("checksum_sha256")
        if isinstance(checksum, str) and checksum:
            result.append({"artifact_id": str(item.get("artifact_id", "")), "sha256": checksum})
    return sorted(result, key=lambda item: (item["artifact_id"], item["sha256"]))


def _artifact_manifest(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Bind every public artifact declaration, even without a checksum."""
    items: list[dict[str, str | None]] = []
    for item in receipt.get("artifacts") or []:
        if isinstance(item, Mapping):
            checksum = item.get("sha256") or item.get("checksum") or item.get("checksum_sha256")
            items.append({
                "artifact_id": str(item.get("artifact_id", "")),
                "sha256": checksum if isinstance(checksum, str) and checksum else None,
                # Only the hash is incorporated into the receipt payload; a
                # path/body in an artifact declaration is never copied out.
                "declaration_hash": _digest(dict(item)),
            })
        else:
            items.append({"artifact_id": None, "sha256": None, "declaration_hash": _digest(item)})
    return {"count": len(items), "items": items}


def _session_binding_hash(receipt: Mapping[str, Any]) -> str | None:
    browser = receipt.get("browser")
    if not isinstance(browser, Mapping):
        return None
    binding = {
        "browser_session_id": browser.get("browser_session_id"),
        "context_id": browser.get("context_id"),
    }
    if not any(isinstance(value, str) and value for value in binding.values()):
        return None
    return _digest(binding)


def _field_presence(receipt: Mapping[str, Any]) -> dict[str, bool]:
    """Distinguish omitted fields from explicit nulls in a public payload."""
    fields = (
        "target_locator", "target_resolution", "failure_kind", "execution_error",
        "action_evidence", "page_precondition", "page_transition",
        "dispatch_document_url", "authority_decision", "transaction",
        "quorum_verification", "control_epoch", "signed_plan", "identity", "mutation_arbitration", "speculation", "expectation_evidence",
        "artifacts", "browser",
    )
    return {name: name in receipt for name in fields}


_RECEIPT_CHAIN_KNOWN_FIELDS = frozenset({
    "schema_version", "operation_id", "verdict", "action_type", "target_locator", "target_resolution",
    "target_url", "started_at_ms", "finished_at_ms", "action_started_at_ms", "action_completed_at_ms",
    "verification_completed_at_ms", "execution_status", "execution_error", "failure_kind",
    "action_executed_successfully", "action_evidence", "page_precondition", "page_transition",
    "navigation_occurred", "dispatch_document_url", "authority_decision", "transaction",
        "quorum_verification", "control_epoch", "signed_plan", "identity", "mutation_arbitration", "speculation", "expectation_results", "freshness", "expectation_evidence",
    "evidence", "artifacts", "runtime_version", "browser", "telemetry", "operation_timing", "cleanup",
    "expectations_declared", "pre_action_observation", "post_action_observation", "recovery_attempts",
    "limitations", "backend_identity", "browser_identity", "receipt_chain",
})


def receipt_payload(receipt: Any) -> dict[str, Any]:
    """Stable relevant payload, excluding the self-referential chain field.

    Operational timings and telemetry are intentionally excluded. The chain
    covers outcomes, target/action facts, governance, verification, bounded
    evidence, and artifact checksums without making unrelated latency noise a
    reproducibility input.
    """
    raw = _as_dict(receipt)
    return {
        "schema_version": raw.get("schema_version"),
        "operation_id": raw.get("operation_id"),
        "verdict": raw.get("verdict"),
        "action_type": raw.get("action_type"),
        "target_locator": raw.get("target_locator"),
        "target_resolution": raw.get("target_resolution"),
        "target_url": raw.get("target_url"),
        "execution_status": raw.get("execution_status"),
        "execution_error": raw.get("execution_error"),
        "failure_kind": raw.get("failure_kind"),
        "action_executed_successfully": raw.get("action_executed_successfully"),
        "action_evidence": raw.get("action_evidence"),
        "page_precondition": raw.get("page_precondition"),
        "page_transition": raw.get("page_transition"),
        "navigation_occurred": raw.get("navigation_occurred"),
        "dispatch_document_url": raw.get("dispatch_document_url"),
        "authority_decision": raw.get("authority_decision"),
        "transaction": raw.get("transaction"),
        "quorum_verification": raw.get("quorum_verification"),
        "signed_plan": raw.get("signed_plan"),
        "identity": raw.get("identity"),
        "mutation_arbitration": raw.get("mutation_arbitration"),
        "speculation": raw.get("speculation"),
        "control_epoch": raw.get("control_epoch"),
        "expectation_results": raw.get("expectation_results"),
        "freshness": raw.get("freshness"),
        "bounded_evidence": {
            "expectation_evidence": raw.get("expectation_evidence"),
            "evidence": raw.get("evidence"),
        },
        "artifact_manifest": _artifact_manifest(raw),
        "runtime_version": raw.get("runtime_version"),
        "browser": {
            key: (raw.get("browser") or {}).get(key)
            for key in ("engine", "channel", "browser_session_id", "context_id", "page_id")
        },
        "field_presence": _field_presence(raw),
        # Direct mapping callers may carry an additive extension before the
        # package parser sees it.  Bind it rather than silently permitting an
        # artifact/governance field to appear after sealing.  The only
        # deliberately excluded known fields are timing/telemetry/cleanup.
        "extensions": {
            key: value for key, value in raw.items()
            if key not in _RECEIPT_CHAIN_KNOWN_FIELDS
        },
    }


def hash_receipt(receipt: Any) -> str:
    """Return the deterministic hash of a receipt's relevant payload."""
    return _digest(receipt_payload(receipt))


def _receipt_payload_v2(receipt: Any) -> dict[str, Any]:
    """The v2 payload before all artifact declarations were bound."""
    raw = _as_dict(receipt)
    return {
        "schema_version": raw.get("schema_version"), "operation_id": raw.get("operation_id"),
        "verdict": raw.get("verdict"), "action_type": raw.get("action_type"),
        "target_locator": raw.get("target_locator"), "target_resolution": raw.get("target_resolution"),
        "target_url": raw.get("target_url"), "execution_status": raw.get("execution_status"),
        "execution_error": raw.get("execution_error"), "failure_kind": raw.get("failure_kind"),
        "action_executed_successfully": raw.get("action_executed_successfully"),
        "action_evidence": raw.get("action_evidence"), "page_precondition": raw.get("page_precondition"),
        "page_transition": raw.get("page_transition"), "navigation_occurred": raw.get("navigation_occurred"),
        "dispatch_document_url": raw.get("dispatch_document_url"),
        "authority_decision": raw.get("authority_decision"), "transaction": raw.get("transaction"),
        "quorum_verification": raw.get("quorum_verification"), "control_epoch": raw.get("control_epoch"),
        "expectation_results": raw.get("expectation_results"), "freshness": raw.get("freshness"),
        "bounded_evidence": {"expectation_evidence": raw.get("expectation_evidence"), "evidence": raw.get("evidence")},
        "artifact_hashes": _artifact_hashes_v2(raw), "runtime_version": raw.get("runtime_version"),
        "browser": {key: (raw.get("browser") or {}).get(key) for key in ("engine", "channel", "browser_session_id", "context_id", "page_id")},
        "field_presence": _field_presence(raw),
    }


def _receipt_payload_v1(receipt: Any) -> dict[str, Any]:
    """Historical v1 payload retained solely to verify published chains."""
    raw = _as_dict(receipt)
    return {
        "schema_version": raw.get("schema_version"), "operation_id": raw.get("operation_id"),
        "verdict": raw.get("verdict"), "action_type": raw.get("action_type"),
        "target_locator": raw.get("target_locator"), "target_resolution": raw.get("target_resolution"),
        "target_url": raw.get("target_url"), "execution_status": raw.get("execution_status"),
        "failure_kind": raw.get("failure_kind"),
        "action_executed_successfully": raw.get("action_executed_successfully"),
        "action_evidence": raw.get("action_evidence"), "page_precondition": raw.get("page_precondition"),
        "authority_decision": raw.get("authority_decision"), "transaction": raw.get("transaction"),
        "quorum_verification": raw.get("quorum_verification"),
        "expectation_results": raw.get("expectation_results"), "freshness": raw.get("freshness"),
        "bounded_evidence": {"expectation_evidence": raw.get("expectation_evidence"), "evidence": raw.get("evidence")},
        "artifact_hashes": _artifact_hashes_v2(raw), "runtime_version": raw.get("runtime_version"),
        "browser": {key: (raw.get("browser") or {}).get(key) for key in ("engine", "channel", "browser_session_id", "context_id", "page_id")},
    }


def _make_receipt_chain_entry_v1(
    receipt: Any,
    *,
    previous_receipt_hash: str | None = None,
    execution_plan_hash: str | None = None,
    operation_hash: str | None = None,
) -> dict[str, Any]:
    raw = _as_dict(receipt)
    payload_hash = _legacy_digest(_receipt_payload_v1(raw))
    authority = raw.get("authority_decision") or {}
    entry = {
        "chain_version": "1",
        "previous_receipt_hash": previous_receipt_hash,
        "receipt_payload_hash": payload_hash,
        "execution_plan_hash": execution_plan_hash,
        "operation_hash": operation_hash,
        "policy_hash": authority.get("policy_hash"),
        "evidence_hash": _legacy_digest({"evidence": raw.get("evidence"), "expectation_evidence": raw.get("expectation_evidence")}),
        "artifact_hashes": _artifact_hashes_v2(raw),
        "runtime_version": raw.get("runtime_version"),
        "receipt_schema_version": raw.get("schema_version"),
    }
    entry["receipt_hash"] = _legacy_digest(entry)
    return entry


def _make_receipt_chain_entry_v2(
    receipt: Any,
    *,
    previous_receipt_hash: str | None = None,
    execution_plan_hash: str | None = None,
    operation_hash: str | None = None,
) -> dict[str, Any]:
    """Historical v2 verifier retained for published pre-checkpoint chains."""
    raw = _as_dict(receipt)
    payload_hash = _legacy_digest(_receipt_payload_v2(raw))
    authority = raw.get("authority_decision") or {}
    entry = {
        "chain_version": "2",
        "previous_receipt_hash": previous_receipt_hash,
        "receipt_payload_hash": payload_hash,
        "execution_plan_hash": execution_plan_hash,
        "operation_hash": operation_hash,
        "policy_hash": authority.get("policy_hash"),
        "evidence_hash": _legacy_digest({
            "evidence": raw.get("evidence"),
            "expectation_evidence": raw.get("expectation_evidence"),
            "action_evidence": raw.get("action_evidence"),
            "quorum_verification": raw.get("quorum_verification"),
        }),
        "artifact_hashes": _artifact_hashes_v2(raw),
        "session_binding_hash": _session_binding_hash(raw),
        "runtime_version": raw.get("runtime_version"),
        "receipt_schema_version": raw.get("schema_version"),
    }
    entry["receipt_hash"] = _legacy_digest(entry)
    return entry


def make_receipt_chain_entry(
    receipt: Any,
    *,
    previous_receipt_hash: str | None = None,
    execution_plan_hash: str | None = None,
    operation_hash: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    raw = _as_dict(receipt)
    payload_hash = hash_receipt(raw)
    authority = raw.get("authority_decision") or {}
    entry = {
        "chain_version": RECEIPT_CHAIN_VERSION,
        "previous_receipt_hash": previous_receipt_hash,
        "receipt_payload_hash": payload_hash,
        "execution_plan_hash": execution_plan_hash,
        "operation_hash": operation_hash,
        "policy_hash": authority.get("policy_hash"),
        "evidence_hash": _digest({
            "evidence": raw.get("evidence"),
            "expectation_evidence": raw.get("expectation_evidence"),
            "action_evidence": raw.get("action_evidence"),
            "quorum_verification": raw.get("quorum_verification"),
            "signed_plan": raw.get("signed_plan"),
            "identity": raw.get("identity"),
            "mutation_arbitration": raw.get("mutation_arbitration"),
            "speculation": raw.get("speculation"),
        }),
        "artifact_hashes": _artifact_manifest(raw),
        "session_binding_hash": _session_binding_hash(raw),
        "runtime_version": raw.get("runtime_version"),
        "receipt_schema_version": raw.get("schema_version"),
        "session_id": session_id,
    }
    entry["receipt_hash"] = _digest(entry)
    return entry


def chain_receipt(
    receipt: Any,
    *,
    previous_receipt_hash: str | None = None,
    execution_plan_hash: str | None = None,
    operation_hash: str | None = None,
    session_id: str | None = None,
) -> Any:
    """Return a newly sealed receipt carrying one chain entry."""
    entry = make_receipt_chain_entry(
        receipt,
        previous_receipt_hash=previous_receipt_hash,
        execution_plan_hash=execution_plan_hash,
        operation_hash=operation_hash,
        session_id=session_id,
    )
    if not hasattr(receipt, "to_dict"):
        result = _as_dict(receipt)
        result["receipt_chain"] = entry
        return result
    return replace(receipt, _sealed=False, receipt_chain=entry).seal()


def verify_receipt_hash(receipt: Any) -> bool:
    raw = _as_dict(receipt)
    entry = raw.get("receipt_chain")
    if not isinstance(entry, Mapping):
        return False
    maker = {
        "1": _make_receipt_chain_entry_v1,
        "2": _make_receipt_chain_entry_v2,
        RECEIPT_CHAIN_VERSION: make_receipt_chain_entry,
    }.get(entry.get("chain_version"))
    if maker is None:
        return False
    kwargs = {
        "previous_receipt_hash": entry.get("previous_receipt_hash"),
        "execution_plan_hash": entry.get("execution_plan_hash"),
        "operation_hash": entry.get("operation_hash"),
    }
    if maker is make_receipt_chain_entry:
        kwargs["session_id"] = entry.get("session_id")
    expected = maker(raw, **kwargs)
    return dict(entry) == expected


@dataclass(frozen=True)
class ReceiptChainVerification:
    valid: bool
    head: str | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReceiptChainCheckpoint:
    """Host-retained chain anchor; this is expressly not a signature."""

    session_id: str
    chain_length: int
    chain_head_hash: str | None
    timestamp_ms: int
    chain_version: str = RECEIPT_CHAIN_VERSION
    runtime_version: str | None = None

    def validate(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("receipt checkpoint session_id is required")
        if not isinstance(self.chain_length, int) or isinstance(self.chain_length, bool) or self.chain_length < 0:
            raise ValueError("receipt checkpoint chain_length must be non-negative")
        if self.chain_length == 0 and self.chain_head_hash is not None:
            raise ValueError("empty receipt checkpoint cannot have a head hash")
        if self.chain_length > 0 and (not isinstance(self.chain_head_hash, str) or len(self.chain_head_hash) != 64):
            raise ValueError("receipt checkpoint head hash is invalid")
        if not isinstance(self.timestamp_ms, int) or isinstance(self.timestamp_ms, bool) or self.timestamp_ms < 0:
            raise ValueError("receipt checkpoint timestamp is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "chain_length": self.chain_length,
            "chain_head_hash": self.chain_head_hash,
            "timestamp_ms": self.timestamp_ms,
            "chain_version": self.chain_version,
            "runtime_version": self.runtime_version,
        }


def verify_receipt_chain(receipts: Iterable[Any], *, allow_legacy: bool = False) -> ReceiptChainVerification:
    previous: str | None = None
    session_binding: str | None = None
    reasons: list[str] = []
    for index, receipt in enumerate(receipts):
        raw = _as_dict(receipt)
        entry = raw.get("receipt_chain")
        if not isinstance(entry, Mapping):
            if allow_legacy:
                continue
            reasons.append(f"receipt[{index}] has no chain entry")
            continue
        if entry.get("previous_receipt_hash") != previous:
            reasons.append(f"receipt[{index}] previous hash does not match chain head")
        if not verify_receipt_hash(raw):
            reasons.append(f"receipt[{index}] hash does not verify")
        binding = entry.get("session_binding_hash")
        if binding is not None:
            if not isinstance(binding, str) or not binding:
                reasons.append(f"receipt[{index}] session binding is invalid")
            elif session_binding is None:
                session_binding = binding
            elif binding != session_binding:
                reasons.append(f"receipt[{index}] session binding does not match chain")
        previous = entry.get("receipt_hash") if isinstance(entry.get("receipt_hash"), str) else previous
    return ReceiptChainVerification(not reasons, previous, tuple(reasons))


def make_receipt_chain_checkpoint(
    receipts: Iterable[Any],
    *,
    session_id: str,
    timestamp_ms: int,
    runtime_version: str | None = None,
) -> ReceiptChainCheckpoint:
    """Export a checkpoint that the host must retain outside the chain."""
    items = tuple(receipts)
    verified = verify_receipt_chain(items)
    if not verified.valid:
        raise ValueError("cannot checkpoint an invalid receipt chain")
    checkpoint = ReceiptChainCheckpoint(session_id, len(items), verified.head, timestamp_ms, runtime_version=runtime_version)
    checkpoint.validate()
    for receipt in items:
        entry = _as_dict(receipt).get("receipt_chain") or {}
        if entry.get("chain_version") == RECEIPT_CHAIN_VERSION and entry.get("session_id") != session_id:
            raise ValueError("receipt chain session does not match checkpoint session")
    return checkpoint


def verify_receipt_chain_against_checkpoint(
    receipts: Iterable[Any], checkpoint: ReceiptChainCheckpoint,
) -> ReceiptChainVerification:
    """Verify a chain relative to an independently retained checkpoint.

    A later chain extension is permitted.  Tail/prefix deletion and rewrites
    cannot pass unless they retain the checkpoint's exact prefix/head.  This
    does not identify a producer or provide independent attestation.
    """
    try:
        checkpoint.validate()
    except ValueError as exc:
        return ReceiptChainVerification(False, None, (str(exc),))
    items = tuple(receipts)
    verified = verify_receipt_chain(items)
    reasons = list(verified.reasons)
    if len(items) < checkpoint.chain_length:
        reasons.append("receipt chain is shorter than the trusted checkpoint")
    elif checkpoint.chain_length:
        entry = _as_dict(items[checkpoint.chain_length - 1]).get("receipt_chain") or {}
        if entry.get("receipt_hash") != checkpoint.chain_head_hash:
            reasons.append("receipt checkpoint head does not match the retained prefix")
    for index, receipt in enumerate(items):
        entry = _as_dict(receipt).get("receipt_chain") or {}
        if entry.get("chain_version") == RECEIPT_CHAIN_VERSION and entry.get("session_id") != checkpoint.session_id:
            reasons.append(f"receipt[{index}] session does not match checkpoint")
    return ReceiptChainVerification(not reasons, verified.head, tuple(reasons))
