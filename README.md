# DingDongDitch

Open-source **browser execution infrastructure**: a plan-consuming runtime that
validates typed `ExecutionPlan` documents, drives a shared Playwright backend,
observes the page, and returns **attested receipts**.

It is **not** an AI assistant, built-in planner, autonomous website explorer,
workflow authoring system, browser, or Playwright replacement.

## Durable continuity (optional)

`ContinuitySession` is a thin host-side control-state journal above the
execution runtime. It records host-authorized browser commands, leased browser
binding metadata, and integrity-checked references to already-published
DingDongDitch receipts. It does not execute commands, choose next actions,
retry unknown outcomes, or persist browser-local objects.

Its command lifecycle is `proposed -> authorized -> dispatched`, followed by
`verified`, `failed`, or `outcome_unknown`; cancellation is allowed only before
dispatch. Reopening a session after an unconfirmed dispatch records
`outcome_unknown` and never replays the command. The reasoning host remains
responsible for every subsequent decision.

## Architecture boundary

```text
Developer code / Cursor / CI / test framework / custom Python host
                         ↓
               authors ExecutionPlan
                         ↓
                   DingDongDitch
        validates, executes, observes, receipts
```

| Role | Responsibility |
|------|----------------|
| **Host** | Project-specific intent: URLs, locators, actions, waits, expectations |
| **DingDongDitch** | Fail-closed validation, ordered execution, observation, receipts |

The host may be a small Python script, a JSON file, Cursor, a test harness, or
another application. DingDongDitch does **not** infer user intent, invent
workflows, choose products/forms/links, study arbitrary sites, or replace
developer-written host code.

## Before changing architecture or expanding scope

Review:

1. [`Engineering/ENGINEERING_PRINCIPLES.md`](./Engineering/ENGINEERING_PRINCIPLES.md)  
2. [`Engineering/NON_GOALS.md`](./Engineering/NON_GOALS.md)  
3. [`Engineering/Phase 2/PHASE_2A_RECOMMENDATION.md`](./Engineering/Phase%202/PHASE_2A_RECOMMENDATION.md)  
4. [`Engineering/Phase 2/RESPONSIBILITY_BOUNDARIES.md`](./Engineering/Phase%202/RESPONSIBILITY_BOUNDARIES.md)  
5. [`Engineering/Phase 2/SUCCESS_SEMANTICS.md`](./Engineering/Phase%202/SUCCESS_SEMANTICS.md)  
6. [`Research/RECONNAISSANCE_REPORT.md`](./Research/RECONNAISSANCE_REPORT.md)  
7. [`Research/Lessons Learned/`](./Research/Lessons%20Learned/)  

## Repository map

| Path | Contents |
|------|----------|
| [`dingdongditch/`](./dingdongditch/) | Runtime package (contracts, executor, CLI) |
| [`tests/`](./tests/) | Unit + Playwright e2e tests |
| [`examples/`](./examples/) | Infrastructure-neutral demos (local fixture) |
| [`Engineering/`](./Engineering/README.md) | Principles, non-goals, Phase 2–3 docs |
| [`Research/`](./Research/README.md) | Phase 1 reconnaissance archive |

## Current implementation

Attested **ordered plan** execution (and standalone operations) via
Playwright-bundled **Chromium**, **Firefox**, and **WebKit**. Host-declared
actions:

`navigate`, `fill`, `click`, `press_key`, `select_option`, `set_checked`,
`hover`, `scroll_to_target`, `wait_for`, `download`.

### Guarded interaction sessions

`TypingSession` is the first session-level primitive. It retains one active
backend, acquires a declared focus target with the ordinary `click` action,
verifies focus, and types through ordinary `press_key` dispatches. The complete
standalone-operation lifecycle runs at session boundaries rather than once per
character; each key still receives a lightweight evidence/recovery receipt. It repeats
the focus check at a host-configured character interval and stops before the
next key if the page or target is no longer safe.

Two generic focus policies are available: strict `target_focused` for editable
controls, and `page_focused_target_visible` for pages that intentionally handle
keyboard input outside a focused form control. The structured result includes
lifecycle checkpoints and every child operation receipt. The shared managed
session phases (`acquire`, `verify`, `perform`, `finish`) are reusable by future
drag, scroll, upload, and playback sessions without changing `TypingSession`.

