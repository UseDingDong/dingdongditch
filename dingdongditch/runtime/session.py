"""Reusable lifecycle for bounded, fail-closed runtime sessions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import threading
from typing import Any


class SessionStatus(str, Enum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class SessionPhase(str, Enum):
    ACQUIRE = "acquire"
    VERIFY = "verify"
    PERFORM = "perform"
    FINISH = "finish"


class SessionLifecycleState(str, Enum):
    NEW = "new"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class SessionCheckpoint:
    phase: SessionPhase
    passed: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "passed": self.passed,
            "detail": dict(self.detail),
        }


class ManagedSession(ABC):
    """Template lifecycle shared by current and future interaction sessions."""

    def __init__(self) -> None:
        self.checkpoints: list[SessionCheckpoint] = []
        self._lifecycle_lock = threading.Lock()
        self.lifecycle_state = SessionLifecycleState.NEW

    def begin(self) -> None:
        with self._lifecycle_lock:
            if self.lifecycle_state != SessionLifecycleState.NEW:
                raise RuntimeError(
                    f"session cannot start from {self.lifecycle_state.value}"
                )
            self.lifecycle_state = SessionLifecycleState.RUNNING

    def finish(self, status: SessionStatus) -> None:
        terminal = SessionLifecycleState(status.value)
        with self._lifecycle_lock:
            if self.lifecycle_state != SessionLifecycleState.RUNNING:
                raise RuntimeError(
                    f"session cannot finish from {self.lifecycle_state.value}"
                )
            self.lifecycle_state = terminal

    def checkpoint(
        self, phase: SessionPhase, passed: bool, **detail: Any
    ) -> bool:
        self.checkpoints.append(SessionCheckpoint(phase, passed, detail))
        return passed

    @abstractmethod
    def run(self) -> Any:
        """Run the session and return its domain-specific structured result."""
