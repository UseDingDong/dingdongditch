# Windows desktop vertical-slice architecture

Date: 2026-07-28

## Audit result

The current runtime is browser-specific rather than a domain-neutral backend
interface:

- `contract.operation.Operation` requires a URL and browser locators.
- `contract.plan.ExecutionPlan` always carries `BrowserConfig`.
- `runtime.executor` and `runtime.plan_executor` are directly typed to and
  instantiate `PlaywrightBackend`.
- Verification assumes page URLs, DOM observations, page preconditions, and
  browser freshness signals.
- `PlanReceipt` and its invariants require browser session/context/page IDs.
- Screenshot collection calls Playwright page screenshot APIs.
- Backend capabilities describe browser provider/engine/channel only.

Making these contracts generically polymorphic in this slice would be a major,
risky redesign and could weaken existing browser behavior.

## Decision

Implement a narrowly separated `desktop` execution domain that shares stable
execution semantics (ordered typed plans, stop-on-failure, verdict vocabulary,
bounded timing, lifecycle, screenshot policy, structured receipts) but does not
pretend browser URLs, DOM expectations, or page identities apply to Windows.

Production modules:

- `contract.desktop`: fail-closed typed desktop actions, application identities,
  UI Automation targets, expectations, operations, and plans.
- `backends.windows_desktop_backend`: Windows-only UIA implementation, bounded
  discovery, window uniqueness, foreground verification, ownership ledger,
  safe close, screenshots, and cleanup.
- `runtime.desktop_executor`: ordered plan runner and desktop verifier producing
  serializable per-action and plan receipts.

The benchmark may construct and submit only `DesktopExecutionPlan` values to the
desktop executor. Native/UIA/process APIs remain private to the production
backend.

## Safety boundaries

- Applications are selected from an explicit allowlist (`explorer`, `notepad`);
  no executable paths, free-form arguments, shell strings, or elevation.
- Paths must exist and are accepted only by the typed Explorer action.
- UI activation uses UIA controls and exact/declared matching, never coordinates
  as the primary mechanism.
- Every wait has a validated finite timeout and exact-one enforcement where
  requested.
- The session owns only process IDs it launched and window handles it discovered
  as the direct result of a typed launch/activation. Pre-existing processes and
  windows are snapshotted and never adopted implicitly.
- Close targets must be in the session ownership ledger. Cleanup preserves all
  errors and never terminates unrelated processes.
- Windows platform gating fails clearly before native imports elsewhere.

## Browser compatibility

No existing browser contract, JSON schema, backend selection, executor, or test
is changed. Desktop support is selected explicitly by importing/calling the
desktop domain executor. A future multi-domain dispatcher can wrap both only
after common receipt fields are deliberately extracted from browser-specific
ones.

