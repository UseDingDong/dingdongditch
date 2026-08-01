"""Minimal explicit-navigation host-side demonstration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running without install when repo root is cwd.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dingdongditch import (  # noqa: E402
    Action,
    ActionType,
    Expectation,
    Locator,
    LocatorStrategy,
    Operation,
    ExecutionPlan,
    execute_plan,
)
from dingdongditch.contract.expectation import ExpectationType  # noqa: E402
from tests.fixtures.local_test_app.server import start_fixture_server  # noqa: E402


def main() -> None:
    server, url = start_fixture_server()
    try:
        operation = Operation(
            operation_id="demo-click-1",
            url=url,
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
                    expectation_id="state-active",
                )
            ],
        )
        plan = ExecutionPlan(
            plan_id="demo-explicit-navigation",
            operations=[
                Operation(
                    operation_id="demo-navigate",
                    url=url,
                    action=Action(type=ActionType.NAVIGATE),
                ),
                operation,
            ],
        )
        receipt = execute_plan(plan)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        print(f"verdict={receipt.plan_verdict.value}", file=sys.stderr)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
