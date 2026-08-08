from dingdongditch.contract.operation import ActionType
from dingdongditch.runtime.executor import _operation_timing


def test_standard_operation_timing_is_non_negative_and_phase_consistent():
    timing = _operation_timing(
        started_at=100,
        finished_at=180,
        action_started_at=110,
        action_completed_at=140,
        verification_started_at=150,
        verification_completed_at=170,
        target_resolution={"stages": [{"timestamp_ms": 120}, {"timestamp_ms": 130}]},
        action_type=ActionType.CLICK,
        include_verification=True,
    )
    assert timing == {
        "total_ms": 80,
        "target_resolution_ms": 20,
        "dispatch_ms": 10,
        "settle_ms": 10,
        "verification_ms": 20,
    }
    assert sum(timing[key] for key in ("target_resolution_ms", "dispatch_ms", "settle_ms", "verification_ms")) <= timing["total_ms"]


def test_non_target_navigation_omits_target_resolution_and_reports_navigation():
    timing = _operation_timing(
        started_at=10,
        finished_at=50,
        action_started_at=12,
        action_completed_at=40,
        action_type=ActionType.NAVIGATE,
    )
    assert "target_resolution_ms" not in timing
    assert timing["dispatch_ms"] == 28
    assert timing["navigation_ms"] == 28


def test_early_failure_still_has_runtime_total_only():
    assert _operation_timing(started_at=25, finished_at=25) == {"total_ms": 0}
