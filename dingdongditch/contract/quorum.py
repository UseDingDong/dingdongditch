"""Explicit, source-independent verification quorum contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from dingdongditch.contract.verdict import Verdict


class VerificationPolicy(str, Enum):
    ALL = "all"
    N_OF_M = "n_of_m"


class EvidenceSourceClass(str, Enum):
    DOM_STATE = "dom_state"
    ACCESSIBILITY_STATE = "accessibility_state"
    NETWORK = "network"
    PAGE_STATE = "page_state"
    FILE_STATE = "file_state"
    VISUAL = "visual"
    HOST_CALLBACK = "host_callback"


# Runtime-supported expectation evaluators each have one authoritative source
# class.  A planner-supplied label is not evidence of independence.
_SOURCE_EXPECTATION_TYPES: dict[EvidenceSourceClass, frozenset[str]] = {
    EvidenceSourceClass.DOM_STATE: frozenset({
        "element_exists", "element_visible", "element_in_viewport", "text", "attribute",
    }),
    EvidenceSourceClass.NETWORK: frozenset({"network"}),
    EvidenceSourceClass.PAGE_STATE: frozenset({"url"}),
    EvidenceSourceClass.FILE_STATE: frozenset({"upload_file_names", "upload_file_count"}),
}


@dataclass(frozen=True)
class VerificationCheck:
    verifier_id: str
    expectation_id: str
    evidence_source: EvidenceSourceClass

    def validate(self) -> None:
        if not isinstance(self.verifier_id, str) or not self.verifier_id:
            raise ValueError("verification check verifier_id is required")
        if not isinstance(self.expectation_id, str) or not self.expectation_id:
            raise ValueError("verification check expectation_id is required")
        if not isinstance(self.evidence_source, EvidenceSourceClass):
            raise ValueError("verification check evidence_source is invalid")
        if self.evidence_source is EvidenceSourceClass.HOST_CALLBACK:
            raise ValueError("host_callback requires a bounded verifier adapter, which is not configured")

    def describe(self) -> dict[str, str]:
        return {
            "verifier_id": self.verifier_id,
            "expectation_id": self.expectation_id,
            "evidence_source": self.evidence_source.value,
        }


@dataclass(frozen=True)
class VerificationQuorum:
    policy: VerificationPolicy
    checks: tuple[VerificationCheck, ...]
    required: int | None = None

    def validate(
        self,
        *,
        expectation_ids: Iterable[str] = (),
        expectation_types: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(self.policy, VerificationPolicy):
            raise ValueError("verification quorum policy is invalid")
        if not self.checks:
            raise ValueError("verification quorum requires checks")
        if len(self.checks) > 16:
            raise ValueError("verification quorum exceeds bounded check limit")
        verifier_ids = [check.verifier_id for check in self.checks]
        source_ids = [check.evidence_source for check in self.checks]
        expectation_refs = [check.expectation_id for check in self.checks]
        if len(verifier_ids) != len(set(verifier_ids)):
            raise ValueError("verification quorum verifier_id values must be unique")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("verification quorum cannot count duplicate evidence sources")
        if len(expectation_refs) != len(set(expectation_refs)):
            raise ValueError("verification quorum cannot count one expectation twice")
        declared = set(expectation_ids)
        for check in self.checks:
            check.validate()
            if declared and check.expectation_id not in declared:
                raise ValueError("verification quorum references an undeclared expectation")
            if check.evidence_source not in _SOURCE_EXPECTATION_TYPES:
                raise ValueError("verification quorum evidence source is not supported by this runtime")
            if expectation_types is not None:
                expectation_type = expectation_types.get(check.expectation_id)
                if expectation_type not in _SOURCE_EXPECTATION_TYPES[check.evidence_source]:
                    raise ValueError("verification quorum evidence source does not match its expectation type")
        if self.policy is VerificationPolicy.ALL:
            if self.required is not None:
                raise ValueError("all quorum must not set required")
        elif not isinstance(self.required, int) or isinstance(self.required, bool) or not 1 <= self.required <= len(self.checks):
            raise ValueError("n_of_m quorum required must be between 1 and check count")

    @property
    def required_count(self) -> int:
        return len(self.checks) if self.policy is VerificationPolicy.ALL else int(self.required)

    def describe(self) -> dict[str, Any]:
        return {
            "policy": self.policy.value,
            "required": self.required,
            "checks": [check.describe() for check in self.checks],
        }


@dataclass(frozen=True)
class QuorumResult:
    verdict: Verdict
    required: int
    achieved: int
    checks: tuple[dict[str, Any], ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "required": self.required,
            "achieved": self.achieved,
            "reason": self.reason,
            "checks": [dict(item) for item in self.checks],
        }


def evaluate_quorum(quorum: VerificationQuorum, expectation_results: Iterable[Any]) -> QuorumResult:
    """Apply strict ALL / N_OF_M truth semantics to independent checks."""
    quorum.validate()
    supplied = tuple(expectation_results)
    duplicate_ids = {
        item.expectation_id for item in supplied
        if sum(other.expectation_id == item.expectation_id for other in supplied) > 1
    }
    results = {item.expectation_id: item for item in supplied if item.expectation_id not in duplicate_ids}
    rows: list[dict[str, Any]] = []
    passed = failed = indeterminate = 0
    for check in quorum.checks:
        item = results.get(check.expectation_id)
        expectation_type = getattr(item, "expectation_type", None) if item is not None else None
        source_binding_valid = (
            item is not None
            and expectation_type in _SOURCE_EXPECTATION_TYPES.get(check.evidence_source, frozenset())
            and getattr(item, "freshness_ok", None) is True
        )
        result = item.result if source_binding_valid else "indeterminate"
        if result == "pass":
            passed += 1
        elif result == "fail":
            failed += 1
        else:
            indeterminate += 1
            result = "indeterminate"
        rows.append({
            "verifier_id": check.verifier_id,
            "expectation_id": check.expectation_id,
            "evidence_source": check.evidence_source.value,
            "result": result,
            "source_binding_valid": source_binding_valid,
            "evidence_refs": list(getattr(item, "evidence_refs", ())[:4]) if item is not None else [],
        })
    required = quorum.required_count
    if passed >= required:
        return QuorumResult(Verdict.VERIFIED, required, passed, tuple(rows), "declared quorum achieved")
    if quorum.policy is VerificationPolicy.ALL and failed:
        return QuorumResult(Verdict.NOT_VERIFIED, required, passed, tuple(rows), "an all-required verifier failed")
    if quorum.policy is VerificationPolicy.N_OF_M and passed + indeterminate < required:
        return QuorumResult(Verdict.NOT_VERIFIED, required, passed, tuple(rows), "remaining evidence cannot meet declared quorum")
    return QuorumResult(Verdict.INDETERMINATE, required, passed, tuple(rows), "declared quorum cannot yet be justified")
