from __future__ import annotations

import uuid
from typing import Any

from dingdongditch.evidence.models import EvidenceSignal, SignalAvailability, SignalKind

def reset_signal_ids_for_tests() -> None:
    """Compatibility no-op: evidence identity is collector-scoped."""


class EvidenceCollector:
    def __init__(
        self, scope_id: str | None = None, *, window_started_at_ms: int | None = None
    ) -> None:
        self.signals: list[EvidenceSignal] = []
        self.scope_id = scope_id or uuid.uuid4().hex
        self._next_id = 1
        self.window_started_at_ms = window_started_at_ms
        self.max_signals = 512
        self.discarded_signal_count = 0

    def add(
        self,
        *,
        kind: SignalKind,
        collected_at_ms: int,
        payload: dict[str, Any],
        availability: SignalAvailability = SignalAvailability.OBSERVED,
        notes: str = "",
        signal_id: str | None = None,
    ) -> EvidenceSignal:
        signal = EvidenceSignal(
            signal_id=signal_id or f"{self.scope_id}-sig-{self._next_id}",
            kind=kind,
            availability=availability,
            collected_at_ms=collected_at_ms,
            payload=payload,
            notes=notes,
        )
        self._next_id += 1
        self.signals.append(signal)
        if len(self.signals) > self.max_signals:
            self.signals.pop(0)
            self.discarded_signal_count += 1
        return signal
