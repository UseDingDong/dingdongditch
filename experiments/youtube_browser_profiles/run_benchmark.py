"""Compare fresh and persistent DingDongDitch sessions on YouTube."""

from __future__ import annotations

import json
import time
from pathlib import Path

from dingdongditch import (
    Action,
    ActionType,
    BrowserConfig,
    BrowserProfile,
    Operation,
    execute_operation,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


OUTPUT = Path(__file__).with_name("benchmark_results.json")


def run(profile: BrowserProfile, launch: int) -> dict:
    backend = PlaywrightBackend(
        BrowserConfig(profile=profile, headless=True)
    )
    started = time.perf_counter()
    try:
        backend.start()
        receipt = execute_operation(
            Operation(
                operation_id=f"youtube-{profile.value}-{launch}",
                url="https://www.youtube.com/",
                action=Action(type=ActionType.NAVIGATE),
            ),
            backend=backend,
        )
        page = backend.page
        page.wait_for_timeout(2500)
        body = page.locator("body").inner_text(timeout=5000)
        cookies = backend._context.cookies() if backend._context else []
        try:
            storage = page.evaluate(
                "() => ({local: Object.keys(localStorage), session: Object.keys(sessionStorage)})"
            )
            storage_error = None
        except Exception as exc:
            storage = {"local": [], "session": []}
            storage_error = f"{type(exc).__name__}: {exc}"
        redirects = [
            {"status": item.status, "url": item.url}
            for item in backend._network
            if item.status is not None and 300 <= item.status < 400
        ]
        lower = body.lower()
        return {
            "profile": profile.value,
            "launch": launch,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "verdict": receipt.verdict.value,
            "execution_error": receipt.execution_error,
            "failure_kind": receipt.failure_kind,
            "final_url": page.url,
            "title": page.title(),
            "redirects": redirects,
            "cookie_count": len(cookies),
            "local_storage_keys": storage["local"],
            "session_storage_keys": storage["session"],
            "storage_error": storage_error,
            "sign_in_prompt_visible": "sign in" in lower,
            "consent_prompt_visible": any(
                phrase in lower
                for phrase in ("before you continue", "accept all", "reject all")
            ),
        }
    except Exception as exc:
        return {
            "profile": profile.value,
            "launch": launch,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        backend.stop()


def main() -> None:
    results = [
        run(BrowserProfile.BENCHMARK, 1),
        run(BrowserProfile.BENCHMARK, 2),
        run(BrowserProfile.DINGDONG, 1),
        run(BrowserProfile.DINGDONG, 2),
    ]
    OUTPUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
