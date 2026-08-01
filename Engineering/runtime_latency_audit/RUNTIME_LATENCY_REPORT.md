# DingDongDitch Runtime Latency & Throughput Audit

Date: 2026-07-29  
Runtime version: 0.2.0  
Timer: `time.perf_counter_ns` (monotonic, nanosecond-resolution API)

## Executive conclusion

DingDongDitch's Python runtime is not the bottleneck. Validation, receipt
construction, JSON serialization, and receipt disk writes together account for
about 0.25% of measured wall time. The dominant costs are synchronous browser
round-trips:

1. backend action execution;
2. browser-backed inspection and verification;
3. screenshot encoding/capture;
4. deliberately conservative download correlation waits.

With an inspection after every operation, evidence generation is the largest
cost class. Without those caller-requested inspections, backend/browser action
latency is primary. There is no evidence that ordinary Python dispatch,
validation, receipt construction, serialization, or disk I/O warrants
optimization.

The safest high-impact improvement is to replace the many serial element-state
queries used by verification and inspection with one atomic browser evaluation
that returns the same fields. The next safest improvement is to reuse browser
sessions across plans. Fixed polling can become event-driven in several places,
but the download correlation window cannot be removed without weakening the
multiple-download guarantee.

## Methodology and scope

The audit harness wraps existing call boundaries; it does not modify arguments,
return values, action ordering, retry behavior, evidence, screenshot policy,
receipts, or cleanup. Each sample retained screenshots, receipt conversion,
JSON serialization, receipt writes, inspection, and cleanup.

Measured workloads:

- 20 samples each: navigation, clicking, typing/fill, pointer movement,
  scrolling, immediate condition wait, and download;
- 5 live Google Maps navigations and 5 live Google Maps pointer moves;
- 200 `ExecutionPlan.validate()` samples;
- 10 additional browser start/stop lifecycle samples;
- 140/140 local actions executed successfully;
- 10/10 complex-app actions executed successfully.

Local interactions used the deterministic bundled test site to remove network
variance. Google Maps supplied a complex, networked web-app workload. Chromium
was bundled and headless. Results describe this Windows host and should be
repeated on production hardware, filesystems, browser channels, and network
routes before setting SLOs.

Stage percentages below are inclusive percentages of the 142.481-second audit
wall time. Nested stages overlap (for example, target resolution is inside
backend execution), so percentages must not be added.

## Stage latency distribution

| Stage | N | Average ms | Median ms | P95 ms | P99 ms | Max ms | Wall % |
|---|---:|---:|---:|---:|---:|---:|---:|
| Total measured operation | 150 | 502.533 | 454.927 | 1,114.380 | 1,226.842 | 2,032.784 | 52.905% |
| Action dispatch | 250 | 194.877 | 87.197 | 954.845 | 972.909 | 1,268.339 | 34.194% |
| Backend execution | 250 | 183.598 | 73.904 | 943.674 | 961.770 | 1,257.564 | 32.215% |
| Inspection generation | 145 | 258.985 | 231.803 | 288.622 | 911.838 | 945.003 | 26.356% |
| Screenshot capture | 130 | 130.058 | 114.454 | 263.836 | 353.146 | 720.551 | 11.867% |
| Wait strategies | 349 | 46.311 | 46.811 | 49.301 | 54.299 | 78.788 | 11.344% |
| Browser startup | 12 | 1,316.403 | 1,318.502 | 1,348.892 | 1,355.804 | 1,357.532 | 11.087% |
| Verification | 85 | 173.092 | 238.060 | 273.027 | 285.171 | 287.314 | 10.326% |
| Evidence observation | 500 | 12.854 | 11.213 | 16.796 | 47.826 | 88.460 | 4.511% |
| Target resolution | 305 | 20.036 | 14.071 | 31.571 | 37.512 | 58.041 | 4.289% |
| Cleanup | 12 | 137.078 | 128.581 | 176.310 | 197.571 | 202.886 | 1.154% |
| Disk I/O (receipt writes) | 145 | 1.533 | 1.260 | 5.041 | 6.064 | 6.415 | 0.156% |
| JSON serialization | 145 | 0.654 | 0.642 | 1.052 | 1.462 | 1.825 | 0.067% |
| Operation validation | 450 | 0.052 | 0.057 | 0.119 | 0.146 | 0.294 | 0.016% |
| ExecutionPlan validation | 200 | 0.027 | 0.024 | 0.036 | 0.054 | 0.169 | 0.004% |
| Receipt generation | 250 | 0.015 | 0.013 | 0.026 | 0.038 | 0.088 | 0.003% |

`Action dispatch` contains `backend execution`, and `backend execution`
contains resolution and some waits. `Inspection generation` is a requested
post-operation activity, not hidden inside `execute_operation`.

## Activity latency and throughput

