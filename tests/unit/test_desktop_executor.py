from pathlib import Path

from dingdongditch.backends.windows_desktop_backend import DesktopDispatchResult
from dingdongditch.contract.desktop import (
    ApprovedApplication,
    DesktopAction,
    DesktopActionType,
    DesktopExecutionPlan,
    DesktopOperation,
)
from dingdongditch.contract.runtime import LifecycleState
from dingdongditch.contract.screenshot import (
    DesktopRedactionRegion,
    ScreenshotConfig,
    ScreenshotPolicy,
)
from dingdongditch.runtime.desktop_executor import (
    DesktopActionReceipt,
    DesktopPlanReceipt,
    execute_desktop_plan,
)


class FakeBackend:
    backend_identity = "fake-windows-uia"
    session_id = "fake-session"
    lifecycle_state = LifecycleState.NOT_STARTED
    cleanup_errors = []
    owned_process_ids = ()
    owned_window_handles = ()

    @staticmethod
    def capabilities():
        return {"domain": "windows_desktop"}

    def start(self):
        self.lifecycle_state = LifecycleState.ACTIVE

    def dispatch(self, action):
        return DesktopDispatchResult(
            ok=True,
            started_at_ms=1,
            completed_at_ms=2,
            failure_kind=None,
            error=None,
            evidence={"verification_result": {"passed": True}},
        )

    def stop(self):
        self.lifecycle_state = LifecycleState.STOPPED

    def remaining_owned_process_ids(self):
        return []


def test_receipt_round_trip_and_verified_plan():
    plan = DesktopExecutionPlan(
        plan_id="round-trip",
        operations=(
            DesktopOperation(
                "launch",
                DesktopAction(
                    type=DesktopActionType.LAUNCH_APPLICATION,
                    application=ApprovedApplication.NOTEPAD,
                ),
            ),
        ),
    )
    receipt = execute_desktop_plan(plan, backend=FakeBackend(), stop_session=True)
    restored = DesktopPlanReceipt.from_dict(receipt.to_dict())
    assert restored.to_dict() == receipt.to_dict()
    assert restored.plan_verdict.value == "VERIFIED"


def test_cleanup_after_partial_failure():
    class FailingBackend(FakeBackend):
        stopped = False

        def dispatch(self, action):
            return DesktopDispatchResult(
                ok=False,
                started_at_ms=1,
                completed_at_ms=2,
                failure_kind="window_timeout",
                error="timed out",
                evidence={},
            )

        def stop(self):
            self.stopped = True
            self.lifecycle_state = LifecycleState.STOPPED

    backend = FailingBackend()
    plan = DesktopExecutionPlan(
        plan_id="partial-failure",
        operations=(
            DesktopOperation(
                "one",
                DesktopAction(
                    type=DesktopActionType.LAUNCH_APPLICATION,
                    application=ApprovedApplication.NOTEPAD,
                ),
            ),
            DesktopOperation(
                "two",
                DesktopAction(
                    type=DesktopActionType.LAUNCH_APPLICATION,
                    application=ApprovedApplication.NOTEPAD,
                ),
            ),
        ),
    )
    receipt = execute_desktop_plan(plan, backend=backend, stop_session=True)
    assert backend.stopped
    assert receipt.attempted_step_count == 1
    assert receipt.skipped_operation_ids == ["two"]


