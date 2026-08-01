"""Unit tests for optional iframe frame targeting on actions/waits."""

from __future__ import annotations

import pytest

from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    KeyPressScope,
    Locator,
    LocatorStrategy,
)
from dingdongditch.contract.wait import WaitCondition, WaitConditionType
from dingdongditch.plan_json import plan_document_from_dict


def _tid(v: str) -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=v)


def test_action_frame_allowed_on_click():
    Action(type=ActionType.CLICK, locator=_tid("a"), frame=_tid("f")).validate()


def test_navigate_rejects_frame():
    with pytest.raises(ValueError, match="must not include a frame"):
        Action(type=ActionType.NAVIGATE, frame=_tid("f")).validate()


def test_wait_for_rejects_action_frame():
    with pytest.raises(ValueError, match="wait_condition"):
        Action(
            type=ActionType.WAIT_FOR,
            frame=_tid("f"),
            wait_condition=WaitCondition(
                type=WaitConditionType.ELEMENT_VISIBLE,
                locator=_tid("a"),
            ),
        ).validate()


def test_wait_condition_frame_on_element_wait():
    WaitCondition(
        type=WaitConditionType.ELEMENT_VISIBLE,
        locator=_tid("a"),
        frame=_tid("f"),
    ).validate()


def test_load_state_rejects_frame():
    from dingdongditch.contract.wait import LoadState

    with pytest.raises(ValueError, match="page-scoped"):
        WaitCondition(
            type=WaitConditionType.LOAD_STATE,
            load_state=LoadState.LOAD,
            frame=_tid("f"),
        ).validate()


def test_press_key_active_page_rejects_frame():
    with pytest.raises(ValueError, match="must not include a frame"):
        Action(
            type=ActionType.PRESS_KEY,
            key="Enter",
            key_scope=KeyPressScope.ACTIVE_PAGE,
            frame=_tid("f"),
        ).validate()


def test_expectation_frame_describe():
    exp = Expectation(
        type=ExpectationType.ATTRIBUTE,
        locator=_tid("a"),
        frame=_tid("f"),
        attribute_name="value",
        attribute_value="x",
    )
    exp.validate()
    d = exp.describe()
    assert d["frame"]["value"] == "f"


def test_plan_json_parses_frame_on_action_and_wait():
    doc = {
        "browser": {
            "provider": "playwright",
            "engine": "chromium",
            "channel": "bundled",
            "headless": True,
        },
        "plan": {
            "plan_id": "frame-unit",
            "failure_policy": "stop_on_failure",
            "operations": [
                {
                    "operation_id": "click",
                    "url": "https://example.com/",
                    "action": {
                        "type": "click",
                        "locator": {"strategy": "test_id", "value": "inner"},
                        "frame": {"strategy": "test_id", "value": "frame"},
                    },
                    "expectations": [],
                },
                {
                    "operation_id": "wait",
                    "url": "https://example.com/",
                    "action": {
                        "type": "wait_for",
                        "wait_condition": {
                            "type": "element_visible",
                            "locator": {"strategy": "test_id", "value": "inner"},
                            "frame": {"strategy": "test_id", "value": "frame"},
                        },
                    },
                    "expectations": [],
                },
            ],
        },
    }
    plan = plan_document_from_dict(doc)
    assert plan.operations[0].action.frame.value == "frame"
    assert plan.operations[1].action.wait_condition.frame.value == "frame"
