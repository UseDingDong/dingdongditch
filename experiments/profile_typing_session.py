from __future__ import annotations

import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dingdongditch import (
    Action,
    ActionType,
    BrowserConfig,
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
    TypingSession,
    TypingSessionConfig,
    execute_operation,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from tests.fixtures.local_test_app.server import start_fixture_server


def main() -> None:
    server, url = start_fixture_server()
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    target = Locator(LocatorStrategy.TEST_ID, value="key-input")
    counts = {"observe": 0, "dispatch": 0}
    try:
        backend.start()
        execute_operation(
            Operation("navigate", url, Action(ActionType.NAVIGATE)),
            backend=backend,
        )
        original_observe = backend.observe
        original_dispatch = backend.dispatch

        def observe(*args, **kwargs):
            counts["observe"] += 1
            return original_observe(*args, **kwargs)

        def dispatch(*args, **kwargs):
            counts["dispatch"] += 1
            return original_dispatch(*args, **kwargs)

        backend.observe = observe
        backend.dispatch = dispatch
        execute_operation(
            Operation("focus", url, Action(ActionType.CLICK, locator=target)),
            backend=backend,
        )
        counts.update(observe=0, dispatch=0)
        started = time.perf_counter()
        for index in range(40):
            execute_operation(
                Operation(
                    f"baseline-{index}",
                    url,
                    Action(
                        ActionType.PRESS_KEY,
                        key="a",
                        key_scope=KeyPressScope.ACTIVE_PAGE,
                    ),
                ),
                backend=backend,
            )
        baseline = time.perf_counter() - started
        baseline_counts = dict(counts)

        counts.update(observe=0, dispatch=0)
        started = time.perf_counter()
        result = TypingSession(
            TypingSessionConfig(
                session_id="profile",
                url=url,
                text="a" * 40,
                target_locator=target,
                max_text_chunk_characters=10,
            ),
            backend=backend,
        ).run()
        session = time.perf_counter() - started
        print(
            {
                "baseline_seconds": round(baseline, 4),
                "baseline_counts": baseline_counts,
                "session_seconds": round(session, 4),
                "session_counts": dict(counts),
                "session_status": result.status.value,
                "typed": result.typed_characters,
            }
        )
    finally:
        backend.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
