# Phase 3 Index

**Phase:** 3 — Implementation milestones  
**Current:** Declared Wait Conditions complete (bundled Chromium + Firefox + WebKit; native Safari not supported)

| Document | Purpose |
|----------|---------|
| [`MILESTONE_1_IMPLEMENTATION_NOTES.md`](./MILESTONE_1_IMPLEMENTATION_NOTES.md) | Scope, contract, how to run |
| [`MILESTONE_1_LIMITATIONS.md`](./MILESTONE_1_LIMITATIONS.md) | Explicit non-claims |
| [`MILESTONE_1_TARGET_RESOLUTION_HARDENING.md`](./MILESTONE_1_TARGET_RESOLUTION_HARDENING.md) | Constrained semantic targets (hardening pass) |
| [`BROWSER_BOUNDARY_HARDENING.md`](./BROWSER_BOUNDARY_HARDENING.md) | Browser config / launch boundary (pre-Milestone 2) |
| [`MILESTONE_2_NATIVE_ORDERED_PLANS.md`](./MILESTONE_2_NATIVE_ORDERED_PLANS.md) | Native ordered ExecutionPlan |
| [`MILESTONE_2_CHROMIUM_STABILIZATION.md`](./MILESTONE_2_CHROMIUM_STABILIZATION.md) | Chromium plan lifecycle / receipt stabilization |
| [`FIREFOX_COMPATIBILITY_MILESTONE.md`](./FIREFOX_COMPATIBILITY_MILESTONE.md) | Bundled Firefox compatibility |
| [`BASIC_INTERACTION_EXPANSION.md`](./BASIC_INTERACTION_EXPANSION.md) | press_key, select_option, set_checked, hover, scroll_to_target |
| [`WEBKIT_COMPATIBILITY_MILESTONE.md`](./WEBKIT_COMPATIBILITY_MILESTONE.md) | Bundled WebKit compatibility (not native Safari) |
| [`DECLARED_WAIT_CONDITIONS.md`](./DECLARED_WAIT_CONDITIONS.md) | Host-authored wait_for conditions |
| [`ADAPTIVE_PLAN_TIMING.md`](./ADAPTIVE_PLAN_TIMING.md) | Bounded plan deadline + video_ended adaptive extension + multi-select |
| [`IFRAME_TARGETING.md`](./IFRAME_TARGETING.md) | Declared same-page iframe targeting |
| [`PLAN_RUNNER_CLI.md`](./PLAN_RUNNER_CLI.md) | Website-neutral JSON plan-runner CLI |

Package code lives under `/dingdongditch`. Tests under `/tests`.

Before changing scope, re-read Engineering Principles, Non-Goals, and Phase 2A
recommendation.
