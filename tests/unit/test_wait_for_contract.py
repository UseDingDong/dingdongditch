"""Unit tests for wait_for contracts."""

from __future__ import annotations

import pytest

from dingdongditch.contract.expectation import TextMatchMode, UrlMatchMode
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.wait import (
    DEFAULT_WAIT_TIMEOUT_MS,
    MAX_WAIT_TIMEOUT_MS,
    LoadState,
    WaitCondition,
    WaitConditionType,
    validate_wait_timeout_ms,
)


def _loc(value: str = "x") -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def test_wait_for_serializable_and_default_timeout():
    action = Action(
        type=ActionType.WAIT_FOR,
        wait_condition=WaitCondition(
            type=WaitConditionType.ELEMENT_VISIBLE, locator=_loc()
        ),
    )
    action.validate()
    desc = action.describe()
    assert desc["type"] == "wait_for"
    assert desc["wait_timeout_ms"] == DEFAULT_WAIT_TIMEOUT_MS
    assert desc["wait_condition"]["type"] == "element_visible"


def test_each_condition_validates():
    cases = [
        WaitCondition(type=WaitConditionType.ELEMENT_VISIBLE, locator=_loc()),
        WaitCondition(type=WaitConditionType.ELEMENT_HIDDEN, locator=_loc()),
        WaitCondition(
            type=WaitConditionType.TEXT_PRESENT,
            locator=_loc(),
            text_value="hi",
            text_match=TextMatchMode.EXACT,
        ),
        WaitCondition(
            type=WaitConditionType.URL_MATCHES,
            url_value="index.html",
            url_match=UrlMatchMode.CONTAINS,
        ),
        WaitCondition(
            type=WaitConditionType.ATTRIBUTE_EQUALS,
            locator=_loc(),
            attribute_name="data-phase",
            attribute_value="ready",
        ),
        WaitCondition(
            type=WaitConditionType.VALUE_EQUALS, locator=_loc(), value="v"
        ),
        WaitCondition(
            type=WaitConditionType.CHECKED_EQUALS, locator=_loc(), checked=True
        ),
        WaitCondition(
            type=WaitConditionType.SELECTED_VALUE_EQUALS,
            locator=_loc(),
            selected_value="later",
        ),
        WaitCondition(
            type=WaitConditionType.ELEMENT_IN_VIEWPORT,
            locator=_loc(),
            in_viewport=True,
        ),
        WaitCondition(
            type=WaitConditionType.LOAD_STATE, load_state=LoadState.DOMCONTENTLOADED
        ),
        WaitCondition(type=WaitConditionType.VIDEO_ENDED, locator=_loc()),
    ]
    for cond in cases:
        Action(type=ActionType.WAIT_FOR, wait_condition=cond).validate()


def test_video_ended_requires_locator():
    with pytest.raises(ValueError, match="requires a locator"):
        WaitCondition(type=WaitConditionType.VIDEO_ENDED).validate()
    with pytest.raises(ValueError, match="must not include"):
        WaitCondition(
            type=WaitConditionType.VIDEO_ENDED,
            locator=_loc(),
            text_value="x",
        ).validate()


def test_missing_condition_and_bad_timeouts():
    with pytest.raises(ValueError, match="wait_condition"):
        Action(type=ActionType.WAIT_FOR).validate()
    with pytest.raises(ValueError):
        validate_wait_timeout_ms(0)
    with pytest.raises(ValueError):
        validate_wait_timeout_ms(MAX_WAIT_TIMEOUT_MS + 1)
    with pytest.raises(ValueError):
        Action(
            type=ActionType.WAIT_FOR,
            wait_condition=WaitCondition(
                type=WaitConditionType.ELEMENT_VISIBLE, locator=_loc()
            ),
            wait_timeout_ms=MAX_WAIT_TIMEOUT_MS + 1,
        ).validate()


def test_target_rules():
    with pytest.raises(ValueError, match="requires a locator"):
        WaitCondition(type=WaitConditionType.ELEMENT_VISIBLE).validate()
    with pytest.raises(ValueError, match="must not include a locator"):
        WaitCondition(
            type=WaitConditionType.URL_MATCHES,
            locator=_loc(),
            url_value="x",
        ).validate()
    with pytest.raises(ValueError, match="wait_condition"):
        Action(
            type=ActionType.WAIT_FOR,
            locator=_loc(),
            wait_condition=WaitCondition(
                type=WaitConditionType.ELEMENT_VISIBLE, locator=_loc()
            ),
        ).validate()


def test_operation_requires_unique_for_target_waits():
    with pytest.raises(ValueError, match="require_unique_target"):
        Operation(
            operation_id="w",
            url="https://example.com",
            action=Action(
                type=ActionType.WAIT_FOR,
                wait_condition=WaitCondition(
                    type=WaitConditionType.ELEMENT_VISIBLE, locator=_loc()
                ),
            ),
            require_unique_target=False,
        ).validate()


def test_click_rejects_wait_fields():
    with pytest.raises(ValueError, match="wait_for fields"):
        Action(
            type=ActionType.CLICK,
            locator=_loc(),
            wait_timeout_ms=1000,
        ).validate()
