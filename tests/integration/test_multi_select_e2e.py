"""Integration and contract tests for multi-select select_option."""

from __future__ import annotations

import pytest

from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
)
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.plan import ExecutionPlan, PlanVerdict
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.plan_executor import execute_plan


def _cfg(engine: BrowserEngine) -> BrowserConfig:
    return BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=engine,
        channel=BrowserChannel.BUNDLED,
        headless=True,
    )


def _tid(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def _nav(url: str) -> Operation:
    return Operation(
        operation_id="nav",
        url=url,
        action=Action(type=ActionType.NAVIGATE),
        expectations=[
            Expectation(
                type=ExpectationType.URL,
                url_value="index.html",
                url_match=UrlMatchMode.CONTAINS,
            )
        ],
    )


def test_select_option_value_and_values_together_fail_validation():
    with pytest.raises(ValueError, match="exactly one"):
        Action(
            type=ActionType.SELECT_OPTION,
            locator=_tid("multi-color-select"),
            option_value="red",
            option_values=("green",),
        ).validate()


def test_select_option_empty_values_fail_validation():
    with pytest.raises(ValueError, match="non-empty"):
        Action(
            type=ActionType.SELECT_OPTION,
            locator=_tid("multi-color-select"),
            option_values=(),
        ).validate()


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
    ids=["chromium", "firefox", "webkit"],
)
def test_scalar_select_option_unchanged(fixture_url, engine):
    plan = ExecutionPlan(
        plan_id=f"scalar-select-{engine.value}",
        browser_config=_cfg(engine),
        operations=[
            _nav(fixture_url),
            Operation(
                operation_id="select",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=_tid("color-select"),
                    option_value="green",
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.TEXT,
                        locator=_tid("select-output"),
                        text_value="Emerald",
                        text_match=TextMatchMode.EXACT,
                    )
                ],
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    step = next(s for s in receipt.steps if s.operation_id == "select")
    assert step.receipt is not None
    assert step.receipt.action_evidence["select_mode"] == "value"
    assert step.receipt.action_evidence["selected_value"] == "green"
    assert step.receipt.action_evidence["selected_values"] == ["green"]


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
    ids=["chromium", "firefox", "webkit"],
)
def test_multi_select_values_succeed(fixture_url, engine):
    plan = ExecutionPlan(
        plan_id=f"multi-select-{engine.value}",
        browser_config=_cfg(engine),
        operations=[
            _nav(fixture_url),
            Operation(
                operation_id="select-multi",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=_tid("multi-color-select"),
                    option_values=("red", "blue"),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=_tid("multi-select-output"),
                        attribute_name="data-value",
                        attribute_value="red,blue",
                    )
                ],
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    step = next(s for s in receipt.steps if s.operation_id == "select-multi")
    assert step.operation_verdict == Verdict.VERIFIED.value
    assert step.receipt is not None
    evidence = step.receipt.action_evidence
    assert evidence["select_mode"] == "values"
    assert evidence["select_multiple"] is True
    assert evidence["requested"] == ["red", "blue"]
    assert evidence["selected_values"] == ["red", "blue"]


def test_values_on_non_multiple_select_fails(fixture_url):
    plan = ExecutionPlan(
        plan_id="values-on-single",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        operations=[
            _nav(fixture_url),
            Operation(
                operation_id="bad-multi",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=_tid("color-select"),
                    option_values=("red", "green"),
                ),
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict != PlanVerdict.VERIFIED
    step = next(s for s in receipt.steps if s.operation_id == "bad-multi")
    assert step.receipt is not None
    assert step.receipt.failure_kind == "target_not_multi_select"
    assert step.receipt.action_evidence["dispatched"] is False


def test_multi_select_sets_all_requested_values_not_last_only(fixture_url):
    """Multi-select must keep all requested values (no sequential replace-to-last)."""
    plan = ExecutionPlan(
        plan_id="multi-keep-all",
        browser_config=_cfg(BrowserEngine.CHROMIUM),
        operations=[
            _nav(fixture_url),
            Operation(
                operation_id="select-multi",
                url=fixture_url,
                action=Action(
                    type=ActionType.SELECT_OPTION,
                    locator=_tid("multi-color-select"),
                    option_values=("green", "yellow", "red"),
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=_tid("multi-select-output"),
                        attribute_name="data-value",
                        attribute_value="red,green,yellow",
                    )
                ],
            ),
        ],
    )
    receipt = execute_plan(plan)
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    step = next(s for s in receipt.steps if s.operation_id == "select-multi")
    selected = set(step.receipt.action_evidence["selected_values"])
    assert selected == {"green", "yellow", "red"}
    assert len(step.receipt.action_evidence["selected_values"]) == 3
