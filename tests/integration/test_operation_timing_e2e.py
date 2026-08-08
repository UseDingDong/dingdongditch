"""Standard receipt timing coverage for browser operation families."""

from __future__ import annotations

from pathlib import Path

from dingdongditch import (
    Action, ActionType, ComboboxSelection, Expectation, ExpectationType,
    Locator, LocatorStrategy, Operation, UploadAuthorization, Verdict,
    WaitCondition, WaitConditionType, execute_operation,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


def _tid(value: str) -> Locator:
    return Locator(LocatorStrategy.TEST_ID, value)


def _assert_timing(receipt, *, target: bool, verification: bool) -> None:
    timing = receipt.operation_timing
    assert timing is not None and timing["total_ms"] >= 0
    for value in timing.values():
        assert value >= 0
    if target:
        assert "target_resolution_ms" in timing
    else:
        assert "target_resolution_ms" not in timing
    assert "dispatch_ms" in timing
    if verification:
        assert "verification_ms" in timing
    phases = [
        timing[key]
        for key in ("target_resolution_ms", "dispatch_ms", "settle_ms", "verification_ms")
        if key in timing
    ]
    assert sum(phases) <= timing["total_ms"]


def test_standard_timing_for_navigation_target_actions_wait_and_failure(fixture_url):
    backend = PlaywrightBackend()
    backend.start()
    try:
        nav = execute_operation(
            Operation("nav", fixture_url, Action(ActionType.NAVIGATE), [
                Expectation(ExpectationType.URL, url_value=fixture_url)
            ]), backend=backend,
        )
        assert nav.verdict is Verdict.VERIFIED
        _assert_timing(nav, target=False, verification=True)
        assert "navigation_ms" in nav.operation_timing

        click = execute_operation(
            Operation("click", fixture_url, Action(ActionType.CLICK, locator=_tid("target-control")), [
                Expectation(ExpectationType.ATTRIBUTE, locator=_tid("target-control"), attribute_name="data-state", attribute_value="active")
            ]), backend=backend,
        )
        assert click.verdict is Verdict.VERIFIED
        _assert_timing(click, target=True, verification=True)

        fill = execute_operation(
            Operation("fill", fixture_url, Action(ActionType.FILL, locator=_tid("text-input"), text="timed"), [
                Expectation(ExpectationType.ATTRIBUTE, locator=_tid("text-input"), attribute_name="value", attribute_value="timed")
            ]), backend=backend,
        )
        assert fill.verdict is Verdict.VERIFIED
        _assert_timing(fill, target=True, verification=True)

        keys = execute_operation(
            Operation("keys", fixture_url, Action(ActionType.PRESS_KEY, locator=_tid("key-input"), key="Enter"), []), backend=backend,
        )
        _assert_timing(keys, target=True, verification=False)

        select = execute_operation(
            Operation("select", fixture_url, Action(ActionType.SELECT_OPTION, locator=_tid("color-select"), option_value="red"), [
                Expectation(ExpectationType.ATTRIBUTE, locator=_tid("color-select"), attribute_name="value", attribute_value="red")
            ]), backend=backend,
        )
        assert select.verdict is Verdict.VERIFIED
        _assert_timing(select, target=True, verification=True)

        scroll = execute_operation(
            Operation("scroll", fixture_url, Action(ActionType.SCROLL_TO_TARGET, locator=_tid("below-fold")), [
                Expectation(ExpectationType.ELEMENT_IN_VIEWPORT, locator=_tid("below-fold"), in_viewport=True)
            ]), backend=backend,
        )
        assert scroll.verdict is Verdict.VERIFIED
        _assert_timing(scroll, target=True, verification=True)

        wait = execute_operation(
            Operation("wait", fixture_url, Action(ActionType.WAIT_FOR, wait_condition=WaitCondition(WaitConditionType.ELEMENT_VISIBLE, locator=_tid("target-control"))), []), backend=backend,
        )
        assert wait.verdict is Verdict.VERIFIED
        _assert_timing(wait, target=True, verification=False)

        failed = execute_operation(
            Operation("failed", fixture_url, Action(ActionType.CLICK, locator=_tid("disabled-proceed")), []), backend=backend,
        )
        assert failed.verdict is Verdict.EXECUTION_FAILED
        _assert_timing(failed, target=True, verification=False)
    finally:
        backend.stop()


def test_combobox_and_upload_receive_standard_target_timing(fixture_url):
    from dingdongditch.contract.modes import TextMatchMode

    root = Path(__file__).parents[1] / "fixtures" / "local_test_app"
    upload_file = (root / "upload-one.txt").resolve()
    url = fixture_url.replace("index.html", "modern_ats_fixture.html")
    backend = PlaywrightBackend()
    backend.start()
    try:
        execute_operation(Operation("nav", url, Action(ActionType.NAVIGATE), []), backend=backend)
        combo = execute_operation(
            Operation(
                "combo", url,
                Action(ActionType.SELECT_COMBOBOX_OPTION, locator=_tid("city"), combobox_selection=ComboboxSelection("New York", "New York, New York, United States", TextMatchMode.EXACT)),
                [],
            ), backend=backend,
        )
        assert combo.action_executed_successfully is True
        _assert_timing(combo, target=True, verification=False)
        upload = execute_operation(
            Operation(
                "upload", url,
                Action(ActionType.UPLOAD_FILE, locator=Locator(LocatorStrategy.CSS, "#resume-upload"), upload_authorization=UploadAuthorization((str(upload_file),), allowed_files=(str(upload_file),))),
                [Expectation(ExpectationType.TEXT, locator=_tid("resume-chip"), text_value=upload_file.name)],
            ), backend=backend,
        )
        assert upload.verdict is Verdict.VERIFIED
        _assert_timing(upload, target=True, verification=True)
    finally:
        backend.stop()
