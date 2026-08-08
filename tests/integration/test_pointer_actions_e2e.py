"""Real Playwright coverage for typed pointer movement."""

from __future__ import annotations

import pytest

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
)
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    Locator,
    LocatorStrategy,
    Operation,
)
from dingdongditch.contract.expectation import (
    Expectation,
    ExpectationType,
    UrlMatchMode,
)
from dingdongditch.contract.pointer import PointerMoveRequest, PointerOrigin
from dingdongditch.contract.plan import ExecutionPlan, PlanVerdict
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan


def _backend() -> PlaywrightBackend:
    return PlaywrightBackend(
        BrowserConfig(
            provider=BrowserProvider.PLAYWRIGHT,
            engine=BrowserEngine.CHROMIUM,
            channel=BrowserChannel.BUNDLED,
            headless=True,
        )
    )


def _navigate(backend: PlaywrightBackend, url: str) -> None:
    receipt = execute_operation(
        Operation(
            operation_id="nav",
            url=url,
            action=Action(type=ActionType.NAVIGATE),
        ),
        backend=backend,
    )
    assert receipt.action_executed_successfully


def _url_expectation() -> list[Expectation]:
    return [
        Expectation(
            type=ExpectationType.URL,
            url_value="index.html",
            url_match=UrlMatchMode.CONTAINS,
        )
    ]


def test_pointer_to_element_and_offset_generate_verified_receipts(fixture_url):
    backend = _backend()
    backend.start()
    try:
        _navigate(backend, fixture_url)
        locator = Locator(strategy=LocatorStrategy.TEST_ID, value="hover-target")
        center = execute_operation(
            Operation(
                operation_id="pointer-center",
                url=fixture_url,
                action=Action(
                    type=ActionType.POINTER_MOVE,
                    locator=locator,
                    pointer_request=PointerMoveRequest(
                        PointerOrigin.ELEMENT_CENTER, steps=8
                    ),
                ),
                expectations=_url_expectation(),
            ),
            backend=backend,
        )
        assert center.verdict == Verdict.VERIFIED
        assert center.action_evidence["origin"] == "element_center"
        assert center.action_evidence["steps"] == 8
        assert center.action_evidence["position_verification"]["verified"] is True
        assert center.action_evidence["bounding_box"] is not None

        offset = execute_operation(
            Operation(
                operation_id="pointer-offset",
                url=fixture_url,
                action=Action(
                    type=ActionType.POINTER_MOVE,
                    locator=locator,
                    pointer_request=PointerMoveRequest(
                        PointerOrigin.ELEMENT_OFFSET, x=2, y=3, steps=3
                    ),
                ),
                expectations=_url_expectation(),
            ),
            backend=backend,
        )
        box = offset.action_evidence["bounding_box"]
        assert offset.verdict == Verdict.VERIFIED
        assert offset.action_evidence["resolved_position"] == {
            "x": box["x"] + 2,
            "y": box["y"] + 3,
        }
        assert offset.action_evidence["previous_position"] == center.action_evidence[
            "final_position"
        ]
    finally:
        backend.stop()


def test_absolute_pointer_move_receipt_is_deterministic(fixture_url):
    backend = _backend()
    backend.start()
    try:
        _navigate(backend, fixture_url)
        operation = Operation(
            operation_id="pointer-absolute",
            url=fixture_url,
            action=Action(
                type=ActionType.POINTER_MOVE,
                pointer_request=PointerMoveRequest(
                    PointerOrigin.VIEWPORT, x=100, y=120, steps=6
                ),
            ),
            expectations=_url_expectation(),
        )
        first = execute_operation(operation, backend=backend)
        second = execute_operation(operation, backend=backend)
        assert first.verdict == second.verdict == Verdict.VERIFIED
        for receipt in (first, second):
            assert receipt.action_evidence["resolved_position"] == {
                "x": 100.0,
                "y": 120.0,
            }
            assert receipt.action_evidence["steps"] == 6
            assert receipt.action_evidence["position_verification"]["verified"] is True
    finally:
        backend.stop()


def test_missing_pointer_target_returns_typed_failure_receipt(fixture_url):
    backend = _backend()
    backend.start()
    try:
        _navigate(backend, fixture_url)
        receipt = execute_operation(
            Operation(
                operation_id="pointer-missing",
                url=fixture_url,
                locate_retry_ms=0,
                action=Action(
                    type=ActionType.POINTER_MOVE,
                    locator=Locator(
                        strategy=LocatorStrategy.TEST_ID, value="does-not-exist"
                    ),
                    pointer_request=PointerMoveRequest(
                        PointerOrigin.ELEMENT_CENTER
                    ),
                ),
            ),
            backend=backend,
        )
        assert receipt.verdict == Verdict.EXECUTION_FAILED
        assert receipt.action_executed_successfully is False
        assert receipt.failure_kind == "zero_after_primary"
        assert receipt.target_resolution is not None
    finally:
        backend.stop()


@pytest.mark.parametrize(("x", "y"), [(1280, 10), (10, 720)])
def test_runtime_rejects_pointer_outside_viewport(fixture_url, x, y):
    backend = _backend()
    backend.start()
    try:
        _navigate(backend, fixture_url)
        receipt = execute_operation(
            Operation(
                operation_id=f"pointer-outside-{x}-{y}",
                url=fixture_url,
                action=Action(
                    type=ActionType.POINTER_MOVE,
                    pointer_request=PointerMoveRequest(
                        PointerOrigin.VIEWPORT, x=x, y=y
                    ),
                ),
            ),
            backend=backend,
        )
        assert receipt.action_executed_successfully is False
        assert receipt.failure_kind == "pointer_coordinates_out_of_viewport"
        assert receipt.action_evidence["dispatched"] is False
    finally:
        backend.stop()


def test_pointer_plan_receipt_preserves_screenshot_evidence(fixture_url, tmp_path):
    backend = _backend()
    backend.start()
    try:
        _navigate(backend, fixture_url)
        plan = ExecutionPlan(
            plan_id="pointer-screenshot",
            browser_config=backend.browser_config,
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS,
                artifact_root=str(tmp_path),
            ),
            operations=[
                Operation(
                    operation_id="pointer-with-screenshot",
                    url=fixture_url,
                    action=Action(
                        type=ActionType.POINTER_MOVE,
                        pointer_request=PointerMoveRequest(
                            PointerOrigin.VIEWPORT, x=80, y=90, steps=2
                        ),
                    ),
                    expectations=_url_expectation(),
                )
            ],
        )
        receipt = execute_plan(plan, backend=backend)
        assert receipt.plan_verdict == PlanVerdict.VERIFIED
        screenshots = receipt.steps[0].receipt.artifacts
        assert len(screenshots) == 1
        assert screenshots[0]["status"] == "available"
        assert list(tmp_path.glob("*.png"))
    finally:
        backend.stop()
