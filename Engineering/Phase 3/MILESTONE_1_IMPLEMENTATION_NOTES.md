# Milestone 1 — Implementation Notes

**Status:** Complete (local vertical slice)  
**Date:** 2026-07-26  
**Definition:** Phase 2A amended — plan-consuming browser execution runtime

## Milestone purpose

Prove the core execution contract end-to-end:

1. Host supplies one predeclared browser operation  
2. Runtime validates it  
3. Playwright Chromium executes exactly one declared action  
4. Fresh pre- and post-action observations are distinguished  
5. Declared expectations are evaluated from browser-observable evidence  
6. A structured attested receipt is returned  

**Non-goal for this milestone:** AI planning, multi-step plans, MCP, cloud, UI,
multi-browser, autonomous recovery.

## Accepted scope

- Python ≥ 3.11  
- Playwright sync API + Chromium only  
- One operation / one action  
- Local fixture app only for automated tests  

## Implemented operation contract

`Operation` fields:

- `operation_id`, `url`, `action`, `expectations[]`  
- `timeout_ms`, `freshness.max_age_ms`  
- `require_unique_target` (default true; required true for click/fill)  
- `cardinality` (default `exactly_one`; only value supported for actions)  
- `locate_retry_ms` (bounded mechanical locate retry)

Session-level browser selection uses `BrowserConfig` (default: Playwright
bundled Chromium). See [`BROWSER_BOUNDARY_HARDENING.md`](./BROWSER_BOUNDARY_HARDENING.md).

Validated before browser work. Invalid operations → `EXECUTION_FAILED`.

## Supported actions

Milestone 1 originally shipped:

| Action | Requirements |
|--------|----------------|
| `navigate` | Uses operation `url` |
| `click` | Explicit `Locator` |
| `fill` | Explicit `Locator` + `text` |

Later expanded (same contracts / executor) — see
[`BASIC_INTERACTION_EXPANSION.md`](./BASIC_INTERACTION_EXPANSION.md):

| Action | Requirements |
|--------|----------------|
| `press_key` | `key` + `key_scope` (`target` default \| `active_page`) |
| `select_option` | HTML `<select>`; exactly one of `option_value` \| `option_label` |
| `set_checked` | `checked: bool` on checkbox/radio |
| `hover` | Explicit `Locator` |
| `scroll_to_target` | Explicit `Locator` (element into view) |
| `wait_for` | Declared `WaitCondition` + bounded `wait_timeout_ms` |

No natural-language targets. No locator healing. No alternate target selection.
No arbitrary sleep action — see [`DECLARED_WAIT_CONDITIONS.md`](./DECLARED_WAIT_CONDITIONS.md).

## Supported locators

| Strategy | Fields |
|----------|--------|
| `test_id` | `value` |
| `role_name` | `role`, `name`, optional `name_match` (`contains` default, `exact`, `regex`) |
| `css` | `value` |

Optional host-declared **constraints** narrow the primary match set in
declaration order (`within`, `attribute`, `visible`, `enabled`, `exclude`).
See [`MILESTONE_1_TARGET_RESOLUTION_HARDENING.md`](./MILESTONE_1_TARGET_RESOLUTION_HARDENING.md).

Ambiguous matches with `exactly_one` cardinality → `EXECUTION_FAILED` (never
silent first-match). Receipts include a structured `target_resolution` trace.

## Supported expectations

| Type | Behavior |
|------|----------|
| `url` | exact or contains |
| `element_exists` | exists true/false |
| `element_visible` | visible true/false |
| `element_in_viewport` | in_viewport true/false (Basic Interaction Expansion) |
| `text` | contains or exact on target |
| `attribute` | attribute name/value |
| `network` | URL substring (+ optional method/status); must occur after action start |

Expectations are host-declared only (NG-09 / EP-13).

## Verdict semantics

