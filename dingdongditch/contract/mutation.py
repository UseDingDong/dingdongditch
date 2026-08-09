"""Deterministic mutation-epoch arbitration for shared live browsers.

Browser events do not reliably identify a human.  ``HUMAN`` is therefore used
only when a trusted host explicitly reports a manual event; observed page
changes default to ``EXTERNAL_UNKNOWN`` and never claim human attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MutationActor(str, Enum):
    AGENT = "agent"
    HUMAN = "human"
    EXTERNAL_UNKNOWN = "external_unknown"


class MutationArbitrationPolicy(str, Enum):
    FAIL_ON_EXTERNAL_MUTATION = "fail_on_external_mutation"
    REQUIRE_REPREPARE = "require_reprepare"
    HUMAN_PRIORITY = "human_priority"


class MutationArbitrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MutationEvidence:
    mutation_epoch: int
    actor: MutationActor
    policy: MutationArbitrationPolicy
    detected_at_ms: int
    source: str
    preparation_invalidated: bool

    def validate(self) -> None:
        if not isinstance(self.mutation_epoch, int) or isinstance(self.mutation_epoch, bool) or self.mutation_epoch < 0:
            raise ValueError("mutation epoch is invalid")
        if not isinstance(self.actor, MutationActor) or not isinstance(self.policy, MutationArbitrationPolicy):
            raise ValueError("mutation evidence enum is invalid")
        if not isinstance(self.detected_at_ms, int) or isinstance(self.detected_at_ms, bool) or self.detected_at_ms < 0:
            raise ValueError("mutation evidence timestamp is invalid")
        if self.source not in {"browser_state", "trusted_host", "agent_dispatch"}:
            raise ValueError("mutation evidence source is invalid")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "mutation_epoch": self.mutation_epoch,
            "actor": self.actor.value,
            "policy": self.policy.value,
            "detected_at_ms": self.detected_at_ms,
            "source": self.source,
            "preparation_invalidated": self.preparation_invalidated,
        }
