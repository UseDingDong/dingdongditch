# Per-file timing assessment

## Decision

**Final classification: `GLOBAL_TIMEOUT_TOO_SHORT`**

The incomplete 180-second full-suite runs are explained by an unrealistically
short global bound. Ten integration files with trustworthy completion evidence
already total **419.05 seconds**. Five other files each made substantial,
test-by-test progress until a 90-second per-file bound. There is no present
evidence of a genuine hang.

This does not mean the repository is release-ready. Meaningful engineering work
remains because the fresh deterministic-local-fixture runs exposed integration
failures. Those failures need triage and a clean complete run before
documentation, packaging, and release. They are separate from the explanation
for the old 180-second incomplete runs.

No production code was changed and no live website was used.

## Evidence and method

- Inventory source:
  `Engineering/test-results/final-stabilization/collection.txt`.
- Existing suite evidence:
  `Engineering/test-results/{baseline_full_suite.txt,full.log,final_full_suite_run2.txt,unit.log,webkit_isolation.log}`
  and `Engineering/test-results/final-stabilization/`.
- Fresh missing-file evidence:
  `Engineering/test-results/final-stabilization/per-file/<file>.{log,json}`.
- Every fresh file used a separate Python/pytest process, deterministic local
  fixtures, `-vv --tb=line --durations=0`, combined preserved stdout/stderr,
  before/after relevant-process snapshots, and a 90-second bound.
- The first sandboxed attempt was invalid because Playwright's Node driver
  received `EPERM` while resolving its installed path. Those artifacts were
  replaced by an approved local rerun. The table uses only the replacement
  evidence.
- The diagnostic command's outer 15-minute cap interrupted the final WebKit
  rerun. Its exact spawned tree was then terminated. WebKit classification and
  duration therefore use the earlier trustworthy completed focused run
  documented by the stabilization report: 8 passed in 62.45 seconds.

“Last started” means the last node printed by verbose pytest before a summary or
bounded termination. “Last completed” means the last node with a printed
outcome. Durations for completed files are pytest summary durations; timeout
rows show the measured bound (approximately 90 seconds).

## Per-file timing table

| Integration test file | Tests | Classification | Complete? | Duration | Exit | Timed out | Last started | Last completed | Summary | Relevant process remained | Evidence sufficient to classify? |
|---|---:|---|---|---:|---:|---|---|---|---|---|---|
| `test_adaptive_plan_timing_e2e.py` | 13 | FAIL | yes | 64.41s | 1 | no | `test_plan_deadline_expires_cleanly` | same (PASS) | yes: 4 failed, 9 passed | no new process | yes |
| `test_basic_interactions_e2e.py` | 29 | TIMEOUT | no | 91.81s outer / 90s bound | 124 | yes | `test_hover_reveals_tooltip[firefox]` | `test_hover_reveals_tooltip[chromium]` (PASS, 51%) | no | no new process after owned-tree termination | yes for TIMEOUT; no for final file duration |
| `test_chromium_plan_stability.py` | 11 | TIMEOUT | no | 91.45s outer / 90s bound | 124 | yes | `test_cleanup_idempotent_start_stop` | `test_receipt_invariants_on_success_and_stop` (PASS, 72%) | no | no new process after owned-tree termination | yes for TIMEOUT; no for final file duration |
| `test_constrained_targets_e2e.py` | 13 | FAIL | yes | 23.65s | 1 | no | `test_no_first_match_on_ambiguous` | same (PASS) | yes: 12 failed, 1 passed | no new process | yes |
| `test_dialogs_e2e.py` | 7 | PASS | yes | 26.32s | 0 | no | `test_wrong_message_and_multiple_dialogs` | same (PASS) | yes: 6 passed, 1 xfailed | no new process | yes |
| `test_firefox_compatibility.py` | 17 | TIMEOUT | no | 91.30s outer / 90s bound | 124 | yes | `test_firefox_stop_on_failure_variants` | `test_firefox_headed_and_headless_plans[firefox]` (PASS, 58%) | no | no new process after owned-tree termination | yes for TIMEOUT; no for final file duration |
| `test_iframe_targeting_e2e.py` | 30 | TIMEOUT | no | 91.31s outer / 90s bound | 124 | yes | `test_cross_origin_iframe_click[firefox]` | `test_cross_origin_iframe_click[chromium]` (PASS, 83%) | no | no new process after owned-tree termination | yes for TIMEOUT; no for final file duration |
| `test_multi_select_e2e.py` | 10 | PASS | yes | 30.40s | 0 | no | `test_multi_select_sets_all_requested_values_not_last_only` | same (PASS) | yes: 10 passed | no new process | yes |
| `test_ordered_plans_e2e.py` | 20 | FAIL | yes | 50.28s | 1 | no | `test_unexpected_step_exception_preserves_prior_and_skips` | same (PASS) | yes: 2 failed, 18 passed | no new process | yes |
| `test_page_transitions_e2e.py` | 10 | FAIL | yes | 23.85s | 1 | no | `test_deadline_expires_while_waiting_and_cleanup_retains_pages` | same (PASS) | yes: 1 failed, 9 passed | no new process | yes |
| `test_run_plan_cli.py` | 16 | FAIL | yes | 50.13s | 1 | no | `test_sample_plan_loads_without_browser` | same (PASS) | yes: 1 failed, 15 passed | no new process | yes |
| `test_single_operation_e2e.py` | 14 | SLOW_BUT_COMPLETE | yes | 46.66s | 0 | no | `test_role_name_locator_click` | same (PASS) | yes: 14 passed | no new process | yes |
| `test_video_ended_e2e.py` | 12 | FAIL | yes | 40.90s | 1 | no | `test_video_ended_missing_target_fails_validation` | same (PASS) | yes: 5 failed, 7 passed | no new process | yes |
| `test_wait_for_e2e.py` | 20 | TIMEOUT | no | 91.28s outer / 90s bound | 124 | yes | `test_wait_plan_success_and_timeout_stops[firefox]` | `test_wait_plan_success_and_timeout_stops[chromium]` (PASS, 80%) | no | no new process after owned-tree termination | yes for TIMEOUT; no for final file duration |
| `test_webkit_compatibility.py` | 8 | SLOW_BUT_COMPLETE | yes (existing focused run) | 62.45s | 0 | no | `test_webkit_launch_failure_never_falls_back` | same (PASS) | yes: 8 passed | no newly attributable process in stabilization snapshots | yes |

