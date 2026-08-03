"""Host-declared target constraints and resolution-trace models.

Index / positional selection is intentionally unsupported: DOM order is unstable
and first-match selection would violate fail-closed uniqueness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dingdongditch.contract.operation import Locator

MAX_WITHIN_DEPTH = 2


class NameMatchMode(str, Enum):
    """Accessible-name matching for role_name primary locators."""

    EXACT = "exact"
    CONTAINS = "contains"
    REGEX = "regex"


class AttributeOperator(str, Enum):
    EQUALS = "equals"
    EXISTS = "exists"
    NOT_EQUALS = "not_equals"


class CardinalityPolicy(str, Enum):
    """Final candidate cardinality required before action dispatch."""

    EXACTLY_ONE = "exactly_one"


class ConstraintType(str, Enum):
    WITHIN = "within"
    ATTRIBUTE = "attribute"
    VISIBLE = "visible"
    ENABLED = "enabled"
    EXCLUDE = "exclude"


@dataclass(frozen=True)
class TargetConstraint:
    """One host-declared narrowing step. Applied in declaration order."""

    type: ConstraintType
    within: Any | None = None  # Locator; typed loosely to avoid import cycle at runtime
    attribute_name: str | None = None
    attribute_operator: AttributeOperator | None = None
    attribute_value: str | None = None
    visible: bool | None = None
    enabled: bool | None = None
    exclude_names_exact: tuple[str, ...] = ()
    exclude_names_contains: tuple[str, ...] = ()
    exclude_attribute_name: str | None = None
    exclude_attribute_value: str | None = None
    exclude_css: str | None = None

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type.value}
        if self.type == ConstraintType.WITHIN:
            data["within"] = self.within.describe() if self.within is not None else None
        elif self.type == ConstraintType.ATTRIBUTE:
            data["attribute_name"] = self.attribute_name
            data["attribute_operator"] = (
                self.attribute_operator.value if self.attribute_operator else None
            )
            data["attribute_value"] = self.attribute_value
        elif self.type == ConstraintType.VISIBLE:
            data["visible"] = self.visible
        elif self.type == ConstraintType.ENABLED:
            data["enabled"] = self.enabled
        elif self.type == ConstraintType.EXCLUDE:
            if self.exclude_names_exact:
                data["exclude_names_exact"] = list(self.exclude_names_exact)
            if self.exclude_names_contains:
                data["exclude_names_contains"] = list(self.exclude_names_contains)
            if self.exclude_attribute_name is not None:
                data["exclude_attribute_name"] = self.exclude_attribute_name
                data["exclude_attribute_value"] = self.exclude_attribute_value
            if self.exclude_css:
                data["exclude_css"] = self.exclude_css
        return data

    def validate(self, *, within_depth: int = 0, seen_ids: frozenset[int] | None = None) -> None:
        seen = set(seen_ids or ())
        if self.type == ConstraintType.WITHIN:
            if self.within is None:
                raise ValueError("within constraint requires a container locator")
            if within_depth >= MAX_WITHIN_DEPTH:
                raise ValueError(
                    f"within nesting exceeds max depth {MAX_WITHIN_DEPTH}"
                )
            # Pass ancestor ids only; the container adds itself when validate() enters.
            self.within.validate(
                within_depth=within_depth + 1,
                seen_ids=frozenset(seen),
            )
        elif self.type == ConstraintType.ATTRIBUTE:
            if not self.attribute_name:
                raise ValueError("attribute constraint requires attribute_name")
            if self.attribute_operator is None:
                raise ValueError("attribute constraint requires attribute_operator")
            if self.attribute_operator == AttributeOperator.EXISTS:
                if self.attribute_value is not None:
                    raise ValueError("attribute exists must not include attribute_value")
            else:
                if self.attribute_value is None:
                    raise ValueError(
                        f"attribute {self.attribute_operator.value} requires attribute_value"
                    )
        elif self.type == ConstraintType.VISIBLE:
            if self.visible is None:
                raise ValueError("visible constraint requires visible bool")
        elif self.type == ConstraintType.ENABLED:
            if self.enabled is None:
                raise ValueError("enabled constraint requires enabled bool")
        elif self.type == ConstraintType.EXCLUDE:
            has_predicate = bool(
                self.exclude_names_exact
                or self.exclude_names_contains
                or self.exclude_css
                or (
                    self.exclude_attribute_name is not None
                    and self.exclude_attribute_value is not None
                )
            )
            if not has_predicate:
                raise ValueError("exclude constraint requires at least one predicate")
            if (
                self.exclude_attribute_name is not None
                and self.exclude_attribute_value is None
            ):
                raise ValueError("exclude attribute requires exclude_attribute_value")
            if (
                self.exclude_attribute_value is not None
                and self.exclude_attribute_name is None
            ):
                raise ValueError("exclude attribute requires exclude_attribute_name")
            if self.exclude_css is not None and not str(self.exclude_css).strip():
                raise ValueError("exclude_css must not be empty")
        else:
            raise ValueError(f"unsupported constraint type: {self.type}")


@dataclass
class ResolutionStage:
    stage: str
    candidates_before: int
    candidates_after: int
    timestamp_ms: int
    constraint: dict[str, Any] | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "constraint": self.constraint,
            "candidates_before": self.candidates_before,
            "candidates_after": self.candidates_after,
            "timestamp_ms": self.timestamp_ms,
            "notes": self.notes,
        }


@dataclass
class TargetResolutionTrace:
    primary_locator: dict[str, Any]
    stages: list[ResolutionStage] = field(default_factory=list)
    final_candidate_count: int = 0
    cardinality_policy: str = CardinalityPolicy.EXACTLY_ONE.value
    cardinality_passed: bool = False
    dispatch_permitted: bool = False
    failure_reason: str | None = None
    failure_kind: str | None = None
    backend_identity: str = "playwright-sync"
    candidate_summaries: list[dict[str, Any]] = field(default_factory=list)
    # Present when resolution was scoped to a declared iframe element.
    frame_locator: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        stages: list[dict[str, Any]] = []
        for item in self.stages:
            serialized = item.to_dict()
            stages.append(serialized)
            # Preserve the established public constraint-stage vocabulary
            # alongside the newer two-phase trace names.
            if item.stage in {"identity_constraint", "actionability_constraint"}:
                stages.append({
                    **serialized,
                    "stage": "constraint",
                    "phase": item.stage.removesuffix("_constraint"),
                })
        data = {
            "primary_locator": self.primary_locator,
            "stages": stages,
            "final_candidate_count": self.final_candidate_count,
            "cardinality_policy": self.cardinality_policy,
            "cardinality_passed": self.cardinality_passed,
            "dispatch_permitted": self.dispatch_permitted,
            "failure_reason": self.failure_reason,
            "failure_kind": self.failure_kind,
            "backend_identity": self.backend_identity,
            "candidate_summaries": list(self.candidate_summaries),
        }
        if self.frame_locator is not None:
            data["frame_locator"] = self.frame_locator
        return data


def validate_constraint_list(
    constraints: tuple[TargetConstraint, ...],
    *,
    within_depth: int = 0,
    seen_ids: frozenset[int] | None = None,
) -> None:
    visible_values: list[bool] = []
    enabled_values: list[bool] = []
    for constraint in constraints:
        constraint.validate(within_depth=within_depth, seen_ids=seen_ids)
        if constraint.type == ConstraintType.VISIBLE:
            assert constraint.visible is not None
            visible_values.append(constraint.visible)
        if constraint.type == ConstraintType.ENABLED:
            assert constraint.enabled is not None
            enabled_values.append(constraint.enabled)
    if len(set(visible_values)) > 1:
        raise ValueError("contradictory visible constraints")
    if len(set(enabled_values)) > 1:
        raise ValueError("contradictory enabled constraints")


def compile_name_regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid accessible-name regex: {exc}") from exc
