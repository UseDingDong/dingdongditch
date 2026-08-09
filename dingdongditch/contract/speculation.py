"""Bounded, deterministic speculative continuation preparation.

No browser mutation occurs while branches are prepared.  The runtime only
selects exactly one explicitly declared branch whose browser expectations all
pass; it never invents continuations or performs rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from dingdongditch.contract.expectation import Expectation
from dingdongditch.contract.operation import Operation


class BranchSelectionStatus(str, Enum):
    SELECTED = "selected"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"
    STALE = "stale"


@dataclass(frozen=True)
class SpeculativeBranch:
    branch_id: str
    preconditions: tuple[Expectation, ...]
    continuation: Operation

    def validate(self) -> None:
        if not isinstance(self.branch_id, str) or not self.branch_id or len(self.branch_id) > 128:
            raise ValueError("speculative branch id is invalid")
        if not 1 <= len(self.preconditions) <= 8:
            raise ValueError("speculative branch requires one through eight preconditions")
        for condition in self.preconditions:
            if not isinstance(condition, Expectation):
                raise ValueError("speculative branch preconditions are invalid")
            condition.validate()
        if not isinstance(self.continuation, Operation):
            raise ValueError("speculative branch continuation is invalid")
        self.continuation.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        from dingdongditch.machine_contract import _operation_to_dict
        return {
            "branch_id": self.branch_id,
            "preconditions": [condition.describe() for condition in self.preconditions],
            "continuation": _operation_to_dict(self.continuation),
        }


@dataclass(frozen=True)
class SpeculativePlan:
    speculation_id: str
    parent_operation_id: str
    branches: tuple[SpeculativeBranch, ...]
    max_depth: int = 1
    # Legacy sidecars only named their parent by ID.  That is insufficient for
    # execution: another operation could reuse the ID and unlock a branch.
    # New executable graphs carry the exact parent; the field remains optional
    # solely so old documents can still be parsed and reported as unsupported
    # at the execution boundary rather than silently reinterpreted.
    parent_operation: Operation | None = None

    def validate(self) -> None:
        if not isinstance(self.speculation_id, str) or not self.speculation_id or len(self.speculation_id) > 128:
            raise ValueError("speculation id is invalid")
        if not isinstance(self.parent_operation_id, str) or not self.parent_operation_id:
            raise ValueError("speculation parent operation id is invalid")
        if self.parent_operation is not None:
            if not isinstance(self.parent_operation, Operation):
                raise ValueError("speculation parent operation is invalid")
            self.parent_operation.validate()
            if self.parent_operation.operation_id != self.parent_operation_id:
                raise ValueError("speculation parent operation id does not match parent operation")
        if self.max_depth != 1:
            raise ValueError("only one speculative continuation depth is supported")
        if not 1 <= len(self.branches) <= 8:
            raise ValueError("speculation requires one through eight branches")
        ids = [branch.branch_id for branch in self.branches]
        if len(ids) != len(set(ids)):
            raise ValueError("speculative branch ids must be unique")
        for branch in self.branches:
            branch.validate()
            if branch.continuation.operation_id == self.parent_operation_id:
                raise ValueError("speculative continuation cannot recursively reference parent operation")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        result = {
            "speculation_id": self.speculation_id,
            "parent_operation_id": self.parent_operation_id,
            "max_depth": self.max_depth,
            "branches": [branch.to_dict() for branch in self.branches],
        }
        if self.parent_operation is not None:
            from dingdongditch.machine_contract import _operation_to_dict
            result["parent_operation"] = _operation_to_dict(self.parent_operation)
        return result

    def require_execution_binding(self) -> None:
        """Reject legacy ID-only sidecars before they reach browser state."""
        self.validate()
        if self.parent_operation is None:
            raise ValueError("speculation requires an exact parent_operation binding")


@dataclass(frozen=True)
class BranchPreparation:
    token: str
    session_id: str
    speculation_id: str
    parent_operation_id: str
    control_epoch: int
    mutation_epoch: int | None
    expires_at_ms: int
    branch_count: int

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class BranchSelection:
    token: str
    status: BranchSelectionStatus
    branch_id: str | None
    evidence: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"token": self.token, "status": self.status.value, "branch_id": self.branch_id, "evidence": [dict(item) for item in self.evidence]}


@dataclass(frozen=True)
class SpeculationExecutionResult:
    selection: BranchSelection
    prepared_operation: Any | None = None
    operation_result: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection": self.selection.to_dict(),
            "prepared_operation": self.prepared_operation.to_dict() if self.prepared_operation is not None else None,
            "operation_result": self.operation_result.to_dict() if self.operation_result is not None else None,
        }
