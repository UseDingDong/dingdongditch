# Adaptive Plan Timing

**Status:** Complete  
**Date:** 2026-07-26  
**Depends on:** Declared Wait Conditions + Ordered Plans  
**Not:** retries, healing, browser fallback, popup handling, AI planner, site-specific logic  

## Purpose

Add a **bounded overall plan deadline** that the host declares, and allow
**runtime extension only** from trustworthy observed facts for explicitly
supported wait conditions (currently `video_ended`).

Three timing concepts stay separate:

| Concept | Field(s) | Inflated by adaptive plan deadline? |
|---------|----------|-------------------------------------|
| Per-action timeout | `Operation.timeout_ms` | No |
| Per-wait timeout | `Action.wait_timeout_ms` | Wait **deadline** may extend; declared wait timeout is unchanged |
| Overall plan deadline | `initial_plan_timeout_ms` → monotonic deadline | Yes, when adaptation grants |

## Host contract (`ExecutionPlan`)

| Field | Role |
|-------|------|
| `initial_plan_timeout_ms` | Initial overall budget from plan start (monotonic) |
| `adaptive_timeout_enabled` | When false, no runtime extension |
| `max_plan_timeout_ms` | Hard ceiling from plan start; never exceeded |

Validation (before browser launch):

- Budgets are ints in `[100, 3_600_000]`
- Adaptive on ⇒ both budgets required and `max >= initial`
- Adaptive off ⇒ `max` optional but if set requires `initial` and `max >= initial`
- Invalid timing ⇒ `invalid_plan_timing` / `EXECUTION_FAILED` without launching

## Adaptive extension algorithm (`video_ended`)

Only after a unique HTML5 `<video>` observation with trustworthy media facts:

1. Reject (no grant): looping, infinite/NaN/zero duration, invalid rate, never
   started (paused at t≈0), stalled/`readyState < 1`, already ended, missing
   target / ambiguity / ordinary failures.
2. `remaining_ms = ceil((duration - currentTime) / playbackRate * 1000) + 2000`
   (bounded buffering/cleanup margin).
3. Request extension so wait and plan deadlines reach `now + remaining_ms` when
   needed.
4. Cap by `plan_started + max_plan_timeout_ms`.
5. Apply monotonically; do **not** restart action, page, browser, or plan.

`adaptive_timeout_enabled=false` ⇒ no extension. Unsupported conditions never
request extension (fail closed / no-op).

## Semantics

| Event | Outcome |
|-------|---------|
| Plan deadline expires | Honest `NOT_VERIFIED`, `plan_deadline_expired`, normal cleanup / skip remaining |
| Invalid timing contract | Validation failure before launch |
| Ceiling blocks full ask | Grant partial (or zero); receipt records `ceiling_prevented_full_extension` |

Ordinary action timeouts are **not** increased when the plan deadline grows.

## Receipt metadata (`plan_timing`)

Plan receipts (schema **2.1.0**) include:

- initial plan budget / original deadline / resulting deadline  
- max ceiling / adaptive enabled  
- per-decision: observed duration, currentTime, playbackRate, requested /
  granted extension, reason, whether ceiling prevented a full extension  

Wait evidence may include `adaptive_timing` for the last noteworthy decision.
Operation receipts use schema **1.6.0**.

## Multi-select (`select_option`)

Exactly one of:

- `option_value` — single value (scalar path unchanged)  
- `option_label` — single label  
- `option_values` — non-empty list; **only** valid for `<select multiple>`  

`value` + `values` together, empty `values`, or `values` on a non-multiple
select fail closed. Receipts record `selected_values`.

## Limitations

- Adaptive extension is **video_ended only**  
- No site-specific media heuristics  
- No retries / healing / browser fallback / popup handling  
- No direct JavaScript execution as a host action  
- Declared wait timeout max remains 60s; runtime wait **deadline** may grow via
  adaptive extension up to the plan ceiling  
