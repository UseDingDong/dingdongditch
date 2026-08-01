# Milestone 2 — Chromium Stabilization Pass

**Status:** Complete  
**Date:** 2026-07-26  
**Depends on:** Milestone 2 native ordered plans  
**Not:** Milestone 3 / Firefox / WebKit / channel browsers  

## Purpose

Stabilize Milestone 2 on **bundled Chromium** through repeated-plan,
lifecycle, receipt-invariant, cleanup, and ownership tests before any
multi-browser work.

Stabilization does **not** prove universal website compatibility. DingDongDitch
remains execution infrastructure: the host authors plans; the runtime does not
plan, heal, or explore sites.

## Why before Firefox

Firefox compatibility must sit on a known-good Chromium plan lifecycle. Fixing
ownership, cleanup, and receipt contradictions after introducing a second
engine would confound root-cause analysis.

## Deterministic Chromium matrix (CI)

- Ten sequential owned successful plans; distinct session/context/page IDs  
- Success after stopped / stopped after success  
- Injected backend reuse: IDs stable; `execute_plan` does not close caller backend  
- Headed/headless parity on fixture plans  
- Page ID stable across navigate→fill→click  
- URL/fill persistence  
- Constraint resolution identical standalone vs plan  
- Receipt `check_invariants()` on success and stop  
- Validation never starts Playwright  
- Unexpected exception: prior receipts kept, no retry, cleanup  

## Ownership model

| Mode | Who starts | Who stops |
|------|------------|-----------|
| Default `execute_plan(plan)` | Plan executor | Plan executor (`finally`) |
| `execute_plan(plan, backend=...)` | Caller (idempotent start) | **Caller** — plan does not close |

## Receipt invariants

Enforced by `PlanReceipt.check_invariants()`:

- attempted ≤ declared; verified ≤ attempted  
- `VERIFIED` cannot coexist with skipped steps  
- `completed` cannot coexist with unattempted steps or a decisive step  
- `stopped` with attempted steps requires a decisive step  
- all attempted steps share session/context/page IDs  

## No-retry / no-healing confirmation

Runtime search confirms:

- No locator mutation / healing  
- No first-match dispatch  
- No automatic reload recovery  
- No dialog dismissal  
- No backend restart on step failure  
- Only host-declared `locate_retry_ms` mechanical wait for temporarily missing targets (Milestone 1; not plan-level retry)

## Observation hardening

Sites that redirect after `domcontentloaded` can destroy the execution context
while `observe()` reads title/URL. `observe()` now tolerates unavailable
title/URL without retrying the host action. Navigate waits briefly for
`domcontentloaded` settle after `goto`. This is observation fragility handling,
not site-specific logic or action retry.

## Firefox follow-on

Firefox compatibility is documented in
[`FIREFOX_COMPATIBILITY_MILESTONE.md`](./FIREFOX_COMPATIBILITY_MILESTONE.md).
Chromium stabilization remains the prerequisite evidence base; Firefox reuses
the same plan/lifecycle/receipt contracts.
