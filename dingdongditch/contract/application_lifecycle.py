"""Browser-agnostic contracts for application generation lifecycles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from dingdongditch.contract.observation import FrozenDict, freeze


class ApplicationLifecycleState(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    ACTIVE = "active"
    VISUALLY_STABLE = "visually_stable"
    STALLED = "stalled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    OBSERVATION_UNAVAILABLE = "observation_unavailable"


@dataclass(frozen=True)
class ApplicationLifecycleEvidence:
    adapter_id: str
    state: ApplicationLifecycleState
    observation_id: str | None
    captured_at_ms: int | None
    fresh: bool
    terminal: bool
    evidence: FrozenDict

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", freeze(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "state": self.state.value,
            "observation_id": self.observation_id,
            "captured_at_ms": self.captured_at_ms,
            "fresh": self.fresh,
            "terminal": self.terminal,
            "evidence": dict(self.evidence),
        }
