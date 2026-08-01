"""Minimal host example: project code authors a plan; DingDongDitch executes it.

This is not a planner. The host (developer script, Cursor, CI, or test
framework) constructs a typed ExecutionPlan against a known local fixture,
then calls execute_plan. DingDongDitch validates, runs, observes, and returns
a PlanReceipt — it does not invent steps, targets, or workflows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dingdongditch import (  # noqa: E402
    Action,
    ActionType,
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
    Expectation,
    ExpectationType,
    ExecutionPlan,
    Locator,
    LocatorStrategy,
    Operation,
    PlanVerdict,
    execute_plan,
)
from dingdongditch.contract.expectation import UrlMatchMode  # noqa: E402
from tests.fixtures.local_test_app.server import start_fixture_server  # noqa: E402


def build_host_plan(base_url: str) -> ExecutionPlan:
    """Host-side construction only — not part of the DingDongDitch package."""
    field = Locator(strategy=LocatorStrategy.TEST_ID, value="text-input")
    return ExecutionPlan(
        plan_id="host-execution-plan-example",
        browser_config=BrowserConfig(
            provider=BrowserProvider.PLAYWRIGHT,
            engine=BrowserEngine.CHROMIUM,
            channel=BrowserChannel.BUNDLED,
            headless=True,
        ),
        operations=[
            Operation(
                operation_id="host-navigate",
                url=base_url,
                timeout_ms=30_000,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="index.html",
                        url_match=UrlMatchMode.CONTAINS,
                    ),
                ],
            ),
            Operation(
                operation_id="host-fill",
                url=base_url,
                timeout_ms=15_000,
                action=Action(
                    type=ActionType.FILL,
                    locator=field,
                    text="host-authored",
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=field,
                        attribute_name="value",
                        attribute_value="host-authored",
                    ),
                ],
            ),
        ],
    )


def main() -> int:
    server, url = start_fixture_server()
    try:
        plan = build_host_plan(url)
        plan.validate()
        receipt = execute_plan(plan)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        print(
            f"plan_verdict={receipt.plan_verdict.value} "
            f"completion={receipt.completion_status.value}",
            file=sys.stderr,
        )
        return 0 if receipt.plan_verdict == PlanVerdict.VERIFIED else 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
