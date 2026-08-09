"""Public contracts for browser preparation and exactly-once commit tokens."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PreparationStatus(str, Enum):
    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    INVALIDATED = "INVALIDATED"


class CommitRejectedReason(str, Enum):
    PREPARATION_NOT_FOUND = "PREPARATION_NOT_FOUND"
    PREPARATION_INVALIDATED = "PREPARATION_INVALIDATED"
    PREPARATION_EXPIRED = "PREPARATION_EXPIRED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"
    PREPARED_STATE_CHANGED = "PREPARED_STATE_CHANGED"
    TARGET_CHANGED = "TARGET_CHANGED"
    ORIGIN_CHANGED = "ORIGIN_CHANGED"
    PAGE_CHANGED = "PAGE_CHANGED"
    PAYLOAD_CHANGED = "PAYLOAD_CHANGED"
    AUTHORITY_CHANGED = "AUTHORITY_CHANGED"
    AUTHORITY_REJECTED = "AUTHORITY_REJECTED"
    SECRET_BINDING_UNAVAILABLE = "SECRET_BINDING_UNAVAILABLE"
    SECRET_BINDING_CHANGED = "SECRET_BINDING_CHANGED"
    PREPARATION_REQUIRED = "PREPARATION_REQUIRED"
    NOT_CONSEQUENTIAL = "NOT_CONSEQUENTIAL"
    MUTATION_EPOCH_CHANGED = "MUTATION_EPOCH_CHANGED"


class TwoPhaseCommitError(RuntimeError):
    def __init__(self, reason: CommitRejectedReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"reason": self.reason.value, "message": str(self)}


@dataclass(frozen=True)
class PreparedOperation:
    """Safe public view of a server-side prepared operation.

    The token is opaque. Payload and browser handles remain private to the
    retained DingDongDitch session; only digests are exposed.
    """

    token: str
    session_id: str
    expires_at_ms: int
    status: PreparationStatus
    action_type: str
    origin: str
    page_id: str
    state_fingerprint: str
    target_fingerprint: str | None
    operation_hash: str
    authority_policy_hash: str | None
    authority_decision: dict[str, Any] | None
    mutation_epoch: int | None = None
    arbitration_policy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "session_id": self.session_id,
            "expires_at_ms": self.expires_at_ms,
            "status": self.status.value,
            "action_type": self.action_type,
            "origin": self.origin,
            "page_id": self.page_id,
            "state_fingerprint": self.state_fingerprint,
            "target_fingerprint": self.target_fingerprint,
            "operation_hash": self.operation_hash,
            "authority_policy_hash": self.authority_policy_hash,
            "authority_decision": self.authority_decision,
            "mutation_epoch": self.mutation_epoch,
            "arbitration_policy": self.arbitration_policy,
        }


@dataclass(frozen=True)
class CommitResult:
    session_id: str
    token: str
    committed: bool
    rejection_reason: CommitRejectedReason | None
    receipt: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "token": self.token,
            "committed": self.committed,
            "rejection_reason": self.rejection_reason.value if self.rejection_reason else None,
            "receipt": self.receipt.to_dict() if self.receipt is not None else None,
        }
