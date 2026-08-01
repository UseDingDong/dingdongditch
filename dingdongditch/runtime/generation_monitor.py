"""Progress-based monitoring for browser-observed response generation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class GenerationStatus(str, Enum):
    OBSERVING = "observing"
    COMPLETED = "completed"
    GENERATION_STALLED = "generation_stalled"


@dataclass(frozen=True)
class GenerationMonitorResult:
    status: GenerationStatus
    evidence: list[dict[str, Any]] = field(default_factory=list)


class ProgressBasedGenerationMonitor:
    """Track completion and stalls without imposing a total generation timeout."""

    def __init__(
        self,
        *,
        baseline_text: str,
        no_progress_lease_ms: int,
        stable_observations_required: int = 2,
    ) -> None:
        if no_progress_lease_ms < 1:
            raise ValueError("no_progress_lease_ms must be positive")
        if stable_observations_required < 1:
            raise ValueError("stable_observations_required must be positive")
        self.baseline_text = baseline_text
        self.no_progress_lease_ms = no_progress_lease_ms
        self.stable_observations_required = stable_observations_required
        self._last_signature: str | None = None
        self._last_text = ""
        self._last_progress_at_ms: int | None = None
        self._stable = 0
        self._evidence: list[dict[str, Any]] = []

    @staticmethod
    def _signature(text: str, progress_signals: Iterable[str]) -> str:
        material = "\0".join((text, *progress_signals))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def observe(
        self,
        *,
        observation_id: str,
        captured_at_ms: int,
        text: str,
        generation_active: bool,
        progress_signals: Iterable[str] = (),
        fresh: bool = True,
    ) -> GenerationMonitorResult:
        signals = tuple(progress_signals)
        signature = self._signature(text, signals)
        meaningful_progress = (
            self._last_signature is not None and signature != self._last_signature
        )
        if fresh and (
            self._last_progress_at_ms is None or meaningful_progress
        ):
            self._last_progress_at_ms = captured_at_ms

        if fresh and text != self.baseline_text and text == self._last_text and not generation_active:
            self._stable += 1
        else:
            self._stable = 0

        idle_ms = (
            0
            if self._last_progress_at_ms is None
            else max(0, captured_at_ms - self._last_progress_at_ms)
        )
        sample = {
            "observation_id": observation_id,
            "captured_at_ms": captured_at_ms,
            "fresh": fresh,
            "text_length": len(text),
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "generation_active": generation_active,
            "progress_signals": list(signals),
            "meaningful_progress": meaningful_progress,
            "no_progress_ms": idle_ms,
            "stable_idle_samples": self._stable,
        }
        self._evidence.append(sample)
        if fresh:
            self._last_signature = signature
            self._last_text = text

        if self._stable >= self.stable_observations_required:
            return GenerationMonitorResult(
                GenerationStatus.COMPLETED,
                list(self._evidence),
            )
        if (
            fresh
            and generation_active
            and idle_ms >= self.no_progress_lease_ms
        ):
            return GenerationMonitorResult(
                GenerationStatus.GENERATION_STALLED,
                list(self._evidence),
            )
        return GenerationMonitorResult(
            GenerationStatus.OBSERVING,
            list(self._evidence),
        )
