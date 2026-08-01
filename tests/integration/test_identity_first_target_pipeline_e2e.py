"""Regression coverage for identity-first target preparation."""

from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import UrlMatchMode
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.plan_executor import execute_plan


def test_amazon_offscreen_remembered_product_is_relocated_and_opened(fixture_url):
    """Stable product identity must resolve before viewport interaction state."""
    product = Locator(
        strategy=LocatorStrategy.TEST_ID,
        value="amazon-remembered-product-B0STABLE123",
    )
    plan_receipt = execute_plan(
        ExecutionPlan(
            plan_id="amazon-identity-first",
            operations=[
                Operation(
                    operation_id="navigate",
                    url=fixture_url,
                    action=Action(type=ActionType.NAVIGATE),
                    expectations=[
                        Expectation(
                            type=ExpectationType.URL,
                            url_value="index.html",
                            url_match=UrlMatchMode.CONTAINS,
                        )
                    ],
                ),
                Operation(
            operation_id="amazon-remembered-product",
            url=fixture_url,
            timeout_ms=10_000,
            locate_retry_ms=300,
            action=Action(type=ActionType.CLICK, locator=product),
            expectations=[
                Expectation(
                    type=ExpectationType.ATTRIBUTE,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID,
                        value="state-indicator",
                    ),
                    attribute_name="data-state",
                    attribute_value="amazon-product-opened",
                )
            ],
                ),
            ],
        )
    )
    receipt = plan_receipt.steps[1].receipt

    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.action_evidence["preparation"]["scroll_into_view"] == "completed"
    assert receipt.action_evidence["actionability"] == {
        "connected": True,
        "visible": True,
        "enabled": True,
    }
    stages = [stage["stage"] for stage in receipt.target_resolution["stages"]]
    assert stages.index("identity_primary") < stages.index("preparation")
    assert stages.index("preparation") < stages.index("actionability_primary")
    assert stages.index("actionability_primary") < stages.index("actionability")
