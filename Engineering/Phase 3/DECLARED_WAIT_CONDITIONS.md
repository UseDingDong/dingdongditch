# Declared Wait Conditions

**Status:** Complete  
**Date:** 2026-07-26  
**Depends on:** WebKit compatibility + Basic Interaction Expansion  
**Not:** iframes, popups, dialogs, downloads, uploads, sleeps, retries, healing  

## Purpose

Add one host-authored action, `wait_for`, that observes until a single declared
browser-observable condition is true or a bounded timeout expires — without
arbitrary sleeps, compound expressions, or hidden recovery.

## Pre-modification baseline

- **182 tests** passing twice  
- Engines: Chromium, Firefox, WebKit (Playwright-bundled)  
- Receipt schema **1.3.0**  
- No generic wait action; expectation polling after actions only  

## Contract

```text
Action(type=wait_for, wait_condition=WaitCondition(...), wait_timeout_ms=?)
```

| Setting | Policy |
|---------|--------|
| Default timeout | 5_000 ms |
| Minimum | 100 ms |
| Maximum | 60_000 ms |
| Poll interval | 50 ms (bounded observation loop; not a sleep action) |

Condition types:

| Type | Target | Notes |
|------|--------|-------|
| `element_visible` | required | Unique resolve; fail-closed ambiguity |
| `element_hidden` | required | Not visible **or** absent/detached; ambiguity never counts as hidden |
| `text_present` | required | Exact or contains within target (no whole-page scan) |
| `url_matches` | none | `exact` / `contains` string matchers (no executable regex) |
| `attribute_equals` | required | Attribute (value uses input_value when applicable) |
| `value_equals` | required | `input_value` observation |
| `checked_equals` | required | Checkbox/radio checked state |
| `selected_value_equals` | required | HTML `<select>` only |
| `element_in_viewport` | required | Same viewport semantics as expectations |
| `load_state` | none | `domcontentloaded` \| `load` only (no `networkidle`) |
| `video_ended` | required | Same-document HTML5 `<video>` only; observes `ended` |

No compound AND/OR. One wait → one condition.

### `video_ended` boundaries

Supported: uniquely resolved same-document HTML5 `<video>` elements.

Unsupported (fail closed or not claimed):

- YouTube / Vimeo embeds
- iframe-hosted media
- browser-native media control chrome as a separate target
- popup / new-tab media
- players without a real HTML5 `<video>` element

`VERIFIED` requires observing `ended === true`. Timeout without completion is
`NOT_VERIFIED`. Non-`<video>` targets yield `EXECUTION_FAILED`
(`target_not_video`). Ambiguity fails closed.
## Verdict semantics

| Outcome | Verdict |
|---------|---------|
| Condition observed before timeout | `VERIFIED` |
| Timeout without condition | `NOT_VERIFIED` (not execution failure) |
| Ambiguity / dispatch / observation hard failure | `EXECUTION_FAILED` |
| Evidence unreliable | `INDETERMINATE` |
| Invalid contract | validation failure before dispatch |

Dispatch success alone is never VERIFIED — the condition must be observed.

## Receipt evidence (`action_evidence`)

Includes: `condition_type`, `requested_timeout_ms`, `elapsed_ms`,
`condition_satisfied`, `timeout_occurred`, `final_observed_state`,
`observation_count`, plus target-resolution when applicable.

Schema bumped to **1.4.0** (new action type + wait evidence semantics).

## Architecture

Same executor, plan executor, target resolver, shared Playwright backend,
lifecycle IDs, and `stop_on_failure` / skip rules. Backend owns
`_dispatch_wait_for` polling / load_state wait.

## Plan behavior

`wait_for` works standalone and inside `ExecutionPlan` on all three engines.
Timeout → NOT_VERIFIED → later steps skipped, never dispatched.

## Fixture

Local fixture adds delayed hide/state/hash triggers with short `setTimeout(150)`
delays (event-driven demo content, not a runtime sleep action).

## Related fix

`ensure_on_url` treats same path+query as already on-document even if the
fragment differs, so `url_matches` can observe hash changes without being wiped.

## Rejected scope

Arbitrary sleep actions, compound waits, retries, reload recovery, locator
healing, iframe/popup/download/dialog waits, `networkidle`, JS callback
conditions, universal website compatibility.

## Suite results

| Run | Result |
|-----|--------|
| Prior baseline | 182 passed (twice) |
| First full suite | 208 passed (~11m37s) |
| Second full suite | 208 passed (~12m13s) |
| Focused wait e2e | 20 passed |
| Demos | chromium/firefox/webkit VERIFIED; `--demo-timeout` → NOT_VERIFIED skipped=1; headed chromium VERIFIED |

## Acceptance

Gate passed: typed `wait_for`, all conditions on three engines, timeout →
NOT_VERIFIED, plans/stop_on_failure intact, schema 1.4.0, no sleep/retry/healing,
prior tests green, suite twice, docs complete, iframes not started.

## Ready for Iframe Targeting

Completed — see [`IFRAME_TARGETING.md`](./IFRAME_TARGETING.md).