`FAIL` takes precedence over `SLOW_BUT_COMPLETE` where a file both ran slowly and
failed. No file is classified `PROBABLE_HANG`, `PROCESS_LEAK`, or
`INSUFFICIENT_EVIDENCE` merely because its run lacks a summary.

## Duration calculation

Collected inventory:

- Integration: **230 tests in 15 files**
- Unit: **121 tests**
- Complete suite: **351 tests**

Trustworthy completed integration durations:

```text
64.41 + 23.65 + 26.32 + 30.40 + 50.28
+ 23.85 + 50.13 + 46.66 + 40.90 + 62.45
= 419.05 seconds
```

This is a measured lower bound for the integration suite because it excludes
five files that timed out after about 90 seconds each.

For planning only, linear extrapolation from completed-test percentages gives:

| Incomplete file | Progress at 90s | Rough complete-file estimate |
|---|---:|---:|
| basic interactions | 15/29 completed; test 16 started | ~174s |
| Chromium stability | 8/11 completed; test 9 started | ~124s |
| Firefox compatibility | 10/17 completed; test 11 started | ~153s |
| iframe targeting | 25/30 completed; test 26 started | ~108s |
| wait-for | 16/20 completed; test 17 started | ~113s |

Thus:

```text
measured completed integration files             419s
estimated five incomplete integration files      672s
estimated full integration suite               1,091s  (~18.2 min)
measured unit suite                                13.89s
estimated complete 351-test suite              1,105s  (~18.4 min)
```

The extrapolation is deliberately approximate: test costs are not uniform,
failures can shorten execution, and a single combined process can be faster
than 15 fresh processes. It is nevertheless sufficient to prove that 180
seconds is not a credible global bound.

### Justified finite outer timeout

Use **1,500 seconds (25 minutes)** for the complete 351-test suite.

That is about 36% above the 1,105-second estimate, leaving roughly 6.6 minutes
for per-file cost nonuniformity, browser startup/cleanup variance, fixture
startup, and terminal/reporting overhead. Keep lower-level operation bounds and
owned-process-tree cleanup intact. This is a runner/configuration correction;
the timing evidence does not justify production runtime changes.

## Slowest files and tests

### Files

The strongest slow-file evidence is:

1. `test_basic_interactions_e2e.py`: exceeded 90s at 51%; estimated ~174s.
2. `test_firefox_compatibility.py`: exceeded 90s at 58%; estimated ~153s.
3. `test_chromium_plan_stability.py`: exceeded 90s at 72%; estimated ~124s.
4. `test_wait_for_e2e.py`: exceeded 90s at 80%; estimated ~113s.
5. `test_iframe_targeting_e2e.py`: exceeded 90s at 83%; estimated ~108s.
6. `test_adaptive_plan_timing_e2e.py`: completed in 64.41s.
7. `test_webkit_compatibility.py`: completed in 62.45s.

