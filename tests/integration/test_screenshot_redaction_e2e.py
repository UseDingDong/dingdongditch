from pathlib import Path
import pytest

from dingdongditch import (
    Action,
    ActionType,
    BrowserConfig,
    BrowserEngine,
    Expectation,
    ExpectationType,
    Operation,
    ScreenshotConfig,
    ScreenshotPolicy,
    Verdict,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.runtime.executor import execute_operation


def _verified_navigation(url: str, config: ScreenshotConfig) -> Operation:
    return Operation(
        operation_id="redacted-shot",
        url=url,
        action=Action(type=ActionType.NAVIGATE),
        expectations=[Expectation(type=ExpectationType.URL, url_value=url)],
        screenshot_config=config,
    )


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
)
def test_native_screenshot_masks_are_applied_and_receipted(
    tmp_path: Path, engine: BrowserEngine
):
    backend = PlaywrightBackend(BrowserConfig(headless=True, engine=engine))
    try:
        backend.start()
        backend.page.set_content(
            '<input type="password" value="secret">'
            '<div class="private">private text</div>'
            '<iframe srcdoc="&lt;input type=&quot;password&quot; value=&quot;framed&quot;&gt;"></iframe>'
        )
        backend.page.locator("iframe").content_frame.locator("input").wait_for()
        config = ScreenshotConfig(
            policy=ScreenshotPolicy.ALWAYS,
            artifact_root=str(tmp_path),
            sensitive_selectors=(".private",),
            mandatory_redaction=True,
        )
        result = backend.capture_screenshot(
            plan_id="redaction",
            step_id="step",
            operation_id="shot",
            reason="test",
            config=config,
        )
        assert result["captured"] is True, result
        assert result["redaction_status"] == "applied"
        assert result["redaction_match_count"] == 3
        assert result["redaction_selectors"] == [
            'input[type="password"]',
            ".private",
        ]
        assert Path(result["artifact_path"]).is_file()
    finally:
        backend.stop()


def test_mandatory_redaction_failure_writes_no_file_and_fails_receipt(tmp_path: Path):
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        config = ScreenshotConfig(
            policy=ScreenshotPolicy.ALWAYS,
            artifact_root=str(tmp_path),
            sensitive_selectors=("[",),
            mandatory_redaction=True,
        )
        receipt = execute_operation(
            _verified_navigation("data:text/html,<button>Safe</button>", config),
            backend=backend,
        )
        shot = receipt.artifacts[0]
        assert receipt.verdict == Verdict.EXECUTION_FAILED
        assert receipt.failure_kind == "screenshot_redaction_failed"
        assert receipt.execution_status == "evidence_capture_failed"
        assert shot["status"] == "failed"
        assert shot["redaction"]["status"] == "failed"
        assert shot["filename"] is None
        assert list(tmp_path.glob("*.png")) == []
    finally:
        backend.stop()
