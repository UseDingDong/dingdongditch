"""Integration tests for constrained semantic target resolution."""

from __future__ import annotations

from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.target import (
    AttributeOperator,
    ConstraintType,
    NameMatchMode,
    TargetConstraint,
)
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.executor import execute_operation


def _base(url: str, **kwargs) -> dict:
    return {"url": url, "timeout_ms": 10_000, "locate_retry_ms": 300, **kwargs}


def _trace_counts(receipt) -> list[int]:
    assert receipt.target_resolution is not None
    return [s["candidates_after"] for s in receipt.target_resolution["stages"]]


def test_ambiguous_semantic_primary_fails_closed(fixture_url):
    op = Operation(
        operation_id="amb-semantic",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Execute",
                name_match=NameMatchMode.EXACT,
            ),
        ),
        expectations=[],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.action_executed_successfully is False
    assert receipt.target_resolution is not None
    assert receipt.target_resolution["final_candidate_count"] == 2
    assert receipt.target_resolution["dispatch_permitted"] is False
    assert "ambiguous" in (receipt.execution_error or "").lower() or (
        receipt.target_resolution["failure_kind"] == "multiple_after_primary"
    )
    assert len(receipt.target_resolution["candidate_summaries"]) >= 2


def test_within_narrows_to_one_and_verifies(fixture_url):
    op = Operation(
        operation_id="within-1",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Execute",
                name_match=NameMatchMode.EXACT,
                constraints=(
                    TargetConstraint(
                        type=ConstraintType.WITHIN,
                        within=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="region-alpha"
                        ),
                    ),
                ),
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                ),
                attribute_name="data-state",
                attribute_value="alpha-executed",
                expectation_id="e-alpha",
            )
        ],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.target_resolution["dispatch_permitted"] is True
    assert receipt.target_resolution["final_candidate_count"] == 1
    assert _trace_counts(receipt)[0] == 2  # primary
    assert 1 in _trace_counts(receipt)


def test_exact_vs_contains_name_match(fixture_url):
    contains_op = Operation(
        operation_id="name-contains",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Execute",
                name_match=NameMatchMode.CONTAINS,
            ),
        ),
        expectations=[],
    )
    contains_receipt = execute_operation(contains_op)
    assert contains_receipt.verdict == Verdict.EXECUTION_FAILED
    # Execute + Execute later (+ possibly others containing Execute)
    assert contains_receipt.target_resolution["final_candidate_count"] >= 2

    exact_later = Operation(
        operation_id="name-exact-later",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Execute later",
                name_match=NameMatchMode.EXACT,
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ELEMENT_EXISTS,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="execute-later-alpha"
                ),
                exists=True,
                expectation_id="exists",
            )
        ],
    )
    # Click Execute later — no state change expected beyond exists check on itself
    receipt = execute_operation(exact_later)
    assert receipt.action_executed_successfully is True
    assert receipt.target_resolution["final_candidate_count"] == 1
    assert receipt.target_resolution["primary_locator"]["name_match"] == "exact"


def test_attribute_equals_and_exists(fixture_url):
    equals_op = Operation(
        operation_id="attr-eq",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Commit",
                name_match=NameMatchMode.EXACT,
                constraints=(
                    TargetConstraint(
                        type=ConstraintType.ATTRIBUTE,
                        attribute_name="data-purpose",
                        attribute_operator=AttributeOperator.EQUALS,
                        attribute_value="submit-action",
                    ),
                ),
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                ),
                attribute_name="data-state",
                attribute_value="commit-submit",
            )
        ],
    )
    receipt = execute_operation(equals_op)
    assert receipt.verdict == Verdict.VERIFIED

    exists_op = Operation(
        operation_id="attr-exists",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Commit",
                name_match=NameMatchMode.EXACT,
                constraints=(
                    TargetConstraint(
                        type=ConstraintType.ATTRIBUTE,
                        attribute_name="data-purpose",
                        attribute_operator=AttributeOperator.EXISTS,
                    ),
                    TargetConstraint(
                        type=ConstraintType.ATTRIBUTE,
                        attribute_name="data-purpose",
                        attribute_operator=AttributeOperator.EQUALS,
                        attribute_value="preview-action",
                    ),
                ),
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                ),
                attribute_name="data-state",
                attribute_value="commit-preview",
            )
        ],
    )
    receipt2 = execute_operation(exists_op)
    assert receipt2.verdict == Verdict.VERIFIED
    # Ordering: after exists still 2, after equals 1
    after = [s["candidates_after"] for s in receipt2.target_resolution["stages"] if s["stage"] == "constraint"]
    assert after[0] == 2
    assert after[1] == 1


def test_exclude_constraint(fixture_url):
    op = Operation(
        operation_id="exclude-1",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Run task",
                name_match=NameMatchMode.CONTAINS,
                constraints=(
                    TargetConstraint(
                        type=ConstraintType.EXCLUDE,
                        exclude_names_exact=("Run task later", "Cancel task"),
                    ),
                ),
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                ),
                attribute_name="data-state",
                attribute_value="run-task",
            )
        ],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.target_resolution["final_candidate_count"] == 1


