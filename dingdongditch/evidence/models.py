from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class SignalKind(str, Enum):
    URL = "url"
    DOM_STATE = "dom_state"
    NETWORK = "network"
    ACTION_RESULT = "action_result"
    CONSOLE = "console"
    TIMESTAMP = "timestamp"


class SignalAvailability(str, Enum):
    OBSERVED = "observed"
    NOT_REQUESTED = "not_requested"
    UNAVAILABLE = "unavailable"
    CONTRADICTED = "contradicted"


@dataclass
class EvidenceSignal:
    signal_id: str
    kind: SignalKind
    availability: SignalAvailability
    collected_at_ms: int
    payload: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "kind": self.kind.value,
            "availability": self.availability.value,
            "collected_at_ms": self.collected_at_ms,
            "payload": self.payload,
            "notes": self.notes,
        }


@dataclass
class ExpectationResult:
    expectation_id: str
    expectation_type: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    result: str  # pass | fail | indeterminate
    evidence_refs: list[str] = field(default_factory=list)
    evidence_timestamp_ms: int | None = None
    explanation: str = ""
    freshness_ok: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FreshnessEvaluation:
    policy_max_age_ms: int
    action_started_at_ms: int | None
    verification_completed_at_ms: int | None
    stale_signal_ids: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryAttempt:
    reason: str
    attempt_index: int
    occurred_at_ms: int
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ObservationSummary:
    collected_at_ms: int
    url: str | None = None
    notes: str = ""
    signal_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
