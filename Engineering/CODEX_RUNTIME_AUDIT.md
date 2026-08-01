# Codex Runtime Architecture Correction Report

## 1. Executive summary

This change set begins the production correction of DingDongDitch's execution
boundary. It implements and tests the highest-risk invariants: supplied backend
configuration identity, explicit navigation, lifecycle state and liveness,
typed shared timing limits, structured plan-validation errors, operation-scoped
and bounded evidence, runtime telemetry foundations, a compact plan builder,
read-only inspection, and generic HTML5 `video_playing` /
`video_completed_once` wait contracts.

The entire requested fourteen-phase refactor was not completed safely in this
work session. In particular, wait/expectation evaluation is not yet fully
consolidated, standalone cleanup cannot yet be attached to a receipt created
before its `finally` block, full phase-budget enforcement is incomplete, and
the complete integration suite did not finish within the 10-minute command
limit. This report therefore does not claim production completion.

No live website was contacted. Only the deterministic local fixture and
Playwright browser-binary download endpoints were used.

## 2. Intended architecture

Developer-controlled hosts author typed `ExecutionPlan` values. DingDongDitch
validates and deterministically executes those values through a browser backend,
observes declared browser-visible facts, verifies declared expectations, and
returns evidence-backed receipts. It does not plan, heal selectors, invent
navigation, choose recovery, or implement website-specific workflows.

## 3. Revalidated audit findings

The prior 28 findings were rechecked. The highest correctness risks remained:

1. supplied backends were not bound to `plan.browser_config`;
2. non-navigation operations silently called `page.goto`;
3. plan deadlines did not bound verification and several other phases.

Also confirmed were repeated lifecycle decisions, cached-reference liveness,
hidden cleanup errors, prose-based plan failure classification, process-global
evidence IDs, cumulative network snapshots, repeated polling evidence, reverse
contract-to-runtime timing dependency, duplicated limitation registries, and
milestone language in production modules.

## 4. Findings corrected

- A supplied backend whose complete frozen `BrowserConfig` differs from the
  plan is rejected before `start`, `stop`, or operation dispatch.
- Shared operations require an already-active host-owned backend; they no
  longer call `start()` on every operation.
- Backend liveness checks page closure and browser connection.
- Lifecycle state now distinguishes not-started, starting, active, stopping,
  stopped, failed, and crashed.
- Cleanup errors are retained, terminal session identity is retained, and plan
  receipts receive runtime-owned cleanup telemetry after shutdown.
- Non-navigation operations treat `Operation.url` as a same-document
  precondition and fail with `page_precondition_mismatch`; they never call
  `ensure_on_url`.
- Fragments are deliberately ignored for document identity; scheme, host, path,
  and query remain significant.
- Operation receipts gained page-precondition, navigation, dispatch-document,
  telemetry, and cleanup-compatible fields.
- Unexpected exceptions within the operation execution body are converted into
  `internal_runtime_error` receipts.
- Verification deadlines are capped by the current plan deadline.
- Browser action timeouts and locator retry deadlines are capped by the current
  plan deadline.
- Synthetic pre-dispatch plan deadline steps were removed; expiry flows through
  an operation receipt.
- Plan failure classification no longer parses prose for plan ID, empty plan,
  duplicate IDs, or failure-policy errors.
- Plan timing limits moved to a neutral contract module.
- Evidence IDs are collector-scoped instead of process-global.
- Network evidence snapshots are operation-windowed and the session buffer is
  capped at 2,000 records.
- Evidence collectors retain at most 512 signals and record discarded count.
- One authoritative limitations registry now feeds plan and operation receipts.
- Production milestone framing was removed from the touched runtime contracts.
- A `PlanBuilder` and read-only `inspect_target` API were added.
- `video_playing` and `video_completed_once` contracts were added with
  same-element/source progression checks.

## 5. Findings not changed or not yet fully corrected

- Generic wait and expectation evaluation remains split between the backend and
  verifier. Moving it safely requires broader parity tests.
- `PlaywrightBackend` remains too large. Mechanics were not moved merely to
  satisfy a class-size goal without a proven replacement boundary.
