"""Unit tests for new basic interaction action contracts."""

from __future__ import annotations

import pytest

from dingdongditch.contract.operation import (
    Action,
    ActionType,
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
    SelectMode,
    validate_key_string,
)


def test_press_key_target_default_scope():
    a = Action(
        type=ActionType.PRESS_KEY,
        key="Enter",
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="key-input"),
    )
    a.validate()
    assert a.resolved_key_scope() == KeyPressScope.TARGET
    assert a.describe()["key"] == "Enter"


def test_press_key_active_page_forbids_locator():
    with pytest.raises(ValueError, match="active_page"):
        Action(
            type=ActionType.PRESS_KEY,
            key="Escape",
            key_scope=KeyPressScope.ACTIVE_PAGE,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="x"),
        ).validate()


def test_press_key_target_requires_locator():
    with pytest.raises(ValueError, match="requires a locator"):
        Action(type=ActionType.PRESS_KEY, key="Enter").validate()


def test_press_key_empty_and_malformed():
    with pytest.raises(ValueError):
        validate_key_string("")
    with pytest.raises(ValueError):
        validate_key_string("Control+")
    with pytest.raises(ValueError):
        validate_key_string("NotARealKey")


def test_press_key_chord_preserved():
    validate_key_string("Control+A")
    validate_key_string("Meta+A")
    validate_key_string("Shift+Tab")
    validate_key_string("!")
    validate_key_string(".")


def test_select_option_value_or_label_xor():
    Action(
        type=ActionType.SELECT_OPTION,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="color-select"),
        option_value="red",
    ).validate()
    Action(
        type=ActionType.SELECT_OPTION,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="color-select"),
        option_label="Azure",
    ).validate()
    Action(
        type=ActionType.SELECT_OPTION,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="multi-color-select"),
        option_values=("red", "green"),
    ).validate()
    with pytest.raises(ValueError, match="exactly one"):
        Action(
            type=ActionType.SELECT_OPTION,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="color-select"),
            option_value="red",
            option_label="Crimson",
        ).validate()
    with pytest.raises(ValueError, match="exactly one"):
        Action(
            type=ActionType.SELECT_OPTION,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="color-select"),
            option_value="red",
            option_values=("green",),
        ).validate()
    with pytest.raises(ValueError, match="exactly one"):
        Action(
            type=ActionType.SELECT_OPTION,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="color-select"),
        ).validate()
    with pytest.raises(ValueError, match="non-empty"):
        Action(
            type=ActionType.SELECT_OPTION,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="multi-color-select"),
            option_values=(),
        ).validate()


def test_set_checked_requires_bool():
    Action(
        type=ActionType.SET_CHECKED,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="agree-box"),
        checked=True,
    ).validate()
    with pytest.raises(ValueError, match="checked"):
        Action(
            type=ActionType.SET_CHECKED,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="agree-box"),
        ).validate()


def test_hover_and_scroll_require_locator():
    Action(
        type=ActionType.HOVER,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="hover-target"),
    ).validate()
    Action(
        type=ActionType.SCROLL_TO_TARGET,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="below-fold"),
    ).validate()
    with pytest.raises(ValueError):
        Action(type=ActionType.HOVER).validate()


def test_action_serialization_describe():
    a = Action(
        type=ActionType.SELECT_OPTION,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="color-select"),
        option_value="green",
    )
    d = a.describe()
    assert d["type"] == "select_option"
    assert d["select_mode"] == SelectMode.VALUE.value
    assert d["option_value"] == "green"


def test_operation_unique_target_for_new_actions():
    with pytest.raises(ValueError, match="require_unique_target"):
        Operation(
            operation_id="x",
            url="https://example.com",
            action=Action(
                type=ActionType.HOVER,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="h"),
            ),
            require_unique_target=False,
        ).validate()
