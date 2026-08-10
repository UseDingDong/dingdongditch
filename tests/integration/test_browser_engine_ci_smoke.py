"""Small deterministic cross-platform browser-engine gate for CI matrices."""
from __future__ import annotations

import os

from dingdongditch.contract.browser import BrowserConfig, BrowserEngine
from dingdongditch.contract.expectation import Expectation, ExpectationType, UrlMatchMode
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.plan import ExecutionPlan, PlanVerdict
from dingdongditch.runtime.plan_executor import execute_plan


def _engine_from_environment() -> BrowserEngine:
    value = os.environ.get("DINGDONG_CI_BROWSER_ENGINE", BrowserEngine.CHROMIUM.value)
    return BrowserEngine(value)


def test_declared_ci_engine_executes_deterministic_navigation_fill_and_click(fixture_url):
    engine = _engine_from_environment()
    plan = ExecutionPlan(
        plan_id=f"ci-{engine.value}-smoke",
        browser_config=BrowserConfig(engine=engine, headless=True),
        operations=[
            Operation(
                operation_id="navigate",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value=fixture_url,
                        url_match=UrlMatchMode.EXACT,
                    )
                ],
            ),
            Operation(
                operation_id="fill",
                url=fixture_url,
                action=Action(
                    type=ActionType.FILL,
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
                    text=engine.value,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
                        attribute_name="value",
                        attribute_value=engine.value,
                    )
                ],
            ),
            Operation(
                operation_id="click",
                url=fixture_url,
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
            ),
        ],
    )

    result = execute_plan(plan)

    assert result.plan_verdict == PlanVerdict.VERIFIED
    assert result.browser["engine"] == engine.value
    assert result.verified_step_count == 3
