from __future__ import annotations

import json

import pytest

from dingdongditch.contract.expectation import (
    Expectation,
    ExpectationType,
    TextMatchMode,
    UrlMatchMode,
)
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    FreshnessPolicy,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan
from dingdongditch.contract.plan import ExecutionPlan


def _base(url: str, **kwargs) -> dict:
    return {"url": url, "timeout_ms": 10_000, "locate_retry_ms": 500, **kwargs}


def _execute_after_explicit_navigation(op: Operation):
    plan = ExecutionPlan(
        plan_id=f"explicit-{op.operation_id}",
        operations=[
            Operation(
                operation_id=f"{op.operation_id}-navigate",
                url=op.url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value=op.url,
                        url_match=UrlMatchMode.EXACT,
                    )
                ],
            ),
            op,
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.steps[1].receipt is not None
    return receipt.steps[1].receipt


def test_navigate_url_expectation_verified(fixture_url):
    op = Operation(
        operation_id="nav-1",
        **_base(fixture_url),
        action=Action(type=ActionType.NAVIGATE),
        expectations=[
            Expectation(
                type=ExpectationType.URL,
                url_value="index.html",
                url_match=UrlMatchMode.CONTAINS,
                expectation_id="e-url",
            )
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.action_executed_successfully is True
    assert receipt.pre_action_observation is not None
    assert receipt.post_action_observation is not None
    assert receipt.pre_action_observation.collected_at_ms <= receipt.action_started_at_ms
    assert receipt.expectation_results[0].result == "pass"


def test_click_attribute_expectation_verified(fixture_url):
    op = Operation(
        operation_id="click-attr",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
                attribute_name="data-state",
                attribute_value="active",
                expectation_id="e-attr",
            )
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.VERIFIED


def test_click_visibility_expectation_verified(fixture_url):
    op = Operation(
        operation_id="click-vis",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ELEMENT_VISIBLE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="result-item"),
                visible=True,
                expectation_id="e-vis",
            )
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.VERIFIED


def test_fill_text_state_expectation_verified(fixture_url):
    op = Operation(
        operation_id="fill-1",
        **_base(fixture_url),
        action=Action(
            type=ActionType.FILL,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
            text="alpha",
        ),
        expectations=[
            Expectation(
                type=ExpectationType.TEXT,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="state-indicator"),
                text_value="filled",
                text_match=TextMatchMode.CONTAINS,
                expectation_id="e-text",
            ),
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="state-indicator"),
                attribute_name="data-state",
                attribute_value="filled",
                expectation_id="e-attr",
            ),
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.VERIFIED


def test_fill_input_value_attribute_expectation_verified(fixture_url):
    """Live input value must be readable via ATTRIBUTE value (not HTML content attr)."""
    op = Operation(
        operation_id="fill-value-1",
        **_base(fixture_url),
        action=Action(
            type=ActionType.FILL,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
            text="alpha",
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
                attribute_name="value",
                attribute_value="alpha",
                expectation_id="e-input-value",
            ),
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.VERIFIED


def test_click_dom_and_network_expectations_verified(fixture_url):
    op = Operation(
        operation_id="net-1",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="network-control"),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="state-indicator"),
                attribute_name="data-state",
                attribute_value="network-done",
                expectation_id="e-dom",
            ),
            Expectation(
                type=ExpectationType.NETWORK,
                network_url_substring="/api/signal",
                network_status=200,
                expectation_id="e-net",
            ),
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.VERIFIED
    kinds = {e.kind.value for e in receipt.evidence}
    assert "network" in kinds
    assert "dom_state" in kinds or "action_result" in kinds


def test_action_ok_expectation_fails_not_verified(fixture_url):
    op = Operation(
        operation_id="not-verified",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="noop-control"),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="state-indicator"),
                attribute_name="data-state",
                attribute_value="active",
                expectation_id="e-fail",
            )
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.action_executed_successfully is True
    assert receipt.verdict == Verdict.NOT_VERIFIED


def test_missing_target_execution_failed(fixture_url):
    op = Operation(
        operation_id="missing",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="does-not-exist"),
        ),
        expectations=[],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.execution_error == "target not found"


def test_ambiguous_target_execution_failed(fixture_url):
    op = Operation(
        operation_id="ambiguous",
        **_base(fixture_url),
        require_unique_target=True,
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="ambiguous-target"),
        ),
        expectations=[],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.execution_error is not None
    assert "ambiguous" in receipt.execution_error


def test_no_expectations_not_falsely_verified(fixture_url):
    op = Operation(
        operation_id="exec-only",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
        ),
        expectations=[],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.action_executed_successfully is True
    assert receipt.verdict == Verdict.INDETERMINATE
    assert receipt.expectations_declared == 0


def test_delayed_visibility_verified(fixture_url):
    op = Operation(
        operation_id="delayed",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="delayed-control"),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ELEMENT_VISIBLE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="result-item"),
                visible=True,
                expectation_id="e-delay",
            )
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.VERIFIED


def test_receipt_serialization_and_timestamps(fixture_url):
    op = Operation(
        operation_id="serialize",
        **_base(fixture_url),
        action=Action(type=ActionType.NAVIGATE),
        expectations=[
            Expectation(
                type=ExpectationType.URL,
                url_value="index.html",
                url_match=UrlMatchMode.CONTAINS,
            )
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    payload = receipt.to_dict()
    encoded = json.dumps(payload, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["verdict"] == Verdict.VERIFIED.value
    assert decoded["schema_version"]
    assert decoded["freshness"]["policy_max_age_ms"] == 5000
    assert isinstance(decoded["evidence"], list)
    assert decoded["started_at_ms"] <= decoded["finished_at_ms"]
    assert any(er.get("evidence_refs") for er in decoded["expectation_results"])


def test_stale_policy_rejects_verification_when_max_age_too_small(fixture_url, monkeypatch):
    """Force verification-time freshness failure without inventing expectations."""
    from dingdongditch.runtime import verifier as verifier_mod

    real = verifier_mod.is_signal_fresh_for_verification

    def always_stale(*args, **kwargs):
        return args[0].kind.value == "url"

    monkeypatch.setattr(verifier_mod, "is_signal_fresh_for_verification", always_stale)

    op = Operation(
        operation_id="stale",
        **_base(fixture_url),
        freshness=FreshnessPolicy(max_age_ms=1),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
                attribute_name="data-state",
                attribute_value="active",
            )
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.INDETERMINATE
    assert receipt.action_executed_successfully is True
    assert any(r.result == "indeterminate" for r in receipt.expectation_results)

    monkeypatch.setattr(verifier_mod, "is_signal_fresh_for_verification", real)


def test_role_name_locator_click(fixture_url):
    op = Operation(
        operation_id="role-click",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Activate Target",
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="target-control"),
                attribute_name="data-state",
                attribute_value="active",
            )
        ],
    )
    receipt = _execute_after_explicit_navigation(op)
    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.target_locator["strategy"] == "role_name"