Optional **`frame`** scopes element actions/waits/expectations to one unique
same-page iframe (one level; no auto-search; no main-document fallback).

Plans may declare `initial_plan_timeout_ms`, `adaptive_timeout_enabled`, and
`max_plan_timeout_ms`. Adaptive extension is **video_ended-only**, from
observed HTML5 media facts, and never exceeds the declared ceiling. Ordinary
action timeouts are not inflated by a longer plan deadline.
`select_option` accepts scalar `option_value` / `option_label` or multi
`option_values` for `<select multiple>`.

### Browser profiles

Select session state through the public `BrowserConfig` API:

```python
from dingdongditch import BrowserConfig, BrowserProfile

config = BrowserConfig(profile=BrowserProfile.DINGDONG)
```

`benchmark` (the default) creates a fresh temporary context, `dingdong` uses
one isolated persistent Chromium user-data directory across executions, and
`default` optionally opens the existing Chrome `Default` profile when it can
be found. JSON plans accept the equivalent `"profile": "benchmark"`,
`"dingdong"`, or `"default"` browser field. Set
`DINGDONGDITCH_PROFILE_DIR` to explicitly relocate the isolated `dingdong`
profile.

> **Security warning:** persistent profiles are state containers, not security
> sandboxes. `dingdong` retains cookies and browser-local state between runs.
> `default` gives plans access to the existing Chrome Default profile, including
> authenticated sessions. The profile lease prevents concurrent DingDongDitch
> use only; it does not isolate a plan from that profile's data or permissions.
> Use the default `benchmark` profile unless persistent state is explicitly
> required and the plan is trusted.

- Adaptive timing: [`Engineering/Phase 3/ADAPTIVE_PLAN_TIMING.md`](./Engineering/Phase%203/ADAPTIVE_PLAN_TIMING.md)  
- Iframes: [`Engineering/Phase 3/IFRAME_TARGETING.md`](./Engineering/Phase%203/IFRAME_TARGETING.md)  
- Plan-runner CLI: [`Engineering/Phase 3/PLAN_RUNNER_CLI.md`](./Engineering/Phase%203/PLAN_RUNNER_CLI.md)  
- Declared waits: [`Engineering/Phase 3/DECLARED_WAIT_CONDITIONS.md`](./Engineering/Phase%203/DECLARED_WAIT_CONDITIONS.md)  
- WebKit: [`Engineering/Phase 3/WEBKIT_COMPATIBILITY_MILESTONE.md`](./Engineering/Phase%203/WEBKIT_COMPATIBILITY_MILESTONE.md)  
- Basic interactions: [`Engineering/Phase 3/BASIC_INTERACTION_EXPANSION.md`](./Engineering/Phase%203/BASIC_INTERACTION_EXPANSION.md)  
- Firefox: [`Engineering/Phase 3/FIREFOX_COMPATIBILITY_MILESTONE.md`](./Engineering/Phase%203/FIREFOX_COMPATIBILITY_MILESTONE.md)  
- Stabilization: [`Engineering/Phase 3/MILESTONE_2_CHROMIUM_STABILIZATION.md`](./Engineering/Phase%203/MILESTONE_2_CHROMIUM_STABILIZATION.md)  
- Milestone 2: [`Engineering/Phase 3/MILESTONE_2_NATIVE_ORDERED_PLANS.md`](./Engineering/Phase%203/MILESTONE_2_NATIVE_ORDERED_PLANS.md)  
- Milestone 1 notes: [`Engineering/Phase 3/MILESTONE_1_IMPLEMENTATION_NOTES.md`](./Engineering/Phase%203/MILESTONE_1_IMPLEMENTATION_NOTES.md)  
- Limitations: [`Engineering/Phase 3/MILESTONE_1_LIMITATIONS.md`](./Engineering/Phase%203/MILESTONE_1_LIMITATIONS.md)  
- Target hardening: [`Engineering/Phase 3/MILESTONE_1_TARGET_RESOLUTION_HARDENING.md`](./Engineering/Phase%203/MILESTONE_1_TARGET_RESOLUTION_HARDENING.md)  
- Browser boundary: [`Engineering/Phase 3/BROWSER_BOUNDARY_HARDENING.md`](./Engineering/Phase%203/BROWSER_BOUNDARY_HARDENING.md)  

