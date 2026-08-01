# Three-engine stabilization audit

## Scope and conclusion

This is a read-only repository audit. No production code was changed, no live
website was contacted, and no browser was launched.

The repository’s three engines are the explicit `BrowserEngine` values:

1. `chromium` — Playwright-bundled Chromium
2. `firefox` — Playwright-bundled Firefox
3. `webkit` — Playwright-bundled WebKit (not native Safari)

They are not three independent execution engines. They share one
`PlaywrightBackend`, one target resolver, one operation executor, one ordered
plan executor, one verifier, and one receipt model. Engine choice is a
`BrowserConfig` input translated in
`dingdongditch.backends.playwright_backend.launch_playwright_browser`.

Therefore “full three-engine stabilization” is not one monolithic task. The
shared contract/lifecycle risks are one workstream; engine-specific behavior
and compatibility tests are three smaller parallel workstreams after that
shared foundation is stable.

## Engine responsibility matrix

| Dimension | Chromium | Firefox | WebKit |
|---|---|---|---|
| Responsibility | Execute the shared plan through bundled Chromium | Execute the same plan through bundled Firefox | Execute the same plan through bundled WebKit |
| Public inputs | `ExecutionPlan.browser_config` with `engine=chromium`, bundled channel, actions, targets, expectations, deadlines | Same typed inputs with `engine=firefox` | Same typed inputs with `engine=webkit` |
| Public outputs | `PlanReceipt` containing operation receipts, verdicts, browser identity, telemetry, lifecycle/evidence | Same | Same |
| State ownership | Backend-owned Playwright/browser/context/pages; runtime owns plan sequencing | Same | Same |
| Browser/session ownership | `PlaywrightBackend`; runtime-owned plans start/stop it, injected backends remain caller-owned | Same | Same |
| Deadline ownership | `PlanTimingState` owns plan deadline; executor intersects operation/action/verification budgets | Same | Same |
| Verification ownership | Shared `runtime.verifier` evaluates declared expectations | Same | Same |
| Evidence ownership | Shared `EvidenceCollector`, backend observations, action evidence, receipts | Same | Same |
| Cleanup ownership | Backend closes runtime-owned context/browser/Playwright and preserves terminal identity | Same | Same |
| Failure classifications | Shared validation, browser setup, target, dispatch, verification, deadline, cleanup kinds | Same | Same |
| Dependencies | Shared contracts, resolver, verifier, plan executor, bundled Chromium binary | Shared contracts and bundled Firefox binary | Shared contracts and bundled WebKit binary |

There is no engine-specific public contract or alternate executor. Differences
are intentionally confined to Playwright launch behavior and browser-specific
runtime observables.

## Boundary analysis

### Host → typed contracts

The host declares `BrowserConfig`, `ExecutionPlan`, `Operation`, `Action`,
`Locator`, expectations, page transitions, dialogs, and screenshot policy. The
contracts validate fail-closed before browser launch. This boundary is the
strongest architectural seam: public contracts do not expose Playwright page
objects.

Observed coupling: `Operation` currently stores some newer policies as
`Any | None` (`page_transition`, `dialog_contract`, and screenshot
configuration), then imports and validates concrete types inside
`Operation.validate`. This preserves compatibility but weakens static contract
clarity and makes JSON/builder parity easier to drift.

### Typed plan → ordered runtime

`runtime.plan_executor.execute_plan` owns validation, one retained session,
stop-on-failure, step records, plan verdict aggregation, deadline state, and
runtime-owned cleanup. `runtime.executor.execute_operation` owns the per-step
precondition, observation, dispatch, verification, freshness, and operation
receipt.

Observed coupling: both layers construct and enrich receipts. Unexpected
exceptions in the plan executor create a step with `receipt=None`, while normal
operation failures embed a full receipt. This is honest but creates two evidence
shapes consumers must handle.

### Runtime → Playwright backend

The runtime supplies a typed operation and deadline state. The backend resolves
targets, dispatches Playwright calls, observes browser state, owns browser IDs,
page registry, popup/dialog listeners, screenshots, and cleanup telemetry.

Observed coupling: the backend is more than a thin adapter. It owns page
transition policy, dialog policy, screenshot capture, lifecycle, and evidence
assembly. This is still consistent with the stated backend boundary, but it is
the highest concentration of correctness risk.

### Backend → evidence/receipts

Backend observations become `EvidenceSignal`s; dispatch returns action evidence;
the runtime copies those structures into operation receipts; the plan executor
embeds them into plan steps and terminal lifecycle data.

Observed loss risk: any backend fact not copied into `ActionDispatchResult`,
`ExecutionReceipt`, or terminal identity disappears at the next boundary.
Popup/dialog/page-registry/screenshot evidence therefore requires explicit
schema tests at all three levels.

## Findings ranked by risk

