# Milestone 2 — Native Ordered Plans

**Status:** Complete  
**Date:** 2026-07-26  
**Depends on:** Milestone 1 + Browser-boundary hardening  

## Purpose

Move ordered coordination from host/demo loops into DingDongDitch.

DingDongDitch accepts one host-authored `ExecutionPlan`, runs its existing
Milestone 1 operations in declaration order inside **one** retained browser
session, verifies each attempted step independently, stops honestly on failure,
and returns one combined plan receipt.

This is **not** planning, recovery, autonomy, branching, or multi-browser support.

## Host-side chaining vs native plans

| Before (demos) | Milestone 2 |
|----------------|-------------|
| Host loops `execute_operation(..., backend=)` | Host submits `ExecutionPlan` |
| Host owns stop decisions ad hoc | Runtime applies `stop_on_failure` |
| Host aggregates outcomes manually | Runtime returns `PlanReceipt` |

## Public contract

```text
ExecutionPlan
  plan_id: str (required, non-empty, host-supplied)
  browser_config: BrowserConfig (default: playwright chromium bundled)
  operations: list[Operation]  # existing Milestone 1 operations, order preserved
  failure_policy: stop_on_failure  # only policy in M2
```

API: `execute_plan(plan) -> PlanReceipt`

## Validation (before browser launch)

Rejects: empty `plan_id`, zero operations, duplicate `operation_id`s, malformed
operations, unsupported browser config, invalid failure policy.

No partial execution of a statically invalid plan.

## One-session lifecycle

1. Validate plan + BrowserConfig  
2. Create one `PlaywrightBackend`  
3. `start()` once  
4. For each operation in order: `execute_operation(..., backend=session)`  
5. Apply stop policy  
6. Build `PlanReceipt`  
7. `stop()` once (when plan owns the session)  

Stable across all attempted steps: `browser_session_id`, `context_id`, `page_id`.

## Host examples

Infrastructure-neutral demos under `examples/` (local fixture) construct an
`ExecutionPlan` in host code and call `execute_plan` once. See
[`examples/host_execution_plan.py`](../../examples/host_execution_plan.py) and
[`MILESTONE_2_CHROMIUM_STABILIZATION.md`](./MILESTONE_2_CHROMIUM_STABILIZATION.md).
DingDongDitch does not ship site-specific planning demos.

## Operation reuse

Plans call the same `execute_operation` path as standalone calls. Target
resolution, expectations, freshness, verdicts, and browser metadata are not
forked.

## Failure policy

**Only `stop_on_failure`.**

| Step verdict | Plan continues? |
|--------------|-----------------|
| VERIFIED | yes |
| NOT_VERIFIED | **stop** |
| EXECUTION_FAILED | **stop** |
| INDETERMINATE | **stop** |

`continue_on_failure` is rejected for Milestone 2: continuing after unverified
or indeterminate steps would blur success semantics.

No retries, locator changes, reloads, or replanning.

## Verdict aggregation + completion status

Separated on purpose:

**`plan_verdict`** (truth): `VERIFIED` | `NOT_VERIFIED` | `EXECUTION_FAILED` | `INDETERMINATE`

**`completion_status`**: `completed` | `stopped` | `not_started`

| Situation | plan_verdict | completion_status |
|-----------|--------------|-------------------|
| Validation/setup failed | EXECUTION_FAILED | not_started |
| All steps attempted + VERIFIED | VERIFIED | completed |
| Stopped on NOT_VERIFIED | NOT_VERIFIED | stopped |
| Stopped on EXECUTION_FAILED | EXECUTION_FAILED | stopped |
| Stopped on INDETERMINATE | INDETERMINATE | stopped |

Decisive step index/operation_id recorded when stopped.

## Skipped steps

After a stopping verdict, later steps are recorded as:

- `attempted=false`
- `skipped=true`
- `skip_reason=prior_step_prevented_execution`
- no fabricated operation receipts
- no browser action dispatch

## Plan receipt schema `2.0.0`

Includes: plan_id, plan_verdict, completion_status, failure_policy, counts,
decisive step, failure_kind, timestamps, duration, browser metadata, session
IDs, ordered step records (embedding full Milestone 1 receipts when attempted),
limitations.

## Cleanup

Plan-owned sessions always stop in `finally` after success or failure.
Cleanup errors do not overwrite the decisive plan outcome.

Standalone `execute_operation` remains supported unchanged. New host-authored
actions (`press_key`, `select_option`, `set_checked`, `hover`,
`scroll_to_target`) use the same per-step path — see
[`BASIC_INTERACTION_EXPANSION.md`](./BASIC_INTERACTION_EXPANSION.md).

## Rejected features

Branches, loops, DAGs, retries, healing, AI planning, concurrency, variables,
templating, rollback, browser pooling, multi-browser plans, tab management.

## Limitations

- Bundled Chromium + Firefox + WebKit (native Safari unsupported)  
- Single active page (no multi-tab)  
- Linear order only  
- Host must still author every step  
- Live overlays/CAPTCHA remain environmental boundaries  

## Relationship to browser-boundary hardening

Plans inherit one `BrowserConfig` and one `PlaywrightBackend` session model.
Native Safari remains unsupported.

## Governance

- EP-01: step verification ≠ action dispatch  
- EP-13 / NG: host declares plan; runtime does not invent steps  
- Phase 2: plan-consuming execution, not autonomous planning  