**Browser truth:** Playwright-bundled Chromium, Firefox, and WebKit only.
Native Safari and Chrome/Edge/Brave channels remain unsupported.

`wait_for` observes one declared condition with a bounded timeout. It is not an
arbitrary sleep, retry, or recovery mechanism. Supported waits include
`video_ended` for HTML5 `<video>` in the main document or a declared frame
document. Third-party embed players, native media-control chrome, popups/new
tabs, uploads, and nested iframe paths remain unsupported / later milestones.

### Downloads

`download` is a first-class action whose success is based on the browser
download event and completed file, never on trigger success alone. The
session-level `BrowserConfig.download_policy` owns the trusted artifact root.
Actions may choose only a validated relative subdirectory and filename.

Completed artifacts use:

```text
<artifact_root>/downloads/<browser-session-id>/
    staging/
    completed/
```

The runtime arms event and page monitoring before the declared click/key
trigger, correlates exactly one event to the operation, saves into staging,
enforces filename/path, size, extension, MIME, collision and page-effect
policies, calculates the requested checksum, and atomically commits the file.
Completed files survive ordinary browser cleanup. DingDongDitch never opens,
executes, extracts, previews, or otherwise activates downloaded content.

### Permanent execution interfaces

```bash
python -m dingdongditch run-plan path/to/plan.json
python -m dingdongditch run-plan -
```

The CLI only **loads and executes** already-authored plans (file or stdin).
It does not author, heal, or reinterpret them.

### Explicit navigation and shared sessions

Only a `navigate` operation may intentionally load a document. For every other
operation, `url` is a page-identity precondition. A different fragment on the
same scheme/host/path/query is accepted; a different document fails closed with
`page_precondition_mismatch` before dispatch. Hosts that previously relied on a
standalone click/fill operation to open its URL must add an explicit navigate
step and execute both operations in one plan or active shared backend.

When a host supplies a `PlaywrightBackend`, its complete `BrowserConfig` must
equal the plan configuration. A mismatch is rejected without starting,
stopping, or mutating the host-owned session.

`PlanBuilder` is available to reduce typed-plan boilerplate without choosing
workflow details. `inspect_target(backend, locator)` provides read-only target
diagnostics for an already active host-owned session; it never navigates or
dispatches an action.

Declared HTML5 media waits include `video_ended`, `video_playing`, and
`video_completed_once`. The latter requires trustworthy progression and, for
looping media, a near-end-to-start wrap on the same video element and source.

### Quick start

```bash
pip install -e ".[dev]"
python -m playwright install chromium firefox webkit
python -m pytest tests -v
python -m dingdongditch run-plan examples/plans/basic_navigation.json
python -m dingdongditch run-plan examples/plans/iframe_targeting.json
python -m dingdongditch run-plan examples/plans/basic_navigation.json --engine firefox
python -m dingdongditch run-plan examples/plans/basic_navigation.json --engine webkit
Get-Content examples/plans/basic_navigation.json | python -m dingdongditch run-plan -
python examples/host_execution_plan.py
python examples/single_operation.py
python examples/ordered_plan_demo.py
python examples/ordered_plan_demo.py --engine firefox
python examples/ordered_plan_demo.py --engine webkit
python examples/basic_interactions_demo.py
python examples/declared_wait_conditions_demo.py
python examples/browser_config_demo.py --engine webkit
```

DingDongDitch is pre-1.0 alpha software. Public contracts may change between
minor releases; review the changelog when upgrading.

## Community and project policies

- [Contributing](./CONTRIBUTING.md)
- [Support](./SUPPORT.md)
- [Security policy](./SECURITY.md)
- [Governance](./GOVERNANCE.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)
- [Changelog](./CHANGELOG.md)
- [MIT License](./LICENSE)
