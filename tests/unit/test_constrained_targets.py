"""Unit tests for constrained-target contract validation."""

from __future__ import annotations

import pytest

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
    MAX_WITHIN_DEPTH,
    NameMatchMode,
    TargetConstraint,
)


def test_unconstrained_locator_still_validates():
    Locator(strategy=LocatorStrategy.TEST_ID, value="target-control").validate()
    Locator(
        strategy=LocatorStrategy.ROLE_NAME, role="button", name="Activate Target"
    ).validate()
    Locator(strategy=LocatorStrategy.CSS, value="#target-control").validate()


def test_default_name_match_is_contains_for_role_name():
    loc = Locator(strategy=LocatorStrategy.ROLE_NAME, role="button", name="Execute")
    assert loc.resolved_name_match() == NameMatchMode.CONTAINS
    assert loc.describe()["name_match"] == "contains"


def test_invalid_regex_fails_validation():
    with pytest.raises(ValueError, match="invalid accessible-name regex"):
        Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role="button",
            name="(",
            name_match=NameMatchMode.REGEX,
        ).validate()


def test_empty_exclude_fails_validation():
    with pytest.raises(ValueError, match="exclude constraint requires"):
        Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role="button",
            name="Run",
            constraints=(TargetConstraint(type=ConstraintType.EXCLUDE),),
        ).validate()


def test_contradictory_visible_fails_validation():
    with pytest.raises(ValueError, match="contradictory visible"):
        Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role="button",
            name="Reveal panel",
            constraints=(
                TargetConstraint(type=ConstraintType.VISIBLE, visible=True),
                TargetConstraint(type=ConstraintType.VISIBLE, visible=False),
            ),
        ).validate()


def test_contradictory_enabled_fails_validation():
    with pytest.raises(ValueError, match="contradictory enabled"):
        Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role="button",
            name="Proceed",
            constraints=(
                TargetConstraint(type=ConstraintType.ENABLED, enabled=True),
                TargetConstraint(type=ConstraintType.ENABLED, enabled=False),
            ),
        ).validate()


def test_name_match_rejected_on_css():
    with pytest.raises(ValueError, match="name_match is only valid"):
        Locator(
            strategy=LocatorStrategy.CSS,
            value="button",
            name_match=NameMatchMode.EXACT,
        ).validate()


def test_nested_within_within_max_depth_succeeds():
    assert MAX_WITHIN_DEPTH == 2
    outer = Locator(strategy=LocatorStrategy.TEST_ID, value="outer-region")
    inner = Locator(
        strategy=LocatorStrategy.TEST_ID,
        value="inner-region",
        constraints=(TargetConstraint(type=ConstraintType.WITHIN, within=outer),),
    )
    Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Nested action",
        constraints=(TargetConstraint(type=ConstraintType.WITHIN, within=inner),),
    ).validate()


def test_excessive_within_nesting_rejected():
    outer = Locator(strategy=LocatorStrategy.TEST_ID, value="outer-region")
    inner = Locator(
        strategy=LocatorStrategy.TEST_ID,
        value="inner-region",
        constraints=(TargetConstraint(type=ConstraintType.WITHIN, within=outer),),
    )
    level2 = Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Nested action",
        constraints=(TargetConstraint(type=ConstraintType.WITHIN, within=inner),),
    )
    level3 = Locator(
        strategy=LocatorStrategy.ROLE_NAME,
        role="button",
        name="Nested action",
        constraints=(TargetConstraint(type=ConstraintType.WITHIN, within=level2),),
    )
    with pytest.raises(ValueError, match="within nesting exceeds"):
        level3.validate()


def test_circular_within_rejected_via_seen_ids():
    parent = Locator(strategy=LocatorStrategy.TEST_ID, value="parent")
    child = Locator(
        strategy=LocatorStrategy.TEST_ID,
        value="child",
        constraints=(TargetConstraint(type=ConstraintType.WITHIN, within=parent),),
    )
    with pytest.raises(ValueError, match="circular within"):
        child.validate(seen_ids=frozenset({id(parent)}))


def test_click_rejects_require_unique_false():
    with pytest.raises(ValueError, match="require_unique_target=True"):
        Operation(
            operation_id="x",
            url="http://example",
            require_unique_target=False,
            action=Action(
                type=ActionType.CLICK,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="t"),
            ),
        ).validate()


def test_attribute_exists_rejects_value():
    with pytest.raises(ValueError, match="must not include attribute_value"):
        TargetConstraint(
            type=ConstraintType.ATTRIBUTE,
            attribute_name="data-purpose",
            attribute_operator=AttributeOperator.EXISTS,
            attribute_value="x",
        ).validate()