| Verdict | Meaning |
|---------|---------|
| `VERIFIED` | Action executed and all required expectations passed with fresh evidence |
| `NOT_VERIFIED` | Action executed; one or more expectations failed |
| `EXECUTION_FAILED` | Action could not be validly dispatched/completed |
| `INDETERMINATE` | Cannot honestly decide (including: zero expectations after successful execution; stale/unavailable evidence) |

**Zero expectations + successful action → `INDETERMINATE`**, with
`action_executed_successfully=true`. This prevents false verified task success
(EP-01, L01, L15; aligns with `SUCCESS_SEMANTICS.md`).

## Evidence sources

Collected when available:

- URL / title  
- DOM/element state for checks  
- Network response log (page-level)  
- Playwright action result / exception  
- Timestamps (monotonic ms)

Receipt stores evidence once and references it from expectation results.

## Freshness behavior

Simple Milestone 1 policy (`FreshnessPolicy.max_age_ms`, default 5000):

1. Evidence used for verification must be collected at/after `action_started_at_ms`  
2. Evidence older than `max_age_ms` relative to verification completion is stale  
3. Stale required evidence → expectation `indeterminate` → top-level `INDETERMINATE`  
4. Pre-action observations are never reused as post-action proof  

**Limitation:** This is not a freeze/synchronization engine (see Phase 2 G1). Documented in `MILESTONE_1_LIMITATIONS.md`.

## Retry behavior

Only bounded mechanical locate retry within `locate_retry_ms` when the declared
target is temporarily missing. No target rewriting, no plan changes, no AI.

Retries are recorded on the receipt (`recovery_attempts`).

After action success, expectations may be polled until `timeout_ms` solely to
observe declared outcomes (e.g. delayed visibility)—not to invent new actions.

## Repository structure

```
dingdongditch/
  contract/     operation, expectation, verdict, receipt
  runtime/      executor, verifier, freshness
  backends/     playwright_backend (Chromium adapter)
  evidence/     signal models + collector
tests/
  unit/
  integration/
  fixtures/local_test_app/
examples/single_operation.py
Engineering/Phase 3/
```

## How to run the local demonstration

```bash
pip install -e ".[dev]"
python -m playwright install chromium
python examples/single_operation.py
```

## How to run the tests

```bash
pip install -e ".[dev]"
python -m playwright install chromium
python -m pytest tests -v
```

## Design decisions

1. **Dataclasses over extra validation frameworks** — keep deps to Playwright (EP-14).  
2. **Playwright confined to `backends/`** — public contract has no Page objects (EP-08 direction).  
3. **Verdict vocabulary from Milestone 1 prompt** — compatible with Phase 2 success ladder; maps L2 action success vs L4 expectation hold.  
4. **INDETERMINATE for zero expectations** — honest alternative to inventing success.  
5. **Generic domain language only** — no commerce/social vocabulary in runtime (prompt + NG-12 spirit).  
6. **Constrained targets, not healing** — hosts declare narrowing constraints; runtime never invents or ranks candidates (`MILESTONE_1_TARGET_RESOLUTION_HARDENING.md`).  
7. **No positional index** — rejected in the hardening pass; DOM order is not stable uniqueness.  
8. **Browser boundary** — Chromium is an explicit supported `BrowserConfig`, launched only via backend-owned translation (`BROWSER_BOUNDARY_HARDENING.md`).

## Governance links

- Principles: EP-01, EP-02, EP-03, EP-04, EP-05 (bounded), EP-07, EP-08, EP-11, EP-13, EP-14  
- Non-goals: NG-01, NG-02, NG-03, NG-04, NG-05, NG-08, NG-09  
- Phase 2: `PHASE_2A_RECOMMENDATION.md`, `RESPONSIBILITY_BOUNDARIES.md`, `SUCCESS_SEMANTICS.md`, challenge record  

## Test results (executed 2026-07-26)

Initial Milestone 1: `20 passed`.

After target-resolution hardening + input_value fix: `46 passed`.

After browser-boundary hardening: see latest `pytest` run in the hardening
report (suite grows with browser-boundary tests).
