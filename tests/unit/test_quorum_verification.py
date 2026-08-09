from __future__ import annotations

import pytest

from dingdongditch import (
    Action, ActionType, EvidenceSourceClass, Expectation, ExpectationType,
    Operation, VerificationCheck, VerificationPolicy, VerificationQuorum,
    evaluate_quorum,
)
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.models import ExpectationResult


def _result(identifier: str, result: str) -> ExpectationResult:
    expectation_type = {"dom": "attribute", "network": "network", "page": "url"}[identifier]
    return ExpectationResult(
        expectation_id=identifier, expectation_type=expectation_type, expected={}, observed={}, result=result,
        evidence_refs=[f"sig-{identifier}"], evidence_timestamp_ms=1,
        explanation=result, freshness_ok=True, failure_evidence=None,
    )


def _quorum(policy=VerificationPolicy.N_OF_M, required=2) -> VerificationQuorum:
    return VerificationQuorum(
        policy=policy,
        required=(None if policy is VerificationPolicy.ALL else required),
        checks=(
            VerificationCheck("dom", "dom", EvidenceSourceClass.DOM_STATE),
            VerificationCheck("network", "network", EvidenceSourceClass.NETWORK),
            VerificationCheck("page", "page", EvidenceSourceClass.PAGE_STATE),
        ),
    )


def test_all_and_exact_n_of_m_quorum_passes_with_independent_sources():
    results = [_result("dom", "pass"), _result("network", "pass"), _result("page", "pass")]
    assert evaluate_quorum(_quorum(VerificationPolicy.ALL), results).verdict is Verdict.VERIFIED
    exact = evaluate_quorum(_quorum(required=2), results[:2])
    assert exact.verdict is Verdict.VERIFIED
    assert exact.achieved == 2 and {row["evidence_source"] for row in exact.checks} == {"dom_state", "network", "page_state"}


def test_quorum_not_met_and_indeterminate_truth_semantics():
    quorum = _quorum(required=2)
    assert evaluate_quorum(quorum, [_result("dom", "pass"), _result("network", "fail"), _result("page", "fail")]).verdict is Verdict.NOT_VERIFIED
    assert evaluate_quorum(quorum, [_result("dom", "pass"), _result("network", "indeterminate")]).verdict is Verdict.INDETERMINATE
    assert evaluate_quorum(_quorum(VerificationPolicy.ALL), [_result("dom", "pass"), _result("network", "fail"), _result("page", "indeterminate")]).verdict is Verdict.NOT_VERIFIED


def test_duplicate_evidence_sources_are_rejected_and_legacy_expectations_remain_valid():
    duplicate = VerificationQuorum(
        policy=VerificationPolicy.N_OF_M, required=2,
        checks=(
            VerificationCheck("one", "a", EvidenceSourceClass.DOM_STATE),
            VerificationCheck("two", "b", EvidenceSourceClass.DOM_STATE),
        ),
    )
    with pytest.raises(ValueError, match="duplicate evidence sources"):
        duplicate.validate(expectation_ids=("a", "b"))

    legacy = Operation(
        "legacy", "https://example.test", Action(ActionType.NAVIGATE),
        expectations=[Expectation(expectation_id="url", type=ExpectationType.URL, url_value="https://example.test")],
    )
    legacy.validate()
    assert legacy.verification_quorum is None


def test_dom_network_agreement_and_disagreement_are_explicit():
    quorum = VerificationQuorum(
        policy=VerificationPolicy.ALL,
        checks=(
            VerificationCheck("dom", "dom", EvidenceSourceClass.DOM_STATE),
            VerificationCheck("network", "network", EvidenceSourceClass.NETWORK),
        ),
    )
    assert evaluate_quorum(quorum, [_result("dom", "pass"), _result("network", "pass")]).verdict is Verdict.VERIFIED
    assert evaluate_quorum(quorum, [_result("dom", "fail"), _result("network", "pass")]).verdict is Verdict.NOT_VERIFIED
    assert evaluate_quorum(quorum, [_result("dom", "pass"), _result("network", "fail")]).verdict is Verdict.NOT_VERIFIED
