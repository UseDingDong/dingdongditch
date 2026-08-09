"""Model-neutral planner control handoff contracts for retained sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentHandoffCheckpoint:
    handoff_token: str
    session_id: str
    old_agent_id: str | None
    recipient_agent_id: str | None
    control_epoch: int
    expires_at_ms: int
    selected_page_id: str | None
    pages: tuple[dict[str, Any], ...]
    observation_checkpoint: dict[str, Any]
    authority: dict[str, Any] | None
    receipt_chain_head: str | None
    pending_preparations: tuple[dict[str, Any], ...]
    runtime_capabilities: tuple[str, ...]
    identity: dict[str, Any] | None = None
    mutation: dict[str, Any] | None = None
    mutation_epoch: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoff_token": self.handoff_token,
            "session_id": self.session_id,
            "old_agent_id": self.old_agent_id,
            "recipient_agent_id": self.recipient_agent_id,
            "control_epoch": self.control_epoch,
            "expires_at_ms": self.expires_at_ms,
            "selected_page_id": self.selected_page_id,
            "pages": [dict(page) for page in self.pages],
            "observation_checkpoint": dict(self.observation_checkpoint),
            "authority": dict(self.authority) if self.authority else None,
            "receipt_chain_head": self.receipt_chain_head,
            "pending_preparations": [dict(item) for item in self.pending_preparations],
            "runtime_capabilities": list(self.runtime_capabilities),
            "identity": dict(self.identity) if self.identity else None,
            "mutation": dict(self.mutation) if self.mutation else None,
            "mutation_epoch": self.mutation_epoch,
        }


@dataclass(frozen=True)
class AgentHandoff:
    session_id: str
    agent_id: str
    control_epoch: int
    control_token: str
    receipt_chain_head: str | None
    authority: dict[str, Any] | None
    identity: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "control_epoch": self.control_epoch,
            "control_token": self.control_token,
            "receipt_chain_head": self.receipt_chain_head,
            "authority": dict(self.authority) if self.authority else None,
            "identity": dict(self.identity) if self.identity else None,
        }