- Standalone runtime-owned cleanup occurs after receipt construction and is not
  yet reflected in that already-returning receipt object.
- Startup itself cannot be preempted synchronously at the precise plan deadline;
  elapsed time can be checked only after blocking Playwright startup calls.
- Pre/post observation and receipt construction do not yet have complete phase
  budget checks.
- Polling evidence is bounded globally but is not yet summarized as
  first/latest/decisive snapshots.
- Full typed conversion of all receipt strings was not completed.
- JSON/CLI validation remains repeated. Removing it safely requires deciding
  whether direct contract construction and external JSON share identical error
  semantics.
- The backend launch error classifier still inspects Playwright prose to
  distinguish missing binaries. This is at an external exception-normalization
  boundary, not plan-validation state, but remains fragile.

## 6. Architectural decisions

- `BrowserConfig` equality is the execution-environment identity because it is
  frozen and currently contains all material settings.
- Host-owned backends must be explicitly started by their owner.
- Runtime-owned backends are created, started, and stopped by the public
  execution API.
- `Operation.url` is a precondition for non-navigation operations, never
  navigation permission.
- Same-document identity ignores only the fragment.
- Evidence identity belongs to a receipt/operation collector.
- Evidence windows begin at operation start.
- Plan builders create ordinary typed plans and perform no inference.
- Inspection requires an active session and exposes observation only.

## 7. Files added, changed, moved, or removed

Added:

- `dingdongditch/contract/runtime.py`
- `dingdongditch/contract/capabilities.py`
- `dingdongditch/plan_builder.py`
- `dingdongditch/inspection.py`
- `tests/unit/test_runtime_architecture_corrections.py`
- `Engineering/CODEX_RUNTIME_AUDIT.md`

Changed:

- `README.md`
- `dingdongditch/__init__.py`
- `dingdongditch/backends/playwright_backend.py`
- `dingdongditch/contract/browser.py`
- `dingdongditch/contract/operation.py`
- `dingdongditch/contract/plan.py`
- `dingdongditch/contract/receipt.py`
- `dingdongditch/contract/verdict.py`
- `dingdongditch/contract/wait.py`
- `dingdongditch/evidence/collector.py`
- `dingdongditch/runtime/executor.py`
- `dingdongditch/runtime/freshness.py`
- `dingdongditch/runtime/plan_executor.py`
- `dingdongditch/runtime/plan_timing.py`
- `examples/single_operation.py`
- `tests/integration/test_single_operation_e2e.py`

No files were moved or removed.

## 8. Public contract changes

- Non-navigation standalone operations on a fresh backend now fail
  `page_precondition_mismatch` instead of implicitly loading their URL.
- Host-supplied backends must already be active and exactly match the plan.
- `ExecutionReceipt.to_dict()` includes `page_precondition`,
  `navigation_occurred`, `dispatch_document_url`, `telemetry`, and `cleanup`.
- `PlanReceipt.to_dict()` includes `lifecycle` and `telemetry`.
- Wait condition enum adds `video_playing` and `video_completed_once`.
- `PlanBuilder` and `inspect_target` are exported from the top-level package.

The receipt schema-version constants were not incremented in this partial
change. Before release, schema migration policy must be decided and versions
updated because additive fields and navigation behavior are public changes.

## 9. Host migration guidance

Previous invalid pattern:

```python
execute_operation(click_operation_for_url)
```

New pattern:

```python
plan = ExecutionPlan(
    plan_id="explicit",
    operations=[navigate_operation, click_operation],
)
execute_plan(plan)
```

Alternatively, a host may explicitly start a matching backend, navigate through
a declared operation, then execute later operations through that same backend.
Hosts must stop their own backend in `finally`.

Hosts reusing inspection sessions must construct plans with the exact same
provider, engine, channel, and headless setting.

## 10. Lifecycle model

`not_started -> starting -> active -> stopping -> stopped`

Launch or cleanup failure enters `failed`. An object whose cached references
exist but whose page is closed or browser disconnected enters `crashed`.

