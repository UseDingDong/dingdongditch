"""Deterministic demo of the five basic interaction expansion actions."""

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
from dingdongditch.contract.operation import KeyPressScope  # noqa: E402
from tests.fixtures.local_test_app.server import start_fixture_server  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Basic interactions demo")
    parser.add_argument(
        "--engine", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    engine = BrowserEngine(args.engine)

    server, url = start_fixture_server()
    try:
        tid = LocatorStrategy.TEST_ID
        plan = ExecutionPlan(
            plan_id=f"basic-interactions-{engine.value}",
            browser_config=BrowserConfig(
                provider=BrowserProvider.PLAYWRIGHT,
                engine=engine,
                channel=BrowserChannel.BUNDLED,
                headless=not args.headed,
            ),
            operations=[
                Operation(
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
                ),
                Operation(
                    operation_id="fill",
                    url=url,
                    action=Action(
                        type=ActionType.FILL,
                        locator=Locator(strategy=tid, value="key-input"),
                        text="demo",
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(strategy=tid, value="key-input"),
                            attribute_name="value",
                            attribute_value="demo",
                        )
                    ],
                ),
                Operation(
                    operation_id="press",
                    url=url,
                    action=Action(
                        type=ActionType.PRESS_KEY,
                        key="Enter",
                        locator=Locator(strategy=tid, value="key-input"),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(strategy=tid, value="state-indicator"),
                            attribute_name="data-state",
                            attribute_value="enter-submitted",
                        )
                    ],
                ),
                Operation(
                    operation_id="select",
                    url=url,
                    action=Action(
                        type=ActionType.SELECT_OPTION,
                        locator=Locator(strategy=tid, value="color-select"),
                        option_value="blue",
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(strategy=tid, value="select-output"),
                            attribute_name="data-value",
                            attribute_value="blue",
                        )
                    ],
                ),
                Operation(
                    operation_id="check",
                    url=url,
                    action=Action(
                        type=ActionType.SET_CHECKED,
                        locator=Locator(strategy=tid, value="agree-box"),
                        checked=True,
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ATTRIBUTE,
                            locator=Locator(strategy=tid, value="check-output"),
                            attribute_name="data-agree",
                            attribute_value="true",
                        )
                    ],
                ),
                Operation(
                    operation_id="hover",
                    url=url,
                    action=Action(
                        type=ActionType.HOVER,
                        locator=Locator(strategy=tid, value="hover-target"),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_VISIBLE,
                            locator=Locator(strategy=tid, value="hover-tooltip"),
                            visible=True,
                        )
                    ],
                ),
                Operation(
                    operation_id="scroll",
                    url=url,
                    action=Action(
                        type=ActionType.SCROLL_TO_TARGET,
                        locator=Locator(strategy=tid, value="below-fold"),
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_IN_VIEWPORT,
                            locator=Locator(strategy=tid, value="below-fold"),
                            in_viewport=True,
                        )
                    ],
                ),
            ],
        )
        # Unused import kept for documentation of active_page option:
        _ = KeyPressScope
        receipt = execute_plan(plan)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        print(
            f"verdict={receipt.plan_verdict.value} engine={engine.value} "
            f"session={receipt.browser_session_id}",
            file=sys.stderr,
        )
        return 0 if receipt.plan_verdict.value == "VERIFIED" else 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
