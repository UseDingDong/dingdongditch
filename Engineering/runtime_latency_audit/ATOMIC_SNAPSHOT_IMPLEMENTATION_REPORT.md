# Atomic Element Snapshot Optimization Report

Date: 2026-07-29  
Result: **PASS — optimization acceptance criteria met**

The optimized verification and inspection paths preserve the existing public
dictionary, receipt, verdict, and inspection shapes. The complete repository
integration suite is not green because it contains 41 failures outside this
change; those failures are documented under Test Results rather than hidden.

## Root cause confirmed

`PlaywrightBackend.read_element_state()` resolved one target and then issued
serial browser calls for visibility, enabled state, text, ten attributes, live
input value, checked state, and viewport state.

For a unique unconstrained target, the old path required:

- one browser round-trip for primary cardinality;
- sixteen post-resolution browser round-trips for state.

Inspection and DOM expectation verification both used this shared path. The
baseline measured 173.092 ms average verification and 258.985 ms average
inspection latency.

## Architecture

`ElementStateSnapshot` is an internal frozen typed structure with:

- explicit `available`, `missing`, `ambiguous`, and `unavailable` states;
- match count, existence, ambiguity, visibility, enabled state, viewport state;
- checked, selected, focused, text, live value, role, bounding box, attributes;
- target-resolution trace, collection mode, and error;
- a compatibility projection that recreates the prior public/evidence
  dictionary shape.

Cardinality and frame resolution are unchanged. Once exactly one target is
resolved, one locator evaluation gathers the state synchronously in the target
document. The snapshot is immediately consumed and never cached across an
action, verification, navigation, or inspection boundary.

Only an explicit browser response of `supported: false` may enter the retained
serial fallback. Playwright errors, detached elements, and destroyed execution
contexts propagate through the existing unavailable/indeterminate handling;
they do not fall back and accidentally observe a replacement element or a new
document. Every fallback adds an `atomic_element_snapshot_fallback` backend
telemetry event.

## Browser round-trips

For a unique, unconstrained DOM target:

| Path | Resolution | State collection | Total | Reduction |
|---|---:|---:|---:|---:|
| Baseline | 1 | 16 | 17 | — |
| Optimized | 1 | 1 | 2 | 88.2% |

Constrained-target resolution is intentionally unchanged. It may require
additional browser calls to preserve existing constraint and trace semantics.

The optimized benchmark captured 205 atomic snapshots and used the serial
fallback zero times.

## Latency before and after

Identical command and workload:

```powershell
python Engineering\runtime_latency_audit\benchmark_runtime.py `
  --repetitions 20 --complex-repetitions 5
```

### Verification

| Metric | Baseline ms | Optimized ms | Saving ms | Improvement |
|---|---:|---:|---:|---:|
| Average | 173.092 | 39.435 | 133.657 | 77.22% |
| Median | 238.060 | 50.634 | 187.426 | 78.73% |
| P95 | 273.027 | 63.650 | 209.377 | 76.69% |
| P99 | 285.171 | 64.790 | 220.381 | 77.28% |
| Maximum | 287.314 | 65.969 | 221.345 | 77.04% |

The average includes nearly free URL-only verification samples. The DOM-heavy
median and tail savings reach the audit's predicted 150–220 ms range.

### Inspection

| Metric | Baseline ms | Optimized ms | Saving ms | Improvement |
|---|---:|---:|---:|---:|
| Average | 258.985 | 62.065 | 196.920 | 76.04% |
| Median | 231.803 | 53.705 | 178.098 | 76.83% |
| P95 | 288.622 | 84.555 | 204.067 | 70.70% |
| P99 | 911.838 | 173.705 | 738.133 | 80.95% |
| Maximum | 945.003 | 218.705 | 726.298 | 76.86% |

### Representative end-to-end activities

| Activity | Baseline average ms | Optimized average ms | Improvement |
|---|---:|---:|---:|
| Clicking | 706.48 | 516.72 | 26.9% |
| Typing/fill | 451.30 | 263.98 | 41.5% |
| Scrolling | 543.17 | 363.40 | 33.1% |
| Downloads | 1,100.92 | 1,098.92 | 0.2% |
| Local navigation | 231.59 | 241.20 | -4.1% |
| Local pointer movement | 75.82 | 78.87 | -4.0% |

Navigation, viewport pointer movement, and downloads do not use DOM expectation
snapshots in these samples, so their small changes are ordinary run-to-run
variance. Live Google Maps navigation had a 4.753-second network outlier and is
not used to claim an optimization gain.

Total benchmark wall time fell from 142.481 seconds to 106.610 seconds, a 25.2%
reduction, despite the Google Maps outlier.

## Behavioral and race validation

Focused tests cover:

- one evaluation with no serial property calls;
- missing and ambiguous legacy output;
- hidden and disabled targets;
- role, focus, value, bounding-box, and viewport fields;
- explicit unsupported fallback and telemetry;
- destroyed execution context without fallback;
- Chromium, Firefox, and WebKit parity;
- navigation replacement proving snapshots are not cached;
- unchanged public inspection keys.

The existing verification, page-precondition, and basic-interaction suites
passed with explicit navigation: 51 passed.

All benchmark actions succeeded:

- local actions: 140/140;
- Google Maps actions: 10/10;
- atomic snapshots: 205;
- fallbacks: 0.

## Test results

- Unit suite: **229 passed, 1 skipped**.
- Focused atomic integration suite: **4 passed**.
- Existing verification/page-precondition/basic-interaction integration:
  **51 passed**.
- Complete integration invocation: **209 passed, 41 failed, 1 xfailed**.

The 41 complete-suite failures do not execute the optimized snapshot path:

- most standalone tests expect implicit `ensure_on_url()` navigation, while the
  current runtime rejects an `about:blank` page precondition before dispatch;
  the current unit architecture test explicitly asserts `ensure_on_url()` is
  not called;
- several host-owned-backend tests pass an unstarted backend, while the current
  runtime contract returns `browser_session_not_active`;
- one popup-close test expects a specialized error but receives the existing
  Playwright `action_dispatch_failed` close error.

These failures reproduce in isolated modules and occur before
`capture_element_snapshot()`, or in unrelated page-transition/media paths.
Changing those contracts would be unrelated work and was intentionally not
included in this optimization.

## Process cleanup

After tests and the optimized benchmark, a read-only Windows process query found
zero Playwright-owned Chromium, Firefox, WebKit, or Node processes.

## Modified files

- `dingdongditch/backends/element_snapshot.py`
- `dingdongditch/backends/playwright_backend.py`
- `tests/unit/test_atomic_element_snapshot.py`
- `tests/integration/test_atomic_element_snapshot_e2e.py`
- `Engineering/runtime_latency_audit/benchmark_runtime.py`

Evidence artifacts and this report were added under
`Engineering/runtime_latency_audit/`.

## Remaining bottlenecks

The optimization exposes the next measured limits without changing them:

1. backend/browser action execution;
2. screenshot capture;
3. conservative download correlation windows;
4. browser startup and cleanup;
5. unchanged constrained-target resolution.

No unrelated wait, screenshot, download, action-ordering, serialization, or
cleanup optimization was implemented.

## Evidence locations

- Baseline raw benchmark: `benchmark_results_baseline.json`
- Optimized raw benchmark: `benchmark_results.json`
- Reproducible benchmark: `benchmark_runtime.py`
- Original audit: `RUNTIME_LATENCY_REPORT.md`
- Focused tests:
  `tests/unit/test_atomic_element_snapshot.py` and
  `tests/integration/test_atomic_element_snapshot_e2e.py`
