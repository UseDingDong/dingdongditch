from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from dingdongditch.contract.verdict import Verdict
from dingdongditch.contract.observation import freeze
from dingdongditch.evidence.models import (
    ExpectationResult,
    EvidenceSignal,
    FreshnessEvaluation,
    ObservationSummary,
    RecoveryAttempt,
)

RECEIPT_SCHEMA_VERSION = "1.8.0"


def _deep_freeze_receipt(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            object.__setattr__(value, item.name, _deep_freeze_receipt(getattr(value, item.name)))
        return value
    if isinstance(value, dict):
        return freeze({key: _deep_freeze_receipt(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return freeze([_deep_freeze_receipt(item) for item in value])
    return value


@dataclass
class ExecutionReceipt:
    schema_version: str
    operation_id: str
    verdict: Verdict
    action_type: str
    target_locator: dict[str, Any] | None
    target_url: str
    started_at_ms: int
    finished_at_ms: int
    action_started_at_ms: int | None
    action_completed_at_ms: int | None
    verification_completed_at_ms: int | None
    execution_status: str
    execution_error: str | None
    pre_action_observation: ObservationSummary | None
    post_action_observation: ObservationSummary | None
    expectation_results: list[ExpectationResult]
    evidence: list[EvidenceSignal]
    freshness: FreshnessEvaluation
    recovery_attempts: list[RecoveryAttempt]
    limitations: list[str]
    backend_identity: str
    browser_identity: str
    runtime_version: str
    action_executed_successfully: bool
    expectations_declared: int
    target_resolution: dict[str, Any] | None = None
    browser: dict[str, Any] | None = None
    failure_kind: str | None = None
    action_evidence: dict[str, Any] | None = None
    page_precondition: dict[str, Any] | None = None
    navigation_occurred: bool = False
    dispatch_document_url: str | None = None
    telemetry: list[dict[str, Any]] | None = None
    # Per-operation monotonic runtime duration phases (not upstream reasoning).
    operation_timing: dict[str, int] | None = None
    # Bounded semantic justifications for failed/indeterminate expectations.
    expectation_evidence: list[dict[str, Any]] | None = None
    # Optional heavyweight material is referenced, never embedded.
    artifacts: list[dict[str, Any]] | None = None
    cleanup: dict[str, Any] | None = None
    page_transition: dict[str, Any] | None = None
    # Compact governance facts. Detailed policy remains host-owned.
    authority_decision: dict[str, Any] | None = None
    transaction: dict[str, Any] | None = None
    quorum_verification: dict[str, Any] | None = None
    # Session control epoch binds a receipt to the planner lease that caused
    # the dispatch without recording a planner secret or vendor identity.
    control_epoch: int | None = None
    receipt_chain: dict[str, Any] | None = None
    # Bounded pointer only; the public signed authorization object is retained
    # by the host and never embedded in receipts.
    signed_plan: dict[str, Any] | None = None
    # Portable identity attribution, intentionally separate from policy and
    # current controller lease.
    identity: dict[str, Any] | None = None
    mutation_arbitration: dict[str, Any] | None = None
    speculation: dict[str, Any] | None = None
    _sealed: bool = False

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False) and name != "_sealed":
            raise TypeError("published runtime receipt is immutable")
        object.__setattr__(self, name, value)

    def seal(self) -> "ExecutionReceipt":
        if self._sealed:
            return self
        for item in fields(self):
            if item.name != "_sealed":
                object.__setattr__(self, item.name, _deep_freeze_receipt(getattr(self, item.name)))
        object.__setattr__(self, "_sealed", True)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "verdict": self.verdict.value,
            "action_type": self.action_type,
            "target_locator": self.target_locator,
            "target_resolution": self.target_resolution,
            "target_url": self.target_url,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "action_started_at_ms": self.action_started_at_ms,
            "action_completed_at_ms": self.action_completed_at_ms,
            "verification_completed_at_ms": self.verification_completed_at_ms,
            "execution_status": self.execution_status,
            "execution_error": self.execution_error,
            "failure_kind": self.failure_kind,
            "action_executed_successfully": self.action_executed_successfully,
            "action_evidence": self.action_evidence,
            "page_precondition": self.page_precondition,
            "navigation_occurred": self.navigation_occurred,
            "dispatch_document_url": self.dispatch_document_url,
            "telemetry": list(self.telemetry or []),
            "operation_timing": self.operation_timing,
            "expectation_evidence": list(self.expectation_evidence or []),
            "artifacts": list(self.artifacts or []),
            "cleanup": self.cleanup,
            "page_transition": self.page_transition,
            "authority_decision": self.authority_decision,
            "transaction": self.transaction,
            "quorum_verification": self.quorum_verification,
            "control_epoch": self.control_epoch,
            "receipt_chain": self.receipt_chain,
            "signed_plan": self.signed_plan,
            "identity": self.identity,
            "mutation_arbitration": self.mutation_arbitration,
            "speculation": self.speculation,
            "expectations_declared": self.expectations_declared,
            "pre_action_observation": (
                self.pre_action_observation.to_dict() if self.pre_action_observation else None
            ),
            "post_action_observation": (
                self.post_action_observation.to_dict() if self.post_action_observation else None
            ),
            "expectation_results": [r.to_dict() for r in self.expectation_results],
            "evidence": [e.to_dict() for e in self.evidence],
            "freshness": self.freshness.to_dict(),
            "recovery_attempts": [r.to_dict() for r in self.recovery_attempts],
            "limitations": list(self.limitations),
            "backend_identity": self.backend_identity,
            "browser_identity": self.browser_identity,
            "browser": self.browser,
            "runtime_version": self.runtime_version,
        }

    def to_core_dict(self) -> dict[str, Any]:
        """Layer 1: small deterministic truth record without evidence/artifacts."""
        resolution = self.target_resolution or {}
        expectation_counts = {"pass": 0, "fail": 0, "indeterminate": 0}
        for result in self.expectation_results:
            if result.result in expectation_counts:
                expectation_counts[result.result] += 1
        browser = self.browser or {}
        webauthn = (self.action_evidence or {}).get("webauthn")
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "action_type": self.action_type,
            "verdict": self.verdict.value,
            "failure_kind": self.failure_kind,
            "execution_status": self.execution_status,
            "target_resolution": {
                "final_candidate_count": resolution.get("final_candidate_count"),
                "cardinality_passed": resolution.get("cardinality_passed"),
                "failure_kind": resolution.get("failure_kind"),
                "frame_path_depth": resolution.get("frame_path_depth", 0),
                "failure_hop": resolution.get("failure_hop"),
            } if resolution else None,
            "expectation_outcome": {
                "declared": self.expectations_declared,
                **expectation_counts,
            },
            "timing": dict(self.operation_timing or {}),
            "session_page_identity": {
                "browser_session_id": browser.get("browser_session_id"),
                "context_id": browser.get("context_id"),
                "page_id": browser.get("page_id"),
            },
            "webauthn_participation": (
                {
                    "request_id": webauthn.get("request_id"),
                    "status": webauthn.get("status"),
                    "browser_engine": webauthn.get("browser_engine"),
                }
                if isinstance(webauthn, dict)
                else None
            ),
            "authority": (
                {
                    "outcome": (self.authority_decision or {}).get("outcome"),
                    "policy_id": (self.authority_decision or {}).get("policy_id"),
                    "policy_hash": (self.authority_decision or {}).get("policy_hash"),
                    "rule_matched": (self.authority_decision or {}).get("rule_matched"),
                }
                if self.authority_decision is not None
                else None
            ),
            "transaction": (
                {
                    "status": (self.transaction or {}).get("status"),
                    "token_id": (self.transaction or {}).get("token_id"),
                    "preparation_fingerprint": (self.transaction or {}).get("preparation_fingerprint"),
                }
                if self.transaction is not None
                else None
            ),
            "quorum": (
                {
                    "verdict": (self.quorum_verification or {}).get("verdict"),
                    "required": (self.quorum_verification or {}).get("required"),
                    "achieved": (self.quorum_verification or {}).get("achieved"),
                }
                if self.quorum_verification is not None
                else None
            ),
            "receipt_chain": (
                {
                    "receipt_hash": (self.receipt_chain or {}).get("receipt_hash"),
                    "previous_receipt_hash": (self.receipt_chain or {}).get("previous_receipt_hash"),
                }
                if self.receipt_chain is not None
                else None
            ),
            "control_epoch": self.control_epoch,
            "signed_plan": self.signed_plan,
            "identity": self.identity,
            "mutation_arbitration": self.mutation_arbitration,
            "speculation": self.speculation,
        }

    def to_bounded_evidence_dict(self) -> dict[str, Any]:
        """Layer 2: compact evidence justifying, but not redefining, the verdict."""
        return {
            "expectation_evidence": list(self.expectation_evidence or []),
            "signals": [signal.to_dict() for signal in self.evidence],
            "action_evidence": self.action_evidence,
            "freshness": self.freshness.to_dict(),
            "authority_decision": self.authority_decision,
            "transaction": self.transaction,
            "quorum_verification": self.quorum_verification,
            "control_epoch": self.control_epoch,
            "receipt_chain": self.receipt_chain,
            "signed_plan": self.signed_plan,
            "identity": self.identity,
            "mutation_arbitration": self.mutation_arbitration,
            "speculation": self.speculation,
        }

    def to_layered_dict(self) -> dict[str, Any]:
        """Formal three-layer representation for new consumers."""
        return {
            "core_receipt": self.to_core_dict(),
            "bounded_evidence": self.to_bounded_evidence_dict(),
            "artifacts": list(self.artifacts or []),
        }