Runtime-owned plan backends are stopped in the plan executor's `finally`.
Host-owned backends are never stopped by plan execution. Configuration mismatch
does not start, stop, or mutate a host-owned backend.

Terminal session IDs and browser version survive in
`terminal_session_identity` after active fields are cleared.

## 11. Navigation model

Only `ActionType.NAVIGATE` calls `page.goto`. Non-navigation `url` values are
checked against the current document before observation or dispatch. Fragment
changes are same-document; query changes are different-document.

Redirects caused by explicit navigation are visible through post-action URL
evidence. Navigation caused by a declared click remains action-produced
navigation. A later operation must declare the resulting document identity.

## 12. Deadline model

The deadline uses monotonic milliseconds and exact equality means expired.
Declared wait polling already intersects its deadline with the plan deadline.
This change also intersects verification polling, locator retry, and ordinary
Playwright action timeouts.

Incomplete: backend startup, every observation boundary, receipt construction,
and cleanup are not yet fully represented by a shared `PhaseBudget`.
`plan_timing` still exposes original/resulting deadlines and adaptive decisions,
but failure-phase and remaining-budget fields are not complete.

## 13. Verification pipeline

The existing pipeline remains:

1. general pre-observation;
2. browser dispatch or declared wait;
3. general post-observation;
4. verifier-driven expectation polling;
5. freshness aggregation;
6. verdict.

Verification is now deadline-capped. Full condition-vocabulary consolidation is
deferred because the backend wait engine also owns media-specific sampling and
load-state mechanics.

## 14. Evidence-window model

Each operation creates an `EvidenceCollector` scoped by operation ID and start
time. General network observations include only records at or after that start.
The session network buffer retains at most 2,000 records. A collector retains at
most 512 signals.

Known gap: operation IDs can repeat across distinct plans/processes. Collector
instances do not collide internally, but explicit plan ID plus random run ID
should be incorporated before release. Poll summaries also need decisive-sample
retention rather than a simple upper bound.

## 15. Telemetry schema

Backend telemetry currently records:

- `backend_start_started_at`
- `playwright_started_at`
- `browser_launched_at`
- `context_created_at`
- `page_created_at`
- `backend_start_finished_at`
- `cleanup_started_at`
- `context_closed_at`
- `browser_closed_at`
- `playwright_stopped_at`
- `cleanup_finished_at`

Each event has monotonic `at_ms`. Operation receipt phase events and host
correlation metadata from the requested schema are not yet fully implemented.

## 16. Plan-builder API

`PlanBuilder` supports explicit `navigate`, `click`, `fill`, `select`, and
`wait`, then returns a normal validated `ExecutionPlan`. The host supplies every
ID, URL, locator, value, condition, expectation, and timeout. There is no
planning, healing, site knowledge, or browser dispatch in the builder.

## 17. Read-only inspection API

`inspect_target(backend, locator, frame=None)` requires an active backend and
returns current page/browser identity, match count, ambiguity, visibility,
enabled state, text, and target-resolution trace. It performs no navigation or
action and does not choose or rewrite a locator.

## 18. Media completion semantics

`video_ended` remains unchanged.

`video_playing` requires the same element and source across observations,
advancing `currentTime`, `paused=false`, `ended=false`, and `readyState>=2`.

`video_completed_once` accepts `ended=true` for non-looping media. Looping media
requires active trusted progression, a near-end observation, and a wrap to at
most one second on the same element and source. Element/source replacement
invalidates the sample chain.

Known gaps requiring more deterministic tests: seeking-event detection is
inferred only from progression shape; page reload identity is indirectly
rejected through element token loss but lacks a dedicated navigation epoch.

## 19. Test additions

New tests cover:

- backend configuration mismatch without start/stop;
- non-navigation mismatch without dispatch or navigation;
- fragment same-document identity;
- collector-scoped/bounded evidence;
- plan builder output;
- new media contract validation.

The single-operation integration module was migrated to explicit navigation
plans. Its forced-staleness monkeypatch was narrowed so navigation URL evidence
remains fresh while the intended DOM evidence is forced stale.

