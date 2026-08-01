# Fresh Monkeytype Production Benchmark

Date: 2026-07-29  
Result: **PASS**  
Comparison outcome: **Measured regression**

## Result

| Metric | Fresh optimized-runtime run | Previous verified run | Change |
|---|---:|---:|---:|
| WPM | 93 | 104 | -11 WPM (-10.6%) |
| Accuracy | 100% | 100% | unchanged |
| Monkeytype correct characters | 465 | 521 verified key presses | -56 (-10.7%) |
| Incorrect characters | 0 | 0 | unchanged |
| Extra characters | 0 | — | — |
| Missed characters | 0 | — | — |
| Corrections/backspaces reported by Monkeytype | not reported | — | — |
| Backspaces dispatched | 0 | — | — |
| Verified DingDongDitch key operations | 468 | 521 | -53 (-10.2%) |

This run is a lower point estimate than the prior 104 WPM result and is
therefore classified as a measured regression. With only one permitted
successful run and one historical comparison sample, statistical significance
cannot be established.

Accuracy did not regress. The final Monkeytype screen independently reports
93 WPM, 100% accuracy, `465/0/0/0` characters, English, and a 60-second test.

## Execution stack and policy

The benchmark used:

```text
Codex
→ typed ExecutionPlans
→ current production DingDongDitch
→ fresh headed bundled Chromium
→ Monkeytype
```

No JavaScript was injected. No Playwright keyboard or mouse API was called by
the benchmark. Navigation, consent, focus, 60-second selection, every key
press, waits, milestones, and result capture occurred through typed
DingDongDitch plans. Read-only state came through `inspect_target()`.

The successful run used a new browser session and a new evidence directory.
The first attempt stopped before typing because Monkeytype's current 60-second
control did not match the initial typed locator. It was a genuine execution
error, cleaned up with zero remaining owned processes, and triggered the one
permitted retry. No performance result was retried.

## Timing

| Measurement | Duration |
|---|---:|
| Browser launch | 1,741.90 ms |
| Timed typing interval | 61,292.32 ms |
| Complete benchmark execution | 72,271.27 ms |
| Browser cleanup | 875.00 ms |

The typing interval is slightly longer than Monkeytype's 60 seconds because the
host detected the results screen through the next deterministic inspection.

## Runtime evidence explaining the result

The Atomic Snapshot optimization worked during this run:

- atomic snapshots: 186 reported by the benchmark result;
- serial snapshot fallbacks: 0;
- active-word/result-probe inspections during typing: 181;
- inspection time during typing: 10,338.34 ms total, 57.12 ms average.

The remaining throughput limit was per-key deterministic execution:

- typing plans: 90;
- verified key operations: 468;
- typing-plan time: 47,523.35 ms total;
- per-key receipt elapsed time: 101.56 ms average;
- per-key backend action time: 53.20 ms average;
- aggregate per-key action time: 24,899 ms;
- milestone evidence plans: 726.21 ms.

Thus, approximately 47.5 of the 61.3 measured typing seconds were spent inside
the 468 fully receipted key operations, and another 10.3 seconds were spent
reading the current active word and checking for completion. The optimized
atomic inspections materially reduced the observation tax, but they cannot
remove action dispatch, pre/post observations, URL verification, receipt
construction, and ordered plan boundaries for every key.

This evidence explains why the general runtime optimization did not guarantee a
higher Monkeytype score: the optimization targets DOM verification and
inspection, while this complete-stack workload remains dominated by hundreds
of sequential, deterministic key operations. No Monkeytype-specific fast path,
batch injection, direct keyboard call, or weakened receipt policy was used.

## Evidence inventory

| Evidence | Count/status |
|---|---:|
| Plan receipt files | 100 |
| Attempted operation receipts contained in plans | 478 |
| Verified operation receipts | 478 |
| Screenshots | 10 |
| Inspections | 187 |
| Typed words | 90 |
| Cleanup errors | 0 |
| Final lifecycle state | stopped |
| Remaining DingDongDitch/Playwright-owned processes | 0 |

Screenshots include navigation, consent, focus, 60-second selection, ready
state, three typing milestones, and final results.

## Verification

- Fresh headed bundled Chromium: PASS
- Monkeytype loaded and became ready: PASS
- Cookie consent handled through DingDongDitch: PASS
- Standard time 60 / English test: PASS
- Continuous typed-plan execution until completion: PASS
- Final results verified and inspected: PASS
- WPM/accuracy/characters parsed: PASS
- Receipts, inspections, screenshots, and logs written: PASS
- Browser cleanup without errors: PASS
- Remaining owned process count: 0

## Evidence locations

- `benchmark_results.json`
- `receipts/`
- `screenshots/`
- `inspections/`
- `logs/run_history.json`
- `terminal_browser.json`
- `run_benchmark.py`

The final result screenshot is:

`screenshots/wait_final_results__step-0__wait_final_results__after_success__e71b1801-51f6-48d1-a009-5cdae3cafabc.png`
