from dingdongditch.runtime.generation_monitor import (
    GenerationStatus,
    ProgressBasedGenerationMonitor,
)


def observe(monitor, index, at_ms, text, active):
    return monitor.observe(
        observation_id=f"obs-{index}",
        captured_at_ms=at_ms,
        text=text,
        generation_active=active,
        progress_signals=("generation_active",) if active else (),
    )


def finish(monitor, *, start_index, at_ms, text):
    result = None
    for offset in range(3):
        result = observe(
            monitor,
            start_index + offset,
            at_ms + offset * 1_000,
            text,
            False,
        )
    return result


def test_continuously_progressing_long_generation_completes():
    monitor = ProgressBasedGenerationMonitor(
        baseline_text="landing",
        no_progress_lease_ms=30_000,
    )
    for index in range(10):
        result = observe(
            monitor,
            index,
            index * 25_000,
            "response " + ("x" * index),
            True,
        )
        assert result.status == GenerationStatus.OBSERVING

    result = finish(
        monitor,
        start_index=10,
        at_ms=251_000,
        text="response complete",
    )
    assert result.status == GenerationStatus.COMPLETED


def test_stalled_generation_returns_generation_stalled_with_evidence():
    monitor = ProgressBasedGenerationMonitor(
        baseline_text="landing",
        no_progress_lease_ms=30_000,
    )
    observe(monitor, 1, 1_000, "partial response", True)
    result = observe(monitor, 2, 31_000, "partial response", True)

    assert result.status == GenerationStatus.GENERATION_STALLED
    assert result.evidence[-1]["generation_active"] is True
    assert result.evidence[-1]["meaningful_progress"] is False
    assert result.evidence[-1]["no_progress_ms"] == 30_000


def test_normal_short_response_completes_normally():
    monitor = ProgressBasedGenerationMonitor(
        baseline_text="landing",
        no_progress_lease_ms=30_000,
    )
    observe(monitor, 1, 1_000, "short response", True)
    result = finish(
        monitor,
        start_index=2,
        at_ms=2_000,
        text="short response complete",
    )

    assert result.status == GenerationStatus.COMPLETED


def test_completed_response_shorter_than_landing_page_completes():
    landing = "L" * 257
    response = "C" * 169
    monitor = ProgressBasedGenerationMonitor(
        baseline_text=landing,
        no_progress_lease_ms=30_000,
    )
    result = finish(
        monitor,
        start_index=1,
        at_ms=1_000,
        text=response,
    )

    assert len(response) < len(landing)
    assert result.status == GenerationStatus.COMPLETED
