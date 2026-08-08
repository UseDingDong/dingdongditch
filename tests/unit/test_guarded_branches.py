"""Unit coverage for bounded, declarative guarded branch contracts."""

from __future__ import annotations

import pytest

from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    GuardBranch,
    Locator,
    LocatorStrategy,
    Operation,
    OperationGuard,
    TargetAbsentGuard,
)
from dingdongditch.plan_json import plan_document_from_dict


def _target(name: str) -> Locator:
    return Locator(LocatorStrategy.TEST_ID, name)


def _exists(name: str, expected: bool = True) -> Expectation:
    return Expectation(
        type=ExpectationType.ELEMENT_EXISTS, locator=_target(name), exists=expected
    )


def _operation(guard: OperationGuard) -> Operation:
    return Operation(
        operation_id="branching",
        url="https://example.test/",
        action=Action(type=ActionType.CLICK, locator=_target("primary")),
        expectations=[_exists("done")],
        guard=guard,
    )


def test_declared_branch_guard_is_valid_and_describes_ordered_actions():
    guard = OperationGuard(
        branches=(
            GuardBranch(
                branch_id="banner-a",
                when=(_exists("banner-a"),),
                execute=(Action(type=ActionType.CLICK, locator=_target("dismiss-a")),),
            ),
            GuardBranch(
                branch_id="banner-b",
                when=(_exists("banner-b"),),
            ),
        ),
        otherwise=(),
    )
    _operation(guard).validate()
    described = guard.describe()
    assert [item["branch_id"] for item in described["branches"]] == [
        "banner-a",
        "banner-b",
    ]
    assert described["branches"][0]["execute"][0]["type"] == "click"
    assert described["otherwise"] == []


def test_branch_guard_rejects_mixed_legacy_and_branches():
    guard = OperationGuard(
        when_target_absent=TargetAbsentGuard((_exists("done", False),)),
        branches=(GuardBranch("present", (_exists("banner"),)),),
    )
    with pytest.raises(ValueError, match="exactly one"):
        _operation(guard).validate()


def test_branch_guard_rejects_unsupported_nested_workflow_action():
    guard = OperationGuard(
        branches=(
            GuardBranch(
                "navigate",
                (_exists("banner"),),
                execute=(Action(type=ActionType.NAVIGATE),),
            ),
        )
    )
    with pytest.raises(ValueError, match="target-based"):
        _operation(guard).validate()


def test_plan_json_parses_declared_branch_guard():
    plan = plan_document_from_dict(
        {
            "browser": {"provider": "playwright", "engine": "chromium", "channel": "bundled"},
            "plan": {
                "plan_id": "branch-json",
                "operations": [
                    {
                        "operation_id": "branch",
                        "url": "https://example.test/",
                        "action": {"type": "click", "locator": {"strategy": "test_id", "value": "primary"}},
                        "guard": {
                            "branches": [
                                {
                                    "branch_id": "banner",
                                    "when": {"expectations": [{"type": "element_exists", "locator": {"strategy": "test_id", "value": "banner"}, "exists": True}]},
                                    "execute": [{"type": "click", "locator": {"strategy": "test_id", "value": "dismiss"}}],
                                }
                            ],
                            "otherwise": [],
                        },
                        "expectations": [{"type": "element_exists", "locator": {"strategy": "test_id", "value": "done"}, "exists": True}],
                    }
                ],
            },
        }
    )
    guard = plan.operations[0].guard
    assert guard is not None
    assert guard.when_target_absent is None
    assert guard.branches[0].branch_id == "banner"
    assert guard.otherwise == ()
