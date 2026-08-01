# Complete-suite reliability and process-cleanup milestone

## Final verdict

**FURTHER RESEARCH REQUIRED**

The milestone is not fully complete: the 351-test complete suite did not reach
pytest summaries twice within the bounded final runs, and one adaptive-media
expectation remains failing. The proven WebKit failure-path screenshot stall is
fixed, the bounded runner now owns and cleans only its spawned process tree, and
the previously problematic subset passed five consecutive times.

No live websites were used. No hidden retries, skips, weakened assertions, or
arbitrary sleeps were added.

## Environment and preserved baseline

- Windows `win32`, PowerShell
- Python 3.11.4
- pytest 9.1.1, pluggy 1.6.0
- Repository root: `C:\Users\user\Desktop\DingDongDitch`
- Collected tests: **351**
- Engines: bundled Chromium, Firefox, WebKit
- Previous report preserved at `Engineering/test-results/final-stabilization/previous_report.md`
- New artifacts are under `Engineering/test-results/final-stabilization/`

The environment, collection output, process snapshots, isolation logs, and
five repeat logs are preserved in that directory.

## Original timeout and isolation

The prior baseline timed out at about 122 seconds during early integration
execution. Partitioning showed:

- unit tests: 121 passed in about 19 seconds;
- adaptive timing file: completed in 46 seconds but had five expectation
  failures before the timing-classification fix;
- WebKit compatibility: stalled in `test_webkit_stop_on_failure_and_skip`;
- complete integration/full partitions: exceeded their bounded windows.

Verbose WebKit isolation proved the last started test was the deliberate
failure-path test. Its default `ON_FAILURE` screenshot capture could block
inside Playwright WebKit before cleanup.

## Root cause and fix

Confirmed root cause: evidence screenshot capture had no bounded Playwright
operation timeout. On a failed operation, `page.screenshot()` could prevent
the backend from reaching cleanup.

Smallest fix:

- `ScreenshotConfig` now validates `capture_timeout_ms` (default 5 seconds).
- `PlaywrightBackend.capture_screenshot()` passes that bound to Playwright.
- Screenshot errors remain metadata and never replace the original verdict.

This preserved the Host → typed plan → deterministic runtime → backend →
receipt architecture and did not alter browser action semantics.

A separately proven contract issue was also corrected: invalid plan timing now
returns `invalid_plan_timing`, not generic `invalid_operation`.

## Runner and ownership changes

`Engineering/run_suite.py` now:

- runs collection, unit, integration, and optional full partitions;
- emits JSON result timing and per-partition logs;
- preserves pytest exit codes;
- uses a bounded subprocess wait;
- on timeout, terminates only its own process group/tree (`taskkill /T /F` on
  Windows, terminate/kill fallback elsewhere);
- distinguishes timeout (`124`) from test exit failure.

After a bounded integration timeout, the runner’s spawned Python/Node tree was
gone. A single Node process with PID 22964 remained before and after the final
pass, with an earlier timestamp and no ownership relationship provable under
the environment’s restricted process-query permissions. It was not killed or
classified as a DingDongDitch orphan.

## Cleanup invariants

The focused unit and WebKit cleanup tests passed. The runner’s timeout cleanup
was exercised and left no newly spawned process. Existing backend tests cover
runtime-owned browser/context/page cleanup and caller-owned injected backends.

Not fully proven for a complete suite: zero orphan processes after every test,
fixture-server state after all integration files, and complete two-run process
snapshots, because the full suite did not finish.

## Adaptive-media investigation

The remaining isolated failure is:

`tests/integration/test_adaptive_plan_timing_e2e.py::test_adaptation_disabled_does_not_extend_video_wait`

Observed result: `VERIFIED` where the test expects `NOT_VERIFIED`. The test
starts a local ending video and uses a 100 ms `video_ended` wait with adaptive
extension disabled. The result indicates browser/fixture scheduling allowed the
video to reach `ended` before the bounded observation expired. This is currently
consistent with browser timing or fixture timing; repository evidence does not
prove a runtime deadline defect. No assertion was weakened and no test was
skipped.

Smallest next action: capture the video element’s `currentTime`, `duration`,
`ended`, operation start, and plan deadline at each sample on Chromium,
Firefox, and WebKit, then decide whether the fixture’s timing assumption or
runtime sampling contract is wrong.

## Validation results

Focused final command:

```text
python -m pytest tests/unit tests/integration/test_webkit_compatibility.py -q --durations=10
```

Result: **129 passed in 75.19 seconds**.

WebKit compatibility: **8 passed in 62.45 seconds**.

Previously problematic subset, five consecutive clean processes:

`test_webkit_stop_on_failure_and_skip`: **5/5 passed**, approximately 24.7–25.1
seconds each.

Bounded runner validation:

- collection: passed;
- unit partition: passed (121 tests, approximately 14.6–19.4 seconds);
- integration partition: timed out at the configured bound, with spawned tree
  cleanup;
- full partition: timed out at the configured bound.

Final complete-suite run 1: timed out at 180 seconds without a pytest summary.
Final complete-suite run 2: timed out at 180 seconds; after outer interruption,
pytest also emitted a terminal-writer `OSError: [Errno 22] Invalid argument`.

Therefore there are no valid complete-suite run-1/run-2 totals or ten-slowest
complete-suite lists to claim. Observed slowest focused tests remain the WebKit
sequential-owned-plans and failure-path tests, both around 24 seconds.

## Files changed

- `Engineering/run_suite.py`: bounded ownership-safe process-tree cleanup.
- `dingdongditch/contract/screenshot.py`: screenshot capture bound.
- `dingdongditch/backends/playwright_backend.py`: bounded screenshot call.
- `dingdongditch/contract/plan.py`: precise invalid timing classification.

## Remaining risks and next bounded step

The smallest remaining reproducer is the single adaptive-media test above. The
smallest completion blocker is the integration partition’s aggregate runtime;
the current evidence does not prove a deadlock after the screenshot fix.

Next step: run each integration file in a separate runner invocation with a
90-second bound and preserved verbose logs, then run the adaptive file with
structured media-state diagnostics. Only after those results should the complete
suite bound be chosen and two clean full runs attempted again.
