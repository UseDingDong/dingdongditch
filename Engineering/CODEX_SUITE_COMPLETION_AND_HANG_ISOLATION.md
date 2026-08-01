# Phase 5 — Suite completion and hang isolation

## Final verdict

**FURTHER RESEARCH REQUIRED**

The suite is not yet proven to complete reliably twice. The audit did identify
and fix one deterministic runtime cause of a browser-engine stall, and the
focused regression is green, but the complete 351-test suite still exceeds the
bounded completion window and leaves a Node process visible after interruption.

No live website was used. All browser tests use repository-local fixtures.

## Environment and baseline

- OS: Windows (`win32`), PowerShell
- Python: 3.11.4
- pytest: 9.1.1
- pluggy: 1.6.0
- Playwright Python package: installed; bundled browser tests launch through
  Playwright
- pytest config: `pyproject.toml`, `testpaths = tests`
- Collected: **351 tests**
- Integration files: 15; unit files: 13
- Engines represented: bundled Chromium, Firefox, WebKit

Baseline collection was successful in 0.58 seconds. Raw artifacts are under
`Engineering/test-results/`, including `baseline_environment.txt` and
`baseline_collection.txt`.

## Original behavior

The first full run used unbuffered verbose pytest output, `--durations=10`, and
a 120-second outer bound. It timed out at approximately 122 seconds while
executing `test_basic_interactions_e2e.py`, after 351 items were collected.
The raw output is `Engineering/test-results/baseline_full_suite.txt`.

The first partitioned run established:

- unit partition: **121 passed in 19.36 seconds** after the timing-classification fix;
- integration partition: exceeded a 60-second bound;
- full partition: exceeded a 60-second bound.

## Isolation method and evidence

Isolation proceeded by collection, unit/integration partitioning, individual
adaptive timing isolation, engine-file isolation, and verbose last-test logs.
The WebKit log showed the last started test was:

`test_webkit_stop_on_failure_and_skip`

That test exercises a deliberate failed operation. The default production
screenshot policy is `ON_FAILURE`, so the failure path attempted a Playwright
screenshot. The WebKit process stalled there until the outer timeout.

The smallest reproducer passed after the fix:

`test_webkit_stop_on_failure_and_skip` — **1 passed in 24.42 seconds**.

The complete WebKit compatibility file then passed **8/8 in 62.45 seconds**.

## Root cause found and fix

Confirmed cause: screenshot capture had no operation-level bound. A failure
receipt could therefore block in `page.screenshot()` before cleanup, violating
the evidence layer’s non-interference requirement.

Smallest fix:

- `ScreenshotConfig.capture_timeout_ms` defaults to 5 seconds and validates
  positive values.
- `PlaywrightBackend.capture_screenshot()` passes that bound to Playwright.
- Capture failures remain additive metadata and cannot replace the operation
  verdict.

No browser action semantics, verification expectations, retries, or locator
behavior were weakened.

A separate proven contract defect was fixed: invalid plan timing now maps to
`PlanFailureKind.INVALID_PLAN_TIMING` instead of the generic
`invalid_operation` classification.

## Files changed

- `dingdongditch/contract/screenshot.py` — bounded screenshot configuration.
- `dingdongditch/backends/playwright_backend.py` — bounded capture call.
- `dingdongditch/contract/plan.py` — precise timing validation classification.
- `Engineering/run_suite.py` — bounded, reproducible collection/unit/integration/full runner.

The runner writes per-partition logs, emits JSON timing summaries, exits nonzero
on failure or timeout, and works from the repository root without shell-specific
test orchestration.

## Cleanup invariants

Existing tests cover runtime-owned versus injected backend ownership and normal
context/browser/Playwright cleanup. The isolated WebKit failure now reaches
teardown. However, after the interrupted full-suite run, a `node` process was
still visible, so the “no orphan process after every complete run” criterion is
not proven. No process was killed during this readout audit.

## Engine-specific results

- Chromium: exercised in focused suites; no new hang isolated here.
- Firefox: exercised in focused suites; no new hang isolated here.
- WebKit: **8/8 passed** after the bounded screenshot fix; the prior stall was
  deterministic and screenshot-related.

The shared lifecycle contract remains common across all engines. The remaining
adaptive-video assertion (`test_adaptation_disabled_does_not_extend_video_wait`)
is environment/media-timing sensitive in this run; it is a test failure, not a
hang, and requires separate evidence before any semantic change.

## Tests and commands

Collection:

```text
python -m pytest --collect-only -q
```

Bounded runner:

```text
python Engineering/run_suite.py --timeout 180 --full
```

Focused final command:

```text
python -m pytest tests/unit tests/integration/test_webkit_compatibility.py -q --durations=10
```

Focused final result: **129 passed in 75.19 seconds**.

WebKit result: **8 passed in 62.45 seconds**.

Complete-suite run 1: timed out at the bounded outer limit before a pytest
summary. Complete-suite run 2: timed out at 180 seconds; pytest also reported
an `OSError: [Errno 22] Invalid argument` while its terminal writer was
finishing after interruption. The two final raw/partition logs are in
`Engineering/test-results/`.

## Ten slowest observed tests

The stable focused timing sample was:

1. `test_webkit_ten_sequential_owned_plans` — 24.40s
2. `test_webkit_stop_on_failure_and_skip` — 23.59s (before bounded capture fix)
3. `test_webkit_headed_and_headless_plans` — 5.11–5.20s
4. `test_webkit_comprehensive_interaction_plan` — 4.27–4.46s
5. `test_run_plan_stdin::test_repeated_stdin_runs_cleanup` — 3.50–5.33s
6. `test_run_plan_stdin::test_stdin_and_file_identical_receipts` — 2.32–3.61s
7. `test_browser_boundary::test_explicit_browser_config_headless_false_metadata` — ~2.16s
8. `test_browser_boundary::test_new_session_gets_new_ids` — ~1.95–3.01s
9. `test_browser_boundary::test_session_id_reused_across_operations` — ~1.90s
10. `test_browser_boundary::test_omitted_config_defaults_in_execute_operation` — ~1.87s

These are observed durations, not claims that the entire suite completed.

## Remaining risks and next bounded action

1. Isolate the adaptive-media assertion on each engine and record media state,
   plan deadline, and actual wait duration before changing semantics.
2. Run each integration file in a separate process with the new runner and
   inspect process trees after timeout; identify the surviving Node owner.
3. Execute the complete suite with a larger, explicitly documented outer bound
   only after file-level timings are known; then repeat twice from clean
   processes.
4. Add a process-cleanup assertion/diagnostic around fixture-server and
   Playwright child-process ownership once the owner is proven.

The repository is **not stabilized** under the requested success criteria yet,
but the largest proven browser hang has a minimal bounded fix and a green
engine-specific regression.
