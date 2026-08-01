"""Unit tests for ExecutionPlan validation and aggregation."""

from __future__ import annotations

import pytest

from dingdongditch.contract.browser import BrowserChannel, BrowserConfig, BrowserEngine
from dingdongditch.contract.operation import Action, ActionType, Operation
from dingdongditch.contract.plan import (
    CompletionStatus,
    ExecutionPlan,
    FailurePolicy,
    PlanStepRecord,
    PlanVerdict,
    aggregate_plan_outcome,
)
from dingdongditch.contract.verdict import Verdict


def _op(oid: str) -> Operation:
    return Operation(
        operation_id=oid,
        url="https://example.com",
        action=Action(type=ActionType.NAVIGATE),
    )


def test_plan_rejects_empty_id():
    with pytest.raises(ValueError, match="plan_id"):
        ExecutionPlan(plan_id="", operations=[_op("a")]).validate()


def test_plan_rejects_zero_operations():
    with pytest.raises(ValueError, match="at least one"):
        ExecutionPlan(plan_id="p", operations=[]).validate()


def test_plan_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate"):
        ExecutionPlan(plan_id="p", operations=[_op("a"), _op("a")]).validate()


def test_plan_rejects_unsupported_browser():
    with pytest.raises(Exception):
        ExecutionPlan(
            plan_id="p",
            browser_config=BrowserConfig(channel=BrowserChannel.CHROME),
            operations=[_op("a")],
        ).validate()


def test_aggregate_all_verified():
    steps = [
        PlanStepRecord(
            step_index=0,
            operation_id="a",
            attempted=True,
            skipped=False,
            operation_verdict=Verdict.VERIFIED.value,
        ),
        PlanStepRecord(
            step_index=1,
            operation_id="b",
            attempted=True,
            skipped=False,
            operation_verdict=Verdict.VERIFIED.value,
        ),
    ]
    v, c, d_i, d_o, fk = aggregate_plan_outcome(
        steps=steps, declared_count=2, setup_failed=False
    )
    assert v == PlanVerdict.VERIFIED
    assert c == CompletionStatus.COMPLETED
    assert d_i is None


def test_aggregate_stopped_not_verified():
    steps = [
        PlanStepRecord(
            step_index=0,
            operation_id="a",
            attempted=True,
            skipped=False,
            operation_verdict=Verdict.VERIFIED.value,
        ),
        PlanStepRecord(
            step_index=1,
            operation_id="b",
            attempted=True,
            skipped=False,
            operation_verdict=Verdict.NOT_VERIFIED.value,
        ),
        PlanStepRecord(
            step_index=2,
            operation_id="c",
            attempted=False,
            skipped=True,
            skip_reason="prior_step_prevented_execution",
        ),
    ]
    v, c, d_i, d_o, fk = aggregate_plan_outcome(
        steps=steps, declared_count=3, setup_failed=False
    )
    assert v == PlanVerdict.NOT_VERIFIED
    assert c == CompletionStatus.STOPPED
    assert d_i == 1
    assert d_o == "b"


def test_default_failure_policy():
    assert ExecutionPlan(plan_id="p", operations=[_op("a")]).failure_policy == (
        FailurePolicy.STOP_ON_FAILURE
    )
