"""Validate a small benchmark_runtime result against conservative CI gates.

This is a result checker, not another benchmark harness.  It consumes the JSON
written by benchmark_runtime.py and keeps reliability checks separate from the
deliberately broad shared-runner performance threshold.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parent
DEFAULT_BASELINE = ROOT / "ci_regression_baseline.json"


def _mapping(value: Any, name: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        errors.append(f"{name} must be an object")
        return {}
    return value


def _number(value: Any, name: str, errors: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{name} must be a number")
        return None
    if value < 0:
        errors.append(f"{name} must not be negative")
        return None
    return float(value)


def validate(result: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[str]:
    """Return deterministic gate failures; an empty list means the result passed."""
    errors: list[str] = []
    if result.get("schema_version") != 1:
        errors.append("benchmark result schema_version must be 1")
    if baseline.get("schema_version") != 1:
        errors.append("baseline schema_version must be 1")

    repetitions = result.get("repetitions_per_activity")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        errors.append("repetitions_per_activity must be a positive integer")
        return errors

    local = _mapping(result.get("local_benchmark"), "local_benchmark", errors)
    reliability = _mapping(baseline.get("reliability"), "baseline reliability", errors)
    activities = reliability.get("activities_per_repetition")
    verified_activities = reliability.get("verified_activities_per_repetition")
    if isinstance(activities, bool) or not isinstance(activities, int) or activities <= 0:
        errors.append("baseline activities_per_repetition must be a positive integer")
        return errors
    if (
        isinstance(verified_activities, bool)
        or not isinstance(verified_activities, int)
        or verified_activities < 0
        or verified_activities > activities
    ):
        errors.append("baseline verified_activities_per_repetition is invalid")
        return errors

    expected_receipts = repetitions * activities
    expected_verified = repetitions * verified_activities
    receipts = _number(local.get("receipt_count"), "local_benchmark.receipt_count", errors)
    successful = _number(
        local.get("successful_action_count"), "local_benchmark.successful_action_count", errors
    )
    verified = _number(local.get("verified_count"), "local_benchmark.verified_count", errors)
    fallbacks = _number(
        local.get("atomic_snapshot_fallback_count"),
        "local_benchmark.atomic_snapshot_fallback_count",
        errors,
    )
    if receipts is not None and receipts != expected_receipts:
        errors.append(f"expected {expected_receipts} local receipts, got {receipts:g}")
    if verified is not None and verified != expected_verified:
        errors.append(f"expected {expected_verified} verified local receipts, got {verified:g}")
    if receipts and successful is not None:
        rate = successful / receipts
        minimum_rate = _number(
            reliability.get("minimum_action_success_rate"),
            "baseline minimum_action_success_rate",
            errors,
        )
        if minimum_rate is not None and rate < minimum_rate:
            errors.append(f"local action success rate {rate:.3f} is below {minimum_rate:.3f}")
    maximum_fallbacks = _number(
        reliability.get("maximum_atomic_snapshot_fallback_count"),
        "baseline maximum_atomic_snapshot_fallback_count",
        errors,
    )
    if fallbacks is not None and maximum_fallbacks is not None and fallbacks > maximum_fallbacks:
        errors.append(
            f"atomic snapshot fallbacks {fallbacks:g} exceed {maximum_fallbacks:g}"
        )

    performance = _mapping(baseline.get("performance"), "baseline performance", errors)
    stage = performance.get("stage")
    if not isinstance(stage, str) or not stage:
        errors.append("baseline performance stage must be a non-empty string")
        return errors
    summary = _mapping(result.get("summary"), "summary", errors)
    measured_stage = _mapping(summary.get(stage), f"summary.{stage}", errors)
    median = _number(measured_stage.get("median_ms"), f"summary.{stage}.median_ms", errors)
    reference = _number(performance.get("reference_median_ms"), "baseline reference_median_ms", errors)
    multiplier = _number(
        performance.get("maximum_median_multiplier"),
        "baseline maximum_median_multiplier",
        errors,
    )
    floor = _number(
        performance.get("absolute_median_floor_ms"),
        "baseline absolute_median_floor_ms",
        errors,
    )
    if None not in (median, reference, multiplier, floor):
        allowed = max(reference * multiplier, floor)
        if median > allowed:
            errors.append(
                f"{stage} median {median:.1f}ms exceeds conservative {allowed:.1f}ms limit"
            )
    return errors


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("JSON root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()
    try:
        result = _read_json(args.result)
        baseline = _read_json(args.baseline)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_input", "error": type(exc).__name__}))
        return 2
    failures = validate(result, baseline)
    print(
        json.dumps(
            {
                "status": "passed" if not failures else "failed",
                "result": str(args.result),
                "baseline": str(args.baseline),
                "failures": failures,
            }
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
