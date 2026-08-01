from __future__ import annotations

import pytest

from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.collector import reset_signal_ids_for_tests
from dingdongditch.evidence.models import EvidenceSignal, SignalAvailability, SignalKind
from dingdongditch.runtime.executor import _decide_verdict
from dingdongditch.runtime.freshness import evaluate_freshness
from dingdongditch.contract.operation import FreshnessPolicy


def test_operation_validation_rejects_click_without_locator():
    with pytest.raises(ValueError):
        Action(type=ActionType.CLICK).validate()


def test_role_name_locator_requires_role_and_name():
    with pytest.raises(ValueError):
        Locator(strategy=LocatorStrategy.ROLE_NAME, value="x").validate()


def test_freshness_marks_pre_action_signals_stale():
    policy = FreshnessPolicy(max_age_ms=5000)
    signals = [
        EvidenceSignal(
            signal_id="sig-old",
            kind=SignalKind.URL,
            availability=SignalAvailability.OBSERVED,
            collected_at_ms=100,
            payload={"url": "http://example"},
        )
    ]
    evaluation = evaluate_freshness(
        policy=policy,
        action_started_at_ms=200,
        verification_completed_at_ms=250,
        signals=signals,
        signal_ids_used_for_verification={"sig-old"},
    )
    assert "sig-old" in evaluation.stale_signal_ids


def test_freshness_marks_aged_signals_stale():
    policy = FreshnessPolicy(max_age_ms=10)
    signals = [
        EvidenceSignal(
            signal_id="sig-aged",
            kind=SignalKind.DOM_STATE,
            availability=SignalAvailability.OBSERVED,
            collected_at_ms=100,
            payload={},
        )
    ]
    evaluation = evaluate_freshness(
        policy=policy,
        action_started_at_ms=90,
        verification_completed_at_ms=200,
        signals=signals,
        signal_ids_used_for_verification={"sig-aged"},
    )
    assert "sig-aged" in evaluation.stale_signal_ids


def test_decide_verdict_no_expectations_is_indeterminate_not_verified():
    verdict = _decide_verdict(
        action_ok=True,
        expectations_declared=0,
        expectation_results=[],
        freshness_stale=[],
    )
    assert verdict == Verdict.INDETERMINATE


def test_decide_verdict_stale_is_indeterminate():
    class R:
        result = "pass"

    verdict = _decide_verdict(
        action_ok=True,
        expectations_declared=1,
        expectation_results=[R()],
        freshness_stale=["sig-1"],
    )
    assert verdict == Verdict.INDETERMINATE


def test_reset_signal_ids():
    reset_signal_ids_for_tests()