| Activity | N | Average ms | Median ms | P95 ms | P99 ms | Max ms | Approx. sequential ops/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pointer movement, local | 20 | 75.82 | 75.86 | 94.06 | 94.51 | 94.62 | 13.19 |
| Immediate condition wait | 20 | 183.93 | 184.19 | 191.88 | 192.66 | 192.86 | 5.44 |
| Navigation, local | 20 | 231.59 | 220.36 | 261.66 | 367.61 | 394.10 | 4.32 |
| Typing/fill | 20 | 451.30 | 449.12 | 478.07 | 489.10 | 491.85 | 2.22 |
| Scrolling | 20 | 543.17 | 542.30 | 575.28 | 576.20 | 576.43 | 1.84 |
| Google Maps pointer movement | 5 | 562.10 | 602.02 | 637.59 | 643.27 | 644.69 | 1.78 |
| Clicking | 20 | 706.48 | 707.23 | 731.82 | 733.21 | 733.55 | 1.42 |
| Download | 20 | 1,100.92 | 1,099.90 | 1,122.11 | 1,123.66 | 1,124.05 | 0.91 |
| Google Maps navigation | 5 | 1,341.10 | 1,224.01 | 1,872.14 | 2,000.65 | 2,032.78 | 0.75 |

These totals include in-operation screenshots when the operation verdict and
configured policy require one. The separate inspection, serialization, and
receipt write performed after each operation are not included in this table.

## Bottleneck ranking

1. **Browser-backed action execution — highest general impact.** It consumed
   32.215% of audit wall time inclusively. Downloads averaged 957.4 ms in
   dispatch and Google Maps navigation averaged 904.5 ms. This is primarily
   browser/network/safety-window time, not Python dispatch.

2. **Inspection generation — highest evidence-specific impact.** A local
   inspection averaged 232–263 ms; inspecting the Google Maps body averaged
   641 ms. `read_element_state()` makes serial calls for visibility, enabled
   state, text, ten attributes, input value, checked state, and viewport state.

3. **Screenshot capture.** Capture averaged 130.1 ms, with a 720.6 ms maximum.
   Google Maps captures averaged 381 ms for navigation and 263 ms after pointer
   movement. Encoding and browser-to-filesystem transfer dominate.

4. **DOM verification.** A verification call averaged 173.1 ms overall.
   Attribute/viewport verification averaged roughly 236–255 ms per measured
   operation because it uses the same broad serial state reader as inspection.

5. **Conservative download correlation waits.** The benchmark recorded 349
   timeout calls, almost all from downloads, averaging 46.3 ms each including
   protocol overhead. Per download, the fixed event/correlation policy accounts
   for roughly 0.8 seconds. That window proves that an operation did not emit
   additional download events; removing it would weaken determinism.

6. **Browser startup and cleanup.** Startup averages 1.316 seconds and cleanup
   137 ms. This is a major per-plan tax only when callers create an owned browser
   for each plan; retained host-owned sessions already avoid it.

7. **Target resolution and observations.** Resolution averages 20.0 ms and each
   pre/post observation averages 12.9 ms. These are material only for very short
   actions or plans with many steps.

8. **Serialization, disk writes, validation, and receipt construction.** These
   are already near their practical limits and collectively do not justify
   complexity. Receipt construction itself averages 15 microseconds.

## Blocking and wait analysis

Unnecessary or avoidably coarse blocking:

- Target discovery sleeps for 50 ms between complete re-resolution attempts.
  Locator attachment/visibility can be awaited through Playwright events, with
  one final deterministic cardinality resolution for the receipt.
- General `wait_for` conditions poll every 50 ms. Element visibility,
  attachment, text, attributes, URL, load state, and most media conditions have
  event-driven browser primitives or can use a page-side observer/promise.
- Expectation verification polls every 50 ms and then repeats full evidence
  observation. Event-driven waiting followed by one atomic final snapshot would
  preserve the evidence boundary while avoiding polling quantization.
- Navigation calls `goto(..., wait_until="domcontentloaded")` and immediately
  calls `wait_for_load_state("domcontentloaded")` again. The second call is
  normally already satisfied. Remove it only after cross-engine equivalence and
  redirect-race tests.
- The 150 ms observation settle after a failed `title()` read is a fixed delay.
  It occurs only on redirect races; awaiting the current navigation/load event
  is safer and faster than sleeping.

Blocking that is intentional:

- The post-download correlation window must remain bounded and open long enough
  to detect multiple events. An event-driven first-event wait reduces CPU and
  wakeups, but not the full quiet-window latency needed to prove uniqueness.
- Screenshot completion must precede a receipt that claims a captured artifact.
- Cleanup must finish before runtime-owned lifecycle state can be receipted.

## Safe parallelism

Safe candidates:

- Caller-level operations on different browser contexts/pages when the plan
  explicitly declares them independent. Each requires isolated collectors,
  download stores, page IDs, deadlines, and ordered receipt aggregation.
- JSON conversion and external receipt-file writing can overlap unrelated work
  after an immutable receipt has been returned. The measured gain is under
  2 ms per receipt, so this is low priority.