def test_mandatory_redaction_failure_is_explicit_and_stops_plan(tmp_path):
    class RedactionUnavailableBackend(FakeBackend):
        screenshot_calls = 0
        dispatch_calls = 0

        def dispatch(self, action):
            self.dispatch_calls += 1
            return super().dispatch(action)

        def capture_screenshot(self, **kwargs):
            self.screenshot_calls += 1
            raise RuntimeError(
                "mandatory desktop screenshot redaction is unavailable"
            )

    backend = RedactionUnavailableBackend()
    action = DesktopAction(
        type=DesktopActionType.LAUNCH_APPLICATION,
        application=ApprovedApplication.NOTEPAD,
    )
    plan = DesktopExecutionPlan(
        plan_id="mandatory-redaction",
        operations=(DesktopOperation("one", action), DesktopOperation("two", action)),
        screenshot_config=ScreenshotConfig(
            policy=ScreenshotPolicy.ALWAYS,
            artifact_root=str(tmp_path),
            mandatory_redaction=True,
        ),
    )
    receipt = execute_desktop_plan(plan, backend=backend, stop_session=True)
    assert receipt.plan_verdict.value == "EXECUTION_FAILED"
    assert receipt.completion_status.value == "stopped"
    assert receipt.attempted_step_count == 1
    assert receipt.skipped_operation_ids == ["two"]
    assert receipt.failure_kind == "screenshot_redaction_failed"
    assert backend.dispatch_calls == 1
    assert backend.screenshot_calls == 1
    step = receipt.steps[0]
    assert step.verdict.value == "EXECUTION_FAILED"
    assert step.failure_kind == "screenshot_redaction_failed"
    assert "redaction is unavailable" in step.execution_error
    assert step.screenshots == []
    assert "redaction is unavailable" in step.action_evidence["screenshot_error"]
    assert list(tmp_path.iterdir()) == []


def test_mandatory_region_attestation_is_preserved_in_receipt(tmp_path):
    region = DesktopRedactionRegion("secret", 2, 3, 4, 5)

    class AttestingBackend(FakeBackend):
        def capture_screenshot(self, **kwargs):
            return {
                "path": str(tmp_path / "redacted.png"),
                "reason": "after_success",
                "redaction_status": "applied",
                "redacted_regions": [region.describe()],
            }

    plan = DesktopExecutionPlan(
        plan_id="attested-redaction",
        operations=(
            DesktopOperation(
                "one",
                DesktopAction(
                    type=DesktopActionType.LAUNCH_APPLICATION,
                    application=ApprovedApplication.NOTEPAD,
                ),
            ),
        ),
        screenshot_config=ScreenshotConfig(
            policy=ScreenshotPolicy.ALWAYS,
            artifact_root=str(tmp_path),
            mandatory_redaction=True,
            desktop_redaction_regions=(region,),
        ),
    )
    receipt = execute_desktop_plan(plan, backend=AttestingBackend(), stop_session=True)
    assert receipt.plan_verdict.value == "VERIFIED"
    assert receipt.steps[0].screenshots[0]["redacted_regions"] == [region.describe()]


def test_mandatory_region_attestation_mismatch_fails_closed(tmp_path):
    requested = DesktopRedactionRegion("requested", 2, 3, 4, 5)

    class MisattestingBackend(FakeBackend):
        def capture_screenshot(self, **kwargs):
            return {
                "path": str(tmp_path / "unsafe.png"),
                "redaction_status": "applied",
                "redacted_regions": [],
            }

    plan = DesktopExecutionPlan(
        plan_id="misattested-redaction",
        operations=(
            DesktopOperation(
                "one",
                DesktopAction(
                    type=DesktopActionType.LAUNCH_APPLICATION,
                    application=ApprovedApplication.NOTEPAD,
                ),
            ),
        ),
        screenshot_config=ScreenshotConfig(
            policy=ScreenshotPolicy.ALWAYS,
            artifact_root=str(tmp_path),
            mandatory_redaction=True,
            desktop_redaction_regions=(requested,),
        ),
    )
    receipt = execute_desktop_plan(plan, backend=MisattestingBackend(), stop_session=True)
    assert receipt.plan_verdict.value == "EXECUTION_FAILED"
    assert receipt.failure_kind == "screenshot_redaction_failed"
    assert receipt.steps[0].screenshots == []
    assert receipt.steps[0].action_evidence["requested_desktop_redaction_regions"] == [
        requested.describe()
    ]
