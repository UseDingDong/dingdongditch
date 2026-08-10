from __future__ import annotations

from Engineering.runtime_latency_audit.check_ci_regression import validate


def _baseline() -> dict:
    return {
        "schema_version": 1,
        "reliability": {
            "activities_per_repetition": 7,
            "verified_activities_per_repetition": 6,
            "minimum_action_success_rate": 1.0,
            "maximum_atomic_snapshot_fallback_count": 0,
        },
        "performance": {
            "stage": "total_operation",
            "reference_median_ms": 270.0,
            "maximum_median_multiplier": 8.0,
            "absolute_median_floor_ms": 3000.0,
        },
    }


def _result() -> dict:
    return {
        "schema_version": 1,
        "repetitions_per_activity": 2,
        "local_benchmark": {
            "receipt_count": 14,
            "verified_count": 12,
            "successful_action_count": 14,
            "atomic_snapshot_fallback_count": 0,
        },
        "summary": {"total_operation": {"median_ms": 500.0}},
    }


def test_ci_regression_gate_accepts_expected_reliability_and_broad_performance():
    assert validate(_result(), _baseline()) == []


def test_ci_regression_gate_rejects_action_failure_and_unexpected_fallback():
    result = _result()
    result["local_benchmark"]["successful_action_count"] = 13
    result["local_benchmark"]["atomic_snapshot_fallback_count"] = 1

    failures = validate(result, _baseline())

    assert any("success rate" in failure for failure in failures)
    assert any("fallbacks" in failure for failure in failures)


def test_ci_regression_gate_rejects_material_median_regression():
    result = _result()
    result["summary"]["total_operation"]["median_ms"] = 3001.0

    assert any("median" in failure for failure in validate(result, _baseline()))
