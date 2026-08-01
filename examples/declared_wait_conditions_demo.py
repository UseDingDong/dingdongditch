"""Deterministic declared wait_for demo (one native ExecutionPlan)."""

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
    WaitCondition,
    WaitConditionType,
    execute_plan,
)
from dingdongditch.contract.expectation import TextMatchMode, UrlMatchMode  # noqa: E402
from tests.fixtures.local_test_app.server import start_fixture_server  # noqa: E402


def _tid(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Declared wait conditions demo")
    parser.add_argument(
        "--engine", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headed", action="store_true")
    mode.add_argument("--headless", action="store_true", default=True)
    parser.add_argument(
        "--demo-timeout",
        action="store_true",
        help="Run a second plan that intentionally times out (NOT_VERIFIED)",
    )
    args = parser.parse_args()
    engine = BrowserEngine(args.engine)
    headless = not args.headed

    server, url = start_fixture_server()
    try:
        cfg = BrowserConfig(
            provider=BrowserProvider.PLAYWRIGHT,
            engine=engine,
            channel=BrowserChannel.BUNDLED,
            headless=headless,
        )
        plan = ExecutionPlan(
            plan_id=f"declared-waits-{engine.value}",
            browser_config=cfg,
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
                    operation_id="trigger",
                    url=url,
                    action=Action(
                        type=ActionType.CLICK, locator=_tid("delayed-control")
                    ),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_EXISTS,
                            locator=_tid("delayed-control"),
                            exists=True,
                        )
                    ],
                ),
                Operation(
                    operation_id="wait-visible",
                    url=url,
                    action=Action(
                        type=ActionType.WAIT_FOR,
                        wait_condition=WaitCondition(
                            type=WaitConditionType.ELEMENT_VISIBLE,
                            locator=_tid("result-item"),
                        ),
                        wait_timeout_ms=3_000,
                    ),
                ),
                Operation(
                    operation_id="wait-text",
                    url=url,
                    action=Action(
                        type=ActionType.WAIT_FOR,
                        wait_condition=WaitCondition(
                            type=WaitConditionType.TEXT_PRESENT,
                            locator=_tid("state-indicator"),
                            text_value="delayed-ready",
                            text_match=TextMatchMode.CONTAINS,
                        ),
                        wait_timeout_ms=3_000,
                    ),
                ),
                Operation(
                    operation_id="noop",
                    url=url,
                    action=Action(type=ActionType.CLICK, locator=_tid("noop-control")),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_EXISTS,
                            locator=_tid("noop-control"),
                            exists=True,
                        )
                    ],
                ),
            ],
        )
        receipt = execute_plan(plan)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        print(
            f"verdict={receipt.plan_verdict.value} engine={engine.value} "
            f"session={receipt.browser_session_id}"
        )
        ids = {
            (s.browser_session_id, s.context_id, s.page_id)
            for s in receipt.steps
            if s.attempted
        }
        print(f"stable_ids={len(ids) == 1} attempted={receipt.attempted_step_count}")

        if args.demo_timeout:
            timed = execute_plan(
                ExecutionPlan(
                    plan_id=f"wait-timeout-{engine.value}",
                    browser_config=cfg,
                    operations=[
                        Operation(
                            operation_id="nav2",
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
                            operation_id="wait-miss",
                            url=url,
                            action=Action(
                                type=ActionType.WAIT_FOR,
                                wait_condition=WaitCondition(
                                    type=WaitConditionType.ELEMENT_VISIBLE,
                                    locator=_tid("result-item"),
                                ),
                                wait_timeout_ms=400,
                            ),
                        ),
                        Operation(
                            operation_id="skip-me",
                            url=url,
                            action=Action(
                                type=ActionType.CLICK, locator=_tid("noop-control")
                            ),
                            expectations=[
                                Expectation(
                                    type=ExpectationType.ELEMENT_EXISTS,
                                    locator=_tid("noop-control"),
                                    exists=True,
                                )
                            ],
                        ),
                    ],
                )
            )
            print(
                f"timeout_demo verdict={timed.plan_verdict.value} "
                f"skipped={timed.skipped_step_count}"
            )
            if timed.plan_verdict.value != "NOT_VERIFIED":
                return 1

        return 0 if receipt.plan_verdict.value == "VERIFIED" else 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
