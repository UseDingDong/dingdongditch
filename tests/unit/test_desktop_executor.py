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
