"""Browser configuration validation and launch-boundary tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dingdongditch.backends.playwright_backend import (
    PlaywrightBackend,
    launch_playwright_browser,
)
from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserConfigError,
    BrowserEngine,
    BrowserFailureKind,
    BrowserProvider,
    default_browser_config,
)
from dingdongditch.contract.expectation import Expectation, ExpectationType, UrlMatchMode
from dingdongditch.contract.operation import Action, ActionType, Operation
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.executor import execute_operation


def test_default_browser_config_is_bundled_chromium():
    cfg = default_browser_config()
    assert cfg.provider == BrowserProvider.PLAYWRIGHT
    assert cfg.engine == BrowserEngine.CHROMIUM
    assert cfg.channel == BrowserChannel.BUNDLED
    assert cfg.headless is True
    cfg.validate()


def test_explicit_bundled_chromium_validates():
    BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=BrowserEngine.CHROMIUM,
        channel=BrowserChannel.BUNDLED,
        headless=False,
    ).validate()


def test_bundled_firefox_validates_and_is_not_unsupported_engine():
    cfg = BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=BrowserEngine.FIREFOX,
        channel=BrowserChannel.BUNDLED,
        headless=True,
    )
    cfg.validate()
    assert cfg.engine == BrowserEngine.FIREFOX


def test_bundled_webkit_validates_and_is_not_unsupported_engine():
    cfg = BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=BrowserEngine.WEBKIT,
        channel=BrowserChannel.BUNDLED,
        headless=True,
    )
    cfg.validate()
    assert cfg.engine == BrowserEngine.WEBKIT


def test_safari_string_is_not_an_engine_alias():
    with pytest.raises(BrowserConfigError) as exc:
        BrowserConfig(engine="safari").validate()  # type: ignore[arg-type]
    assert exc.value.failure_kind == BrowserFailureKind.UNSUPPORTED_BROWSER_ENGINE
    assert "safari" in str(exc.value).lower()


def test_webkit_unsupported_channel_fails_before_launch():
    with pytest.raises(BrowserConfigError) as exc:
        BrowserConfig(
            engine=BrowserEngine.WEBKIT, channel=BrowserChannel.CHROME
        ).validate()
    assert (
        exc.value.failure_kind
        == BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION
    )


def test_unsupported_channel_fails_before_launch_as_probe():
    """Former WebKit-as-unsupported probe; channels remain the unsupported path."""
    cfg = BrowserConfig(channel=BrowserChannel.CHROME)
    with patch(
        "dingdongditch.backends.playwright_backend.sync_playwright"
    ) as sync_pw:
        receipt = execute_operation(
            Operation(
                operation_id="ch-probe",
                url="https://example.com",
                action=Action(type=ActionType.NAVIGATE),
            ),
            browser_config=cfg,
        )
        assert receipt.verdict == Verdict.EXECUTION_FAILED
        assert receipt.failure_kind == "unsupported_browser_channel"
        sync_pw.assert_not_called()


def test_firefox_chrome_channel_fails_before_launch():
    with pytest.raises(BrowserConfigError) as exc:
        BrowserConfig(
            engine=BrowserEngine.FIREFOX, channel=BrowserChannel.CHROME
        ).validate()
    assert (
        exc.value.failure_kind
        == BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION
    )


def test_firefox_msedge_and_brave_fail_before_launch():
    for channel in (BrowserChannel.MSEDGE, BrowserChannel.BRAVE):
        with pytest.raises(BrowserConfigError) as exc:
            BrowserConfig(engine=BrowserEngine.FIREFOX, channel=channel).validate()
        assert (
            exc.value.failure_kind
            == BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION
        )


def test_unsupported_chrome_channel_fails_before_launch():
    cfg = BrowserConfig(channel=BrowserChannel.CHROME)
    with pytest.raises(BrowserConfigError) as exc:
        cfg.validate()
    assert exc.value.failure_kind == BrowserFailureKind.UNSUPPORTED_BROWSER_CHANNEL

    with patch(
        "dingdongditch.backends.playwright_backend.sync_playwright"
    ) as sync_pw:
        receipt = execute_operation(
            Operation(
                operation_id="ch",
                url="https://example.com",
                action=Action(type=ActionType.NAVIGATE),
            ),
            browser_config=cfg,
        )
        assert receipt.failure_kind == "unsupported_browser_channel"
        sync_pw.assert_not_called()


def test_invalid_engine_channel_combination():
    with pytest.raises(BrowserConfigError) as exc:
        BrowserConfig(
            engine=BrowserEngine.FIREFOX, channel=BrowserChannel.CHROME
        ).validate()
    assert (
        exc.value.failure_kind
        == BrowserFailureKind.UNSUPPORTED_ENGINE_CHANNEL_COMBINATION
    )


def test_capabilities_include_chromium_firefox_webkit():
    caps = PlaywrightBackend.capabilities()
    assert caps.provider == BrowserProvider.PLAYWRIGHT
    assert BrowserEngine.CHROMIUM in caps.engines
    assert BrowserEngine.FIREFOX in caps.engines
    assert BrowserEngine.WEBKIT in caps.engines
    assert caps.channels == (BrowserChannel.BUNDLED,)
    assert "safari_not_supported" in caps.notes


def test_launch_translation_authoritative_for_bundled_chromium():
    pw = MagicMock()
    browser = MagicMock()
    pw.chromium.launch.return_value = browser
    cfg = BrowserConfig(headless=False)
    result = launch_playwright_browser(pw, cfg)
    assert result is browser
    pw.chromium.launch.assert_called_once_with(headless=False)
    pw.firefox.launch.assert_not_called()
    pw.webkit.launch.assert_not_called()


def test_launch_translation_authoritative_for_bundled_firefox():
    pw = MagicMock()
    browser = MagicMock()
    pw.firefox.launch.return_value = browser
    cfg = BrowserConfig(engine=BrowserEngine.FIREFOX, headless=True)
    result = launch_playwright_browser(pw, cfg)
    assert result is browser
    pw.firefox.launch.assert_called_once_with(headless=True)
    pw.chromium.launch.assert_not_called()
    pw.webkit.launch.assert_not_called()


def test_launch_translation_authoritative_for_bundled_webkit():
    pw = MagicMock()
    browser = MagicMock()
    pw.webkit.launch.return_value = browser
    cfg = BrowserConfig(engine=BrowserEngine.WEBKIT, headless=True)
    result = launch_playwright_browser(pw, cfg)
    assert result is browser
    pw.webkit.launch.assert_called_once_with(headless=True)
    pw.chromium.launch.assert_not_called()
    pw.firefox.launch.assert_not_called()


def test_webkit_launch_failure_does_not_call_other_engines():
    pw = MagicMock()
    pw.webkit.launch.side_effect = RuntimeError("webkit boom")
    with pytest.raises(RuntimeError, match="webkit boom"):
        try:
            launch_playwright_browser(
                pw, BrowserConfig(engine=BrowserEngine.WEBKIT, headless=True)
            )
        finally:
            pw.chromium.launch.assert_not_called()
            pw.firefox.launch.assert_not_called()


def test_launch_translation_headless_true():
    pw = MagicMock()
    pw.chromium.launch.return_value = MagicMock()
    launch_playwright_browser(pw, BrowserConfig(headless=True))
    pw.chromium.launch.assert_called_once_with(headless=True)


def test_firefox_launch_failure_does_not_call_chromium():
    pw = MagicMock()
    pw.firefox.launch.side_effect = RuntimeError("firefox boom")
    with pytest.raises(RuntimeError, match="firefox boom"):
        try:
            launch_playwright_browser(
                pw, BrowserConfig(engine=BrowserEngine.FIREFOX, headless=True)
            )
        finally:
            pw.chromium.launch.assert_not_called()


def test_no_silent_chromium_fallback_in_launcher():
    pw = MagicMock()
    cfg = BrowserConfig(
        engine=BrowserEngine.CHROMIUM, channel=BrowserChannel.BUNDLED
    )
    launch_playwright_browser(pw, cfg)
    pw.chromium.launch.assert_called()
    pw.firefox.launch.assert_not_called()


def test_omitted_config_defaults_in_execute_operation(fixture_url):
    receipt = execute_operation(
        Operation(
            operation_id="default-browser",
            url=fixture_url,
            action=Action(type=ActionType.NAVIGATE),
            expectations=[
                Expectation(
                    type=ExpectationType.URL,
                    url_value="index.html",
                    url_match=UrlMatchMode.CONTAINS,
                )
            ],
        )
    )
    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.browser is not None
    assert receipt.browser["provider"] == "playwright"
    assert receipt.browser["engine"] == "chromium"
    assert receipt.browser["channel"] == "bundled"
    assert receipt.browser["headless"] is True
    assert receipt.browser["browser_session_id"]
    assert receipt.schema_version == "1.8.0"


def test_explicit_browser_config_headless_false_metadata(fixture_url):
    cfg = BrowserConfig(headless=False)
    receipt = execute_operation(
        Operation(
            operation_id="headed",
            url=fixture_url,
            action=Action(type=ActionType.NAVIGATE),
            expectations=[
                Expectation(
                    type=ExpectationType.URL,
                    url_value="index.html",
                    url_match=UrlMatchMode.CONTAINS,
                )
            ],
        ),
        browser_config=cfg,
    )
    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.browser["headless"] is False


def test_session_id_reused_across_operations(fixture_url):
    backend = PlaywrightBackend(browser_config=BrowserConfig(headless=True))
    backend.start()
    try:
        sid1 = backend.browser_session_id
        cid1 = backend.context_id
        pid1 = backend.page_id
        assert sid1 and cid1 and pid1

        r1 = execute_operation(
            Operation(
                operation_id="reuse-1",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="index.html",
                        url_match=UrlMatchMode.CONTAINS,
                    )
                ],
            ),
            backend=backend,
        )
        r2 = execute_operation(
            Operation(
                operation_id="reuse-2",
                url=fixture_url,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[
                    Expectation(
                        type=ExpectationType.URL,
                        url_value="index.html",
                        url_match=UrlMatchMode.CONTAINS,
                    )
                ],
            ),
            backend=backend,
        )
        assert r1.verdict == Verdict.VERIFIED
        assert r2.verdict == Verdict.VERIFIED
        assert r1.browser["browser_session_id"] == sid1
        assert r2.browser["browser_session_id"] == sid1
        assert r1.browser["context_id"] == cid1
        assert r2.browser["context_id"] == cid1
        assert r1.browser["page_id"] == pid1
        assert r2.browser["page_id"] == pid1
        assert r2.browser["newly_launched"] is False
    finally:
        backend.stop()
        assert backend.browser_session_id is None
        assert backend.is_started is False


def test_new_session_gets_new_ids():
    b1 = PlaywrightBackend()
    b1.start()
    sid1 = b1.browser_session_id
    b1.stop()
    b2 = PlaywrightBackend()
    b2.start()
    try:
        assert b2.browser_session_id != sid1
        assert b2.browser_session_id is not None
    finally:
        b2.stop()


def test_cleanup_after_validation_failure_does_not_leak():
    with patch(
        "dingdongditch.backends.playwright_backend.sync_playwright"
    ) as sync_pw:
        receipt = execute_operation(
            Operation(
                operation_id="no-launch",
                url="https://example.com",
                action=Action(type=ActionType.NAVIGATE),
            ),
            browser_config=BrowserConfig(channel=BrowserChannel.CHROME),
        )
        assert receipt.verdict == Verdict.EXECUTION_FAILED
        sync_pw.assert_not_called()
