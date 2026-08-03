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

RECEIPT_SCHEMA_VERSION = "1.7.0"


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
    cleanup: dict[str, Any] | None = None
    page_transition: dict[str, Any] | None = None
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
            "cleanup": self.cleanup,
            "page_transition": self.page_transition,
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