| Rank | Finding | Correctness risk | Hang/misleading-receipt likelihood | Effort | Regression risk |
|---:|---|---|---|---|---|
| 1 | Shared backend owns dispatch, page registry, native dialogs, screenshots, cleanup, and telemetry; responsibility concentration makes cross-feature interactions hard to isolate | High | High | Large | High |
| 2 | Full-suite runs have previously exceeded the outer command limit without pytest completion; this prevents proving cross-engine regression stability | High | Medium | Medium | Medium |
| 3 | Engine parity is tested through many separate matrices, but shared lifecycle/receipt invariants are not one engine-parameterized contract suite for every new feature | Medium | High | Medium | Medium |
| 4 | Deadline state is owned by `PlanTimingState`, while backend transition/dialog/screenshot waits derive effective timeouts independently; boundary audits are needed for every new wait/capture path | High | High | Medium | High |
| 5 | Operation/plan policy fields use `Any` compatibility slots and runtime imports for validation; typed API drift can occur between Python, JSON, and builder paths | Medium | Medium | Small | Medium |
| 6 | Runtime-owned cleanup is backend-owned, but receipt construction occurs before final cleanup enrichment; terminal evidence is patched after return construction | Medium | Medium | Medium | Medium |
| 7 | Engine differences are mostly encoded as launch configuration, so browser-specific unsupported behavior can surface late as generic Playwright failures | Medium | Medium | Medium | Medium |
| 8 | Capability/limitations metadata and implementation milestones can lag newer features (popup/dialog/screenshot terminology appears in historical docs) | Low | Medium | Small | Low |

### Proven versus unproven

Proven by repository evidence: one shared Playwright backend is used for all
three engines; ownership and contracts are intended to be identical; engine
selection is explicit; injected versus runtime-owned backend cleanup is
distinguished; popup/page registry and dialog history are backend concerns.

Not proven without running a controlled matrix: identical popup/dialog timing
behavior across all three engines, identical screenshot/redaction behavior,
beforeunload semantics, and complete cleanup evidence under every deadline
failure. This audit does not infer defects from absence of a test result.

## Small-phase stabilization plan

### Phase 1 — Contract and ownership inventory (small)

Scope: make policy ownership explicit and remove undocumented `Any` fields where
safe; define one receipt-field ownership table.

Likely files: `contract/operation.py`, `contract/plan.py`,
`contract/page.py`, `contract/dialog.py`, `contract/screenshot.py`,
`plan_json.py`, `plan_builder.py`.

Tests: Python/JSON/builder round-trip tests for every policy; validation tests
for invalid combinations.

Success: one canonical typed representation per policy and no field whose
owner is ambiguous.

Rollback boundary: revert contract-only changes before backend behavior changes.

Difficulty: small.

### Phase 2 — Shared lifecycle/deadline harness (medium)

Scope: one parameterized harness asserting session identity, page identity,
deadline intersection, stop-on-failure, and terminal cleanup for all engines.

Likely files: `runtime/plan_executor.py`, `runtime/executor.py`,
`backends/playwright_backend.py`, `contract/receipt.py`, `contract/plan.py`.

Tests: same operation matrix over Chromium/Firefox/WebKit; setup failure,
deadline expiry, injected backend, unexpected exception, and cleanup failure.

Success: every attempted step has a deterministic evidence shape and every
engine preserves the same lifecycle invariants.

Rollback boundary: retain current executor and run the harness in parallel
until all invariants pass.

Difficulty: medium.

### Phase 3 — Evidence propagation audit (medium)

Scope: prove that page registry, popup/dialog, screenshot, target, network,
freshness, and cleanup facts survive operation → step → plan serialization.

Likely files: `contract/receipt.py`, `contract/plan.py`,
`runtime/executor.py`, `runtime/plan_executor.py`, `inspection.py`.

Tests: serialize/deserialize-style shape assertions after success, failure,
deadline, popup, dialog, and cleanup.

Success: no backend evidence is silently dropped at a receipt boundary.

Rollback boundary: schema/test-only changes first; preserve additive fields.

Difficulty: medium.

### Phase 4 — Engine-specific compatibility matrix (medium per engine)

Scope: isolate only behavior that differs in Chromium, Firefox, or WebKit:
navigation timing, popup event ordering, native dialog behavior, screenshot
capture, beforeunload, and cleanup.

Likely files: `tests/integration/test_*_compatibility.py`,
`tests/integration/test_page_transitions_e2e.py`,
`tests/integration/test_dialogs_e2e.py`, screenshot tests, and only then backend
feature guards if a deterministic difference is proven.

Tests: local fixtures parameterized by `BrowserEngine`; no live websites.

Success: every engine either passes the common contract or returns an explicit,
documented capability/failure classification.

Rollback boundary: engine-specific test/guard changes only; no shared semantic
weakening.

Difficulty: medium per engine.

### Phase 5 — Suite completion and hang isolation (small to medium)

Scope: isolate the existing full-suite timeout by file/test process, identify
resource leaks or long-running fixtures, then run the complete suite twice.

Likely files: pytest configuration, fixture server lifecycle, integration tests,
backend cleanup tests.

Tests: per-file timing, process isolation, repeated full-suite runs.

Success: two completed full-suite runs with stable counts and no orphaned
browser/server processes.

Rollback boundary: test-runner configuration only.

Difficulty: small to medium.

## Overall recommendation

Do not begin a broad three-engine refactor. Stabilize the shared contract and
receipt/lifecycle harness first, then run three bounded engine-specific matrices
and a separate suite-hang workstream. This decomposes the work into smaller
independent tasks while preserving the Host → typed plan → deterministic runtime
→ backend → evidence-backed receipt architecture.