Disproportionate to test count:

- WebKit compatibility: 62.45s for only 8 tests.
- Chromium stability: more than 90s for 11 tests.
- Adaptive timing: 64.41s for 13 tests.
- Single operation: 46.66s for 14 tests.

### Slowest visible individual tests

From complete fresh `--durations=0` artifacts:

| Test | Phase duration |
|---|---:|
| `test_fixed_plan_budget_without_adaptation` | 16.79s |
| `test_action_ok_expectation_fails_not_verified` | 12.62s |
| `test_middle_not_verified_stops` | 12.50s |
| `test_video_ended_timeout_when_interrupted[webkit]` | 10.66s |
| `test_video_ended_timeout_when_interrupted[firefox]` | 8.94s |
| `test_finite_video_extends_wait_and_plan[firefox]` | 8.29s |
| `test_repeated_cli_executions_no_leak` | 7.60s |
| `test_video_ended_verified_after_playback[firefox]` | 7.35s |
| `test_sample_basic_navigation_json_executes_chromium` | 7.24s |

The existing focused repeat artifacts also show
`test_webkit_stop_on_failure_and_skip` completing five consecutive times in
24.11–24.39s. The prior focused report identifies WebKit's
`test_webkit_ten_sequential_owned_plans` and failure-path test as approximately
24-second tests.

## Hang evidence

### Proven facts

- Both old full runs stopped at the same **180-second outer limit**, not at a
  pytest-generated hang diagnosis.
- The two old full logs did not stop at the same exact test:
  one reached `test_chromium_plan_stability.py::test_ten_sequential_owned_plans_no_leaked_ids`;
  another ended after completing the basic-interactions file.
- The fresh 90-second timeouts also occurred at five different tests in five
  different files.
- Every timed file printed continuing progress before its bound.
- The formerly suspect WebKit failure-path test completed five consecutive
  focused runs and the whole WebKit file has a completed 8-pass run.
- No fresh bounded file left a newly observed Python, Node, browser, or fixture
  process after owned-tree cleanup.

No test has evidence that it starts and can never complete. Some timeout rows
have a final started-but-not-completed test, but each is a single bounded
observation and must not be labeled a hang.

### Likely inference

The suite is dominated by real browser startup, multi-engine parameterization,
deliberate timeout/failure-path behavior, and sequential-plan tests. Aggregate
runtime, rather than blocked cleanup, best explains the incomplete full runs.

### Insufficient evidence

- The exact natural completion duration of the five 90-second timeout files.
- Whether any one of their last-started tests is consistently pathological;
  there is no repeated timeout at the same exact node.
- A precise complete-suite duration under an all-passing state.
- A zero-orphan assertion after a naturally completed 351-test run.

## Process-cleanup evidence

- Each fresh JSON record contains before/after snapshots and
  `new_relevant_processes_remaining: []`.
- On each 90-second timeout, the helper used `taskkill /T /F` on only the
  pytest process it spawned; the log preserves the terminated tree.
- The outer diagnostic interruption during the final WebKit verification did
  temporarily leave that exact diagnostic tree. It was identified by its
  parent/child chain and explicitly terminated. A subsequent snapshot showed
  no Python, Playwright, Firefox, or WebKit process from it.
- A pre-existing ordinary Node process and Codex's `node_repl` remained. Their
  timestamps predate the relevant run and they are not attributable to
  DingDongDitch.
- The stabilization before/after snapshots likewise contained the same
  pre-existing Node PID and no newly attributable runner child.

There is therefore no `PROCESS_LEAK` classification and no evidence that browser
or fixture cleanup blocked the old full-suite completion. Cleanup after a
naturally completed, all-passing 351-test run remains to be demonstrated.

## Release-readiness recommendation

Replace the full-suite outer timeout with **1,500 seconds**, without production
runtime changes. Then triage the fresh integration failures, especially the
adaptive-media expectations and failures seen across constrained targeting,
ordered plans, transitions, CLI, and video-ended behavior. Some may reflect
environmental/timing sensitivity, but the present artifacts record genuine
pytest failures and they cannot be waived.

After those failures are resolved or proven environmental, run the complete
351-test suite in a fresh process with verbose output, durations, and
before/after process snapshots. Documentation, packaging, and release should
wait for that clean summary and cleanup evidence.