## 20. Focused test results by phase

- Initial contract/timing/browser subset: 42 passed, 4 failed because Playwright
  binaries were initially absent.
- Playwright Chromium, Firefox, and WebKit test binaries were installed.
- Architecture correction subset: 48 passed.
- Unit suite after lifecycle fix: 119 passed.
- A combined unit plus migrated single-operation run reached 132 passed and one
  test failure; that test was then corrected as described above.
- Final focused rerun of the six architecture tests plus the two previously
  affected single-operation tests: 8 passed.
- `compileall` completed successfully during the combined command.
- A two-test lifecycle/ordered-plan smoke run passed 2/2.

## 21. Final full-suite result from run one

Not completed. `python -m pytest tests -q` timed out at approximately 122
seconds without a final result before browser binaries were installed.

After installation, `python -m pytest tests/integration -q` timed out at
approximately 604 seconds without a final result. Because pytest output was
buffered, no reliable pass/fail total was emitted.

## 22. Final full-suite result from run two

Not run. A first complete suite did not finish, and claiming a second successful
run would be false.

## 23. Static analysis, formatting, and type-check results

`python -m compileall -q dingdongditch examples tests` succeeded.

The repository declares no formatter, linter, or type checker in
`pyproject.toml`; none was invented or downloaded. No formal static type check
was available.

## 24. Remaining known limitations

- Full lifecycle deadline enforcement is incomplete.
- Wait and expectation engines remain duplicated.
- Standalone cleanup result is not attached to its receipt.
- Evidence polling is bounded but not decisively summarized.
- Operation phase telemetry is incomplete.
- Many older integration modules still rely on standalone implicit navigation
  and require migration to explicit navigation/shared sessions.
- Full three-engine regression status is unknown because the integration suite
  did not finish.
- `PlaywrightBackend` still contains generic wait/adaptive policy.
- Receipt schema versions need a deliberate migration decision.
- Typed state adoption is partial.
- JSON/CLI validation ownership is not yet simplified.

## 25. Regression risks

High:

- hosts and tests relying on implicit standalone navigation;
- timing behavior near plan deadlines;
- media completion edge cases;
- cleanup receipt compatibility.

Medium:

- new browser liveness checks interacting with browser disconnect races;
- bounded evidence dropping early diagnostic samples;
- additive receipt fields affecting strict consumers;
- host sessions whose plan configuration previously differed silently.

## 26. Recommended next deterministic test

Create a local-fixture integration module that starts one backend per engine and
proves, in this order:

1. explicit navigation;
2. non-navigation state preservation;
3. mismatch rejection without `goto`;
4. fragment transition acceptance;
5. action-produced navigation followed by a matching next-step precondition;
6. deadline expiry during verification;
7. cleanup lifecycle contents.

Run this small matrix before migrating the remaining legacy standalone tests.

## 27. Confirmation that no live websites were contacted

Confirmed for runtime and test execution. All browser tests targeted the local
fixture server. Browser binaries were downloaded from Playwright's official
artifact host after approval. Amazon, YouTube, and other live sites were not
opened.

## 28. Confirmation that no temporary scripts remain

No temporary scripts were created by this implementation. Pre-existing
`__pycache__` files and live-test artifacts were not created or modified as
implementation helpers.

## 29. Final diff summary

The change set adds four production modules, one architecture test module, this
report, and modifies the runtime/backend/contracts/docs/examples/tests listed in
section 7. The environment does not expose a usable Git repository (`git`
reported that the directory was not a repository), so a canonical `git diff
--stat` could not be produced.

## Blockers and rollback guidance

This is a partial architecture correction and should not be released as a
complete implementation of all requested phases.

If the repository must return immediately to its prior behavior, revert the
files listed in section 7 using the authoritative upstream source-control copy;
do not selectively restore `ensure_on_url` while retaining new receipt claims.
The navigation contract, tests, README, and executor must move together.

For continuation, preserve the completed configuration-binding and explicit
navigation invariants, migrate remaining tests, then implement a shared
`PhaseBudget` and condition evaluator before narrowing the backend further.
