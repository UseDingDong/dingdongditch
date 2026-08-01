"""Contract and serialization tests for typed pointer movement."""

from __future__ import annotations

import math

import pytest

from dingdongditch import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    PlanBuilder,
    PointerMoveRequest,
    PointerOrigin,
)
from dingdongditch.plan_json import plan_document_from_dict


def _target() -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value="pointer-target")


def test_pointer_to_element_center_contract():
    action = Action(
        type=ActionType.POINTER_MOVE,
        locator=_target(),
        pointer_request=PointerMoveRequest(
            origin=PointerOrigin.ELEMENT_CENTER,
            steps=12,
        ),
    )
    action.validate()
    assert action.describe()["pointer_request"] == {
        "origin": "element_center",
        "steps": 12,
        "verify_position": True,
    }


def test_pointer_to_element_offset_contract():
    action = Action(
        type=ActionType.POINTER_MOVE,
        locator=_target(),
        pointer_request=PointerMoveRequest(
            origin=PointerOrigin.ELEMENT_OFFSET,
            x=7.5,
            y=9,
            steps=4,
        ),
    )
    action.validate()
    assert action.describe()["pointer_request"]["x"] == 7.5
    assert action.describe()["pointer_request"]["y"] == 9


@pytest.mark.parametrize(
    ("pointer_request", "message"),
    [
        (PointerMoveRequest(PointerOrigin.VIEWPORT, x=-1, y=2), "non-negative"),
        (PointerMoveRequest(PointerOrigin.VIEWPORT, x=1, y=math.inf), "finite"),
        (PointerMoveRequest(PointerOrigin.VIEWPORT, x=True, y=2), "finite"),
        (PointerMoveRequest(PointerOrigin.VIEWPORT, x=1, y=2, steps=0), "steps"),
        (PointerMoveRequest(PointerOrigin.VIEWPORT, x=1, y=2, steps=1001), "steps"),
        (
            PointerMoveRequest(PointerOrigin.ELEMENT_CENTER, x=1, y=None),
            "must not include",
        ),
        (
            PointerMoveRequest(PointerOrigin.ELEMENT_OFFSET, x=None, y=1),
            "required",
        ),
    ],
)
def test_invalid_pointer_coordinates_are_rejected(pointer_request, message):
    with pytest.raises(ValueError, match=message):
        pointer_request.validate()


def test_pointer_target_requirements_are_mode_specific():
    Action(
        type=ActionType.POINTER_MOVE,
        pointer_request=PointerMoveRequest(PointerOrigin.VIEWPORT, x=10, y=20),
    ).validate()
    with pytest.raises(ValueError, match="must not include a locator"):
        Action(
            type=ActionType.POINTER_MOVE,
            locator=_target(),
            pointer_request=PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=10, y=20
            ),
        ).validate()


@pytest.mark.parametrize(
    "extra",
    [
        {"text": "x"},
        {"key": "Enter"},
        {"option_value": "x"},
        {"checked": True},
        {"page_id": "page-x"},
    ],
)
def test_pointer_move_rejects_unrelated_action_fields(extra):
    with pytest.raises(ValueError):
        Action(
            type=ActionType.POINTER_MOVE,
            pointer_request=PointerMoveRequest(
                PointerOrigin.VIEWPORT, x=10, y=20
            ),
            **extra,
        ).validate()
    with pytest.raises(ValueError, match="requires a locator"):
        Action(
            type=ActionType.POINTER_MOVE,
            pointer_request=PointerMoveRequest(PointerOrigin.ELEMENT_CENTER),
        ).validate()


def test_pointer_plan_json_is_deterministic_and_round_trips_public_shape():
    document = {
        "plan": {
            "plan_id": "pointer-replay",
            "operations": [
                {
                    "operation_id": "move",
                    "url": "https://example.test/",
                    "action": {
                        "type": "pointer_move",
                        "locator": {
                            "strategy": "test_id",
                            "value": "pointer-target",
                        },
                        "pointer_request": {
                            "origin": "element_offset",
                            "x": 12.5,
                            "y": 8,
                            "steps": 16,
                            "verify_position": True,
                        },
                    },
                }
            ],
        }
    }
    first = plan_document_from_dict(document)
    second = plan_document_from_dict(document)
    assert first.operations[0].action.describe() == second.operations[0].action.describe()
    assert first.operations[0].action.describe() == document["plan"]["operations"][0]["action"]


def test_pointer_builder_and_existing_builder_api_are_compatible():
    builder = PlanBuilder("pointer-builder")
    returned = builder.pointer_move(
        "move",
        "https://example.test/",
        PointerMoveRequest(PointerOrigin.VIEWPORT, x=100, y=200, steps=5),
    )
    assert returned is builder
    plan = builder.build()
    assert plan.operations[0].action.type == ActionType.POINTER_MOVE

    existing = PlanBuilder("existing").navigate("nav", "https://example.test/").build()
    assert existing.operations[0].action.type == ActionType.NAVIGATE
