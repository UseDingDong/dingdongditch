"""Neutral example: explicit BrowserConfig + receipt browser metadata."""

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
    Operation,
    execute_operation,
)
from dingdongditch.contract.expectation import UrlMatchMode  # noqa: E402
from tests.fixtures.local_test_app.server import start_fixture_server  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="BrowserConfig demo")
    parser.add_argument(
        "--engine",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
    )
    args = parser.parse_args()
    engine = BrowserEngine(args.engine)

    server, url = start_fixture_server()
    try:
        config = BrowserConfig(
            provider=BrowserProvider.PLAYWRIGHT,
            engine=engine,
            channel=BrowserChannel.BUNDLED,
            headless=True,
        )
        operation = Operation(
            operation_id="browser-boundary-demo-1",
            url=url,
            action=Action(type=ActionType.NAVIGATE),
            expectations=[
                Expectation(
                    type=ExpectationType.URL,
                    url_value="index.html",
                    url_match=UrlMatchMode.CONTAINS,
                    expectation_id="url",
                )
            ],
        )
        receipt = execute_operation(operation, browser_config=config)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        print(f"verdict={receipt.verdict.value}", file=sys.stderr)
        print(f"browser={receipt.browser}", file=sys.stderr)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
