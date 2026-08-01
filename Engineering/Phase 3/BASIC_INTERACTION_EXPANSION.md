# Basic Interaction Expansion

**Status:** Complete  
**Date:** 2026-07-26  
**Depends on:** Milestone 2 + Firefox compatibility  
**Engines:** Playwright-bundled Chromium, Firefox, and WebKit (native Safari not supported)  

## Purpose

Expand host-authored browser actions beyond navigate / fill / click with five
ordinary, explicitly declared interactions:

| Action | Purpose |
|--------|---------|
| `press_key` | Key or chord on a target or explicit `active_page` |
| `select_option` | Standard HTML `<select>` by value, label, or multi `option_values` |
| `set_checked` | Checkbox/radio to an explicit boolean state |
| `hover` | Pointer over a unique target |
| `scroll_to_target` | Bring a unique target into the viewport |

## Identity preserved

DingDongDitch still:

- executes host-authored operations only  
- does not invent actions, heal locators, or recover plans  
- separates dispatch from declared expectation verification  
- reuses one executor, target resolver, plan executor, and receipt model  

## Supported actions (current)

Host-authored actions:

- `navigate`
- `fill`
- `click`
- `press_key`
- `select_option`
- `set_checked`
- `hover`
- `scroll_to_target`

Actions remain explicitly host authored. No action planning, retries, locator
healing, or arbitrary coordinate targeting.

## Public contracts

Extended `ActionType` and `Action` fields (engine-neutral, JSON-serializable):

- `press_key`: `key`, `key_scope` (`target` default | `active_page`), `locator` when target  
- `select_option`: exactly one of `option_value` | `option_label` | `option_values`  
  (`option_values` only valid at runtime for `<select multiple>`) 
- `set_checked`: `checked: bool`  
- `hover` / `scroll_to_target`: `locator` only  

Validation rejects empty/malformed keys, contradictory key scopes, both value
and label on select, positional select index, missing checked, pixel-scroll
parameters, and other unsupported options before dispatch.

Positional select index is **rejected**. Arbitrary pixel scrolling is **rejected**.
`select_option` covers **standard HTML `<select>` only** — custom JS dropdowns
remain host-authored click sequences, not hidden select heuristics.

New expectation: `element_in_viewport` (`in_viewport: bool`).

Operation receipt schema **1.3.0** adds optional `action_evidence` (requested
parameters, before/after state, `dispatched`, `already_satisfied`, scopes).

## Action-specific semantics

### press_key

- Default safer scope is `target` (unique resolution + target key press).  
- `active_page` requires explicit `key_scope` and forbids a locator.  
- Declared key strings are preserved; no silent Control↔Meta OS substitution.  
- Dispatch success alone is not VERIFIED — declared expectations decide.

### select_option

- Exactly one of value, label, or values.  
- Backend verifies a compatible `<select>` where practical.  
- `option_values` requires `<select multiple>`; scalar path unchanged.  
- Unknown options and non-select targets fail honestly.  
- Selected value/label/`selected_values` recorded in `action_evidence` when observable.

### set_checked

- Establishes requested boolean state (Playwright `set_checked`), not blind toggle.  
- Already-satisfied → `dispatched=false`, `already_satisfied=true`.  
- Radio `checked=false` → structured `unsupported_radio_uncheck` (no JS uncheck).  
- Checkbox true/false both supported. No force-by-default; no JS property mutation path.

### hover

- Unique target hover only. No coordinates, offsets, duration sleeps, or auto submenu clicks.

### scroll_to_target

- Element scroll-into-view only. Records in-viewport before/after.  
- Already in viewport → may skip dispatch with `already_satisfied=true`.  
- Not infinite scroll, pixel deltas, or visual scanning.

## Backend translation

All Playwright calls remain in `PlaywrightBackend.dispatch` — no public
Playwright types, no per-engine public forks, no forced clicks/checks, no JS
property mutation as the normal path. Target-based actions reuse
`resolve_target` unchanged. Active-page key press records that no target
resolver ran.

## Dispatch versus verification

Unchanged: action dispatch evidence is separate from expectation results and
verdicts (`VERIFIED` / `NOT_VERIFIED` / `EXECUTION_FAILED` / `INDETERMINATE`).

## Failure semantics

Reuse existing kinds where possible (`target_resolution_failed`,
`action_dispatch_failed`, contract validation → `EXECUTION_FAILED` before
dispatch). New structured kinds include `unsupported_radio_uncheck`,
`invalid_key` / selection failures as applicable. Contract failures are not
reported as `NOT_VERIFIED`. Successful dispatch with unmet expectation remains
`NOT_VERIFIED`.

## Plan integration

Same `execute_plan` / `stop_on_failure` / skip semantics. Skipped steps never
dispatch. Prior receipts survive. Combined demo:
`examples/basic_interactions_demo.py --engine chromium|firefox [--headed]`.

## Cross-engine behavior

Chromium and Firefox (and WebKit; see WebKit milestone) share one public contract, executor, resolver, verifier,
and receipt schema. Real headed/headless integration tests cover all five
actions. Native Safari remains unsupported.

## Deterministic fixtures

Local fixture (`tests/fixtures/local_test_app/`) adds key form, HTML select,
checkboxes/radios, hover tooltip, below-fold + already-visible targets. No
public-site dependency for acceptance.

## Test matrix

- Unit: contract serialization/validation for all five actions  
- Integration: standalone + plan + stop_on_failure + cross-engine (chromium/firefox)  
- Regression: prior navigate/fill/click, plans, browser boundary, Firefox suite  

## Browser differences found

None that required public-contract forks. Viewport/idempotent scroll behavior
depends on fixture placement (already-visible must start in viewport).

## Implementation defects found and fixed

1. Attribute observation omit list lacked fixture `data-value` / `data-agree` /
   `data-prefers` → select/check expectations `NOT_VERIFIED` → expanded attribute
   reads.  
2. Scroll idempotency test scrolled below-fold first, moving “already-visible”
   out of viewport → reorder + move control near page top.

## Explicitly not included

Declared waits, iframes, tabs/popups, dialogs, downloads/uploads, screenshots,
auth workflows, retries, healing, custom dropdown heuristics, infinite scroll,
forced actions, JS event injection as the normal path. (WebKit engine support
was completed in a later milestone; native Safari remains out of scope.)

**Declared wait conditions** remain a separate upcoming milestone and were not
started here.

## Remaining V1 roadmap (not this milestone)

Declared wait conditions → **iframe targeting (done)** → dialogs → downloads/uploads →
screenshot evidence → auth/storage state. WebKit compatibility is complete
separately; native Safari is not.

## Acceptance gate

Passed when: all five typed actions validate before dispatch; backend-owned
translation; target resolver reuse; active-page keys explicit; no OS key
substitution; HTML select value/label only; honest radio-false policy; hover
without click improvisation; scroll viewport verification; receipts 1.3.0;
standalone + ExecutionPlan; stop_on_failure unchanged; Chromium + Firefox real
tests; full suite twice; deterministic demo; no hidden retry/healing/fallback;
declared waits not implemented.