def test_visible_constraint_only_when_declared(fixture_url):
    # CSS primary includes hidden duplicates; role queries may omit them.
    no_filter = Operation(
        operation_id="vis-none",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.CSS,
                value="button[aria-label='Reveal panel']",
            ),
        ),
        expectations=[],
    )
    r0 = execute_operation(no_filter)
    assert r0.verdict == Verdict.EXECUTION_FAILED
    assert r0.target_resolution["final_candidate_count"] == 2

    with_visible = Operation(
        operation_id="vis-yes",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.CSS,
                value="button[aria-label='Reveal panel']",
                constraints=(
                    TargetConstraint(type=ConstraintType.VISIBLE, visible=True),
                ),
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                ),
                attribute_name="data-state",
                attribute_value="revealed-visible",
            )
        ],
    )
    r1 = execute_operation(with_visible)
    assert r1.verdict == Verdict.VERIFIED


def test_enabled_constraint_only_when_declared(fixture_url):
    no_filter = Operation(
        operation_id="en-none",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Proceed",
                name_match=NameMatchMode.EXACT,
            ),
        ),
        expectations=[],
    )
    r0 = execute_operation(no_filter)
    assert r0.verdict == Verdict.EXECUTION_FAILED
    assert r0.target_resolution["final_candidate_count"] == 2

    enabled = Operation(
        operation_id="en-yes",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Proceed",
                name_match=NameMatchMode.EXACT,
                constraints=(
                    TargetConstraint(type=ConstraintType.ENABLED, enabled=True),
                ),
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                ),
                attribute_name="data-state",
                attribute_value="proceeded",
            )
        ],
    )
    r1 = execute_operation(enabled)
    assert r1.verdict == Verdict.VERIFIED


def test_constraints_still_ambiguous_fails(fixture_url):
    op = Operation(
        operation_id="still-amb",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Twin control",
                name_match=NameMatchMode.EXACT,
                constraints=(
                    TargetConstraint(type=ConstraintType.VISIBLE, visible=True),
                ),
            ),
        ),
        expectations=[],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.target_resolution["failure_kind"] == "multiple_after_constraints"
    assert receipt.target_resolution["final_candidate_count"] == 2
    assert receipt.target_resolution["dispatch_permitted"] is False


def test_constraints_zero_matches_fails(fixture_url):
    op = Operation(
        operation_id="zero-after",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Execute",
                name_match=NameMatchMode.EXACT,
                constraints=(
                    TargetConstraint(
                        type=ConstraintType.ATTRIBUTE,
                        attribute_name="data-purpose",
                        attribute_operator=AttributeOperator.EQUALS,
                        attribute_value="does-not-exist",
                    ),
                ),
            ),
        ),
        expectations=[],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.target_resolution["failure_kind"] in (
        "zero_after_constraints",
        "missing_container",
    )
    assert receipt.target_resolution["final_candidate_count"] == 0
    assert receipt.action_executed_successfully is False


def test_ambiguous_container_fails(fixture_url):
    op = Operation(
        operation_id="amb-container",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Boxed action",
                name_match=NameMatchMode.EXACT,
                constraints=(
                    TargetConstraint(
                        type=ConstraintType.WITHIN,
                        within=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="dup-container"
                        ),
                    ),
                ),
            ),
        ),
        expectations=[],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.target_resolution["failure_kind"] == "ambiguous_container"
    assert receipt.target_resolution["dispatch_permitted"] is False


def test_nested_within_click_verified(fixture_url):
    op = Operation(
        operation_id="nested-within",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Nested action",
                name_match=NameMatchMode.EXACT,
                constraints=(
                    TargetConstraint(
                        type=ConstraintType.WITHIN,
                        within=Locator(
                            strategy=LocatorStrategy.TEST_ID,
                            value="inner-region",
                            constraints=(
                                TargetConstraint(
                                    type=ConstraintType.WITHIN,
                                    within=Locator(
                                        strategy=LocatorStrategy.TEST_ID,
                                        value="outer-region",
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                ),
                attribute_name="data-state",
                attribute_value="nested-clicked",
            )
        ],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.VERIFIED


def test_css_locator_still_works(fixture_url):
    op = Operation(
        operation_id="css-ok",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.CSS, value="#target-control"),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="target-control"
                ),
                attribute_name="data-state",
                attribute_value="active",
            )
        ],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.VERIFIED


def test_no_first_match_on_ambiguous(fixture_url):
    op = Operation(
        operation_id="no-first",
        **_base(fixture_url),
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(
                strategy=LocatorStrategy.ROLE_NAME,
                role="button",
                name="Execute",
                name_match=NameMatchMode.EXACT,
            ),
        ),
        expectations=[
            Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(
                    strategy=LocatorStrategy.TEST_ID, value="state-indicator"
                ),
                attribute_name="data-state",
                attribute_value="alpha-executed",
            )
        ],
    )
    receipt = execute_operation(op)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    # State must remain idle — no silent click of the first Execute.
    assert receipt.action_executed_successfully is False
