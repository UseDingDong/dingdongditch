"""Deterministic Milestone 2 ordered-plan demonstration (bundled engines)."""

from __future__ import annotations

import argparse
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
    execute_plan,
)
from dingdongditch.contract.expectation import UrlMatchMode  # noqa: E402
from tests.fixtures.local_test_app.server import start_fixture_server  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic ordered-plan demo")
    parser.add_argument(
        "--engine",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Bundled Playwright engine (default: chromium)",
    )
    parser.add_argument("--headed", action="store_true", help="Run headed")
    args = parser.parse_args()
    engine = BrowserEngine(args.engine)

    server, url = start_fixture_server()
    try:
        plan = ExecutionPlan(
            plan_id=f"ordered-plan-demo-{engine.value}",
            browser_config=BrowserConfig(
                provider=BrowserProvider.PLAYWRIGHT,
                engine=engine,
                channel=BrowserChannel.BUNDLED,
                headless=not args.headed,
            ),
            operations=[
                Operation(
                    operation_id="demo-navigate",
                    url=url,
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
                    operation_id="demo-fill",
                    url=url,
                    action=Action(
                        type=ActionType.FILL,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="text-input"
                        ),
                        text="ordered-plan",
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(
                                strategy=LocatorStrategy.TEST_ID, value="text-input"
                            ),
                            attribute_name="value",
                            attribute_value="ordered-plan",
                        )
                    ],
                ),
                Operation(
                    operation_id="demo-click",
                    url=url,
                    action=Action(
                        type=ActionType.CLICK,
                        locator=Locator(
                            strategy=LocatorStrategy.TEST_ID, value="target-control"
                        ),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(
                                strategy=LocatorStrategy.TEST_ID, value="target-control"
                            ),
                            attribute_name="data-state",
                            attribute_value="active",
                        )
                    ],
                ),
            ],
        )
        receipt = execute_plan(plan)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        print(
            f"plan_verdict={receipt.plan_verdict.value} "
            f"engine={receipt.browser and receipt.browser.get('engine')} "
            f"completion={receipt.completion_status.value}",
            file=sys.stderr,
        )
        print(
            f"session={receipt.browser_session_id} "
            f"context={receipt.context_id} page={receipt.page_id}",
            file=sys.stderr,
        )
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