- Hashing and MIME/signature checks for an already closed, immutable download
  staging file can be parallelized internally, then joined before commit and
  receipt creation. Benchmark the filesizes first.

Unsafe candidates:

- Actions in the same ordered plan/page; they mutate shared DOM, network,
  pointer, dialog, and freshness state.
- Pre/post observation, verification, and screenshot capture when their temporal
  ordering is part of evidence freshness.
- Cleanup concurrent with any evidence or artifact operation.
- Parallel Playwright sync-API calls on one page/context.

Batching multiple DOM properties into one page evaluation is preferable to
thread-level parallelism: it reduces round-trips and returns an atomic snapshot.

## Recommended optimizations and estimated gains

Estimates are bounded by the measured stage time; they are not claims from an
optimized implementation.

| Recommendation | Measured basis | Estimated safe gain |
|---|---|---:|
| Atomic element-state snapshot for verification and inspection | DOM verification ~236–255 ms; local inspection ~232–263 ms | 150–220 ms per DOM verification/inspection (roughly 60–85% of those stages) |
| Retain/reuse browser sessions across compatible plans | Startup 1,316 ms + cleanup 137 ms | ~1.45 s per avoided browser lifecycle |
| Event-driven locator/condition/verification waits plus one final snapshot | 50 ms polling quantum | 0–50 ms typical latency per asynchronously satisfied wait; larger CPU/wakeup reduction |
| Preserve download quiet window but replace 25 ms polling with event/deadline signaling | ~0.8 s wait budget per download | Near-zero guaranteed latency gain; substantial wakeup/CPU reduction |
| Batch constrained target checks where semantics permit | Resolution average 20 ms | 5–15 ms per constrained resolution |
| Remove redundant post-`goto` DOMContentLoaded wait after parity tests | Navigation dispatch 92.6 ms local | 0–10 ms typical; larger only in race cases |
| Replace fixed 150 ms title retry sleep with navigation-aware await | Only redirect/title failures | Up to 150 ms on affected observations |
| Optimize JSON/receipt disk pipeline | 0.65 ms + 1.53 ms average | <2 ms; not production-priority |
| Micro-optimize validation/receipt objects | <0.08 ms combined | <0.1 ms; reject |

No production-safe recommendation removes screenshots, receipts, freshness
checks, download correlation, determinism, verification, or cleanup.

## Production-safe roadmap

### Phase 1 — high impact, moderate effort

Implement an atomic element-state snapshot used by both
`read_element_state()` and expectation verification. It must return exactly the
current receipt fields, preserve target cardinality traces, and use one
browser-side evaluation after deterministic resolution. Add cross-engine parity,
detached-node, iframe, ambiguity, and freshness tests. Re-run this benchmark and
require identical verdict/receipt semantics.

### Phase 2 — high impact, low integration effort

Make retained browser sessions the recommended production execution mode.
Expose lifecycle reuse metrics and pool only identical browser configurations.
Enforce strict context reset/ownership boundaries; never silently reuse a dirty
context across unrelated trust domains.

### Phase 3 — medium impact, moderate/high effort

Replace 50 ms target, condition, and verification polling with Playwright waits
or page-side observers. Always perform a final atomic snapshot at the existing
verification point so receipts and freshness remain deterministic. Keep the
same deadlines and failure kinds.

### Phase 4 — medium impact, moderate effort

Convert download event polling to a condition/event wait while retaining the
full configured correlation quiet window and late-event cancellation. Optimize
CPU/throughput first; change latency only if a new contract explicitly permits
a shorter correlation window.

### Phase 5 — low impact

Remove the redundant navigation load-state call after Chromium, Firefox, WebKit,
redirect, popup, and slow-navigation parity tests. Replace the title retry sleep
with a bounded navigation-aware wait. Consider batched target constraints.

### Explicit non-goals

Do not spend engineering effort micro-optimizing validation, dataclass receipt
construction, JSON encoding, or ordinary receipt writes. Do not make evidence
capture asynchronous if the receipt can return before the artifact is durable.
Do not parallelize ordered actions on the same page.

## Practical-limit assessment

The pure runtime is already near its practical limit: plan validation is 27
microseconds, operation validation 52 microseconds, receipt construction 15
microseconds, JSON encoding 0.65 ms, and receipt writes 1.53 ms. Optimizing these
cannot materially change user-visible latency.

The full system is not yet at its practical limit because verification and
inspection issue many serial browser calls. Those can be collapsed without
weakening evidence. After that change, screenshot cost, real page/network
latency, browser startup, and the download uniqueness window will form the hard
floor unless the product contract itself changes.

## Reproduction

Run from the repository root:

```powershell
python Engineering\runtime_latency_audit\benchmark_runtime.py `
  --repetitions 20 --complex-repetitions 5
```

The command writes `benchmark_results.json` beside this report. Temporary
screenshots, downloads, inspections, and receipt files are produced during the
run and cleaned only after all measurements complete.
