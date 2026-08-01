from pathlib import Path
import json

from dingdongditch import (
    Action, ActionType, BrowserConfig, DownloadPolicy, DownloadRequest,
    ExecutionPlan, Locator, LocatorStrategy, Operation, Verdict, execute_plan,
    TrustedDownloadConfig,
)


def test_download_is_committed_and_receipted(fixture_url, tmp_path):
    cfg = BrowserConfig(headless=True)
    plan = ExecutionPlan(
        plan_id="download-e2e",
        browser_config=cfg,
        operations=[
            Operation(
                operation_id="navigate",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[],
            ),
            Operation(
                operation_id="download",
                url=fixture_url,
                action=Action(
                    type=ActionType.DOWNLOAD,
                    locator=Locator(strategy=LocatorStrategy.CSS, value="#download-text"),
                    download_request=DownloadRequest(
                        preferred_filename="saved.txt",
                        allowed_extensions=(".txt",),
                        minimum_bytes=1,
                    ),
                ),
            ),
        ],
    )
    # Navigate without expectations is deliberately indeterminate and would
    # stop a plan, so retain the session and execute the download separately.
    from dingdongditch.backends.playwright_backend import PlaywrightBackend
    from dingdongditch.runtime.executor import execute_operation
    backend = PlaywrightBackend(
        cfg, trusted_download_config=TrustedDownloadConfig(artifact_root=str(tmp_path))
    )
    backend.start()
    try:
        nav = execute_operation(plan.operations[0], backend=backend)
        assert nav.action_executed_successfully
        receipt = execute_operation(plan.operations[1], backend=backend)
        assert receipt.verdict == Verdict.VERIFIED, json.dumps(receipt.to_dict(), indent=2)
        result = receipt.action_evidence["download"]
        assert result["state"] == "completed"
        assert "final_path" not in result["artifact"]
        final = backend._download_store.root / result["artifact"]["relative_path"]
        assert final.read_text(encoding="utf-8").startswith("deterministic")
        session_root = tmp_path / "downloads" / backend.browser_session_id
        assert session_root in final.parents
    finally:
        backend.stop()
    assert final.exists()


def test_delayed_download_event_is_armed_before_trigger(fixture_url, tmp_path):
    cfg = BrowserConfig(headless=True)
    from dingdongditch.backends.playwright_backend import PlaywrightBackend
    from dingdongditch.runtime.executor import execute_operation
    backend = PlaywrightBackend(
        cfg, trusted_download_config=TrustedDownloadConfig(artifact_root=str(tmp_path))
    )
    backend.start()
    try:
        execute_operation(
            Operation(
                operation_id="navigate",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
            ),
            backend=backend,
        )
        receipt = execute_operation(
            Operation(
                operation_id="delayed-download",
                url=fixture_url,
                action=Action(
                    type=ActionType.DOWNLOAD,
                    locator=Locator(strategy=LocatorStrategy.CSS, value="#delayed-download"),
                    download_request=DownloadRequest(timeout_ms=5_000),
                ),
            ),
            backend=backend,
        )
        assert receipt.verdict == Verdict.VERIFIED, receipt.to_dict()
        assert receipt.action_evidence["download"]["artifact"]["suggested_filename"] == "server-suggested.txt"
    finally:
        backend.stop()


def test_multiple_download_events_fail_closed(fixture_url, tmp_path):
    cfg = BrowserConfig(headless=True)
    from dingdongditch.backends.playwright_backend import PlaywrightBackend
    from dingdongditch.runtime.executor import execute_operation
    backend = PlaywrightBackend(
        cfg, trusted_download_config=TrustedDownloadConfig(artifact_root=str(tmp_path))
    )
    backend.start()
    try:
        execute_operation(
            Operation(
                operation_id="navigate",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
            ),
            backend=backend,
        )
        receipt = execute_operation(
            Operation(
                operation_id="double-download",
                url=fixture_url,
                action=Action(
                    type=ActionType.DOWNLOAD,
                    locator=Locator(strategy=LocatorStrategy.CSS, value="#double-download"),
                    download_request=DownloadRequest(timeout_ms=5_000),
                ),
            ),
            backend=backend,
        )
        assert receipt.verdict == Verdict.EXECUTION_FAILED
        assert receipt.failure_kind == "multiple_download_events"
        assert receipt.action_evidence["download"]["artifact"] is None
    finally:
        backend.stop()
