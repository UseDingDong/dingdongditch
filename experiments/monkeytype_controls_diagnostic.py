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
    BrowserConfig,
    BrowserProfile,
    Locator,
    LocatorStrategy,
    NameMatchMode,
    Operation,
    execute_operation,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend  # noqa: E402


def main() -> None:
    config = BrowserConfig(
        headless=False,
        profile=BrowserProfile.DINGDONG,
    )
    backend = PlaywrightBackend(config)
    try:
        backend.start()
        url = "https://monkeytype.com/"
        execute_operation(
            Operation("navigate", url, Action(ActionType.NAVIGATE)),
            backend=backend,
            browser_config=config,
        )
        restart_candidates = (
            Locator(LocatorStrategy.CSS, value="#nextTestButton"),
            Locator(LocatorStrategy.CSS, value="#restartTestButton"),
            Locator(
                LocatorStrategy.ROLE_NAME,
                role="button",
                name="restart test",
                name_match=NameMatchMode.EXACT,
            ),
        )
        for restart in restart_candidates:
            state = inspect_target(backend, restart)
            if state.get("match_count") == 1 and state.get("visible") is True:
                execute_operation(
                    Operation(
                        "return-to-test",
                        url,
                        Action(ActionType.CLICK, locator=restart),
                    ),
                    backend=backend,
                    browser_config=config,
                )
                break
        for selector in (
            "#testConfig",
            "#testConfigMode",
            "#testConfigMode .textButton",
            "#testConfigMode .textButton[data-mode]",
            "#testConfigMode .textButton[mode]",
            "#testConfig .textButton",
            ".mode .textButton",
            ".textButton",
            "[mode]",
            "[data-mode]",
            "[aria-label]",
            "button",
            "[role='button']",
        ):
            state = inspect_target(
                backend, Locator(LocatorStrategy.CSS, value=selector)
            )
            print(selector + "=" + json.dumps(state, sort_keys=True))
    finally:
        backend.stop()


if __name__ == "__main__":
    main()
