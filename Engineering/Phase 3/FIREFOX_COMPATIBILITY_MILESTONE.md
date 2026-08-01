# Firefox Compatibility Milestone

**Status:** Complete (acceptance gated on real bundled Firefox tests)  
**Date:** 2026-07-26  
**Depends on:** Milestone 2 + Chromium stabilization  
**Not:** WebKit / Safari / Chrome / Edge / Brave channels  

## Purpose

Add Playwright-bundled Firefox as a second explicit browser engine behind the
existing browser/backend boundary, without forking public contracts or adding
workflow capability.

## Why after Chromium stabilization

Firefox sits on a known-good Chromium plan lifecycle (ownership, cleanup,
receipts, stop-on-failure). Introducing a second engine before that would
confound root-cause analysis.

## Supported configurations

| provider | engine | channel | headed | headless |
|----------|--------|---------|--------|----------|
| playwright | chromium | bundled | yes | yes |
| playwright | firefox | bundled | yes | yes |

## Unsupported

WebKit, Safari, chrome/msedge/brave channels, custom executables, remote
browsers, Selenium, CDP, mixed-engine plans, in-plan engine switching.

## Launch translation

Single authoritative function:

`dingdongditch/backends/playwright_backend.py::launch_playwright_browser`

- chromium + bundled → `playwright.chromium.launch(...)`
- firefox + bundled → `playwright.firefox.launch(...)`
- anything else → structured error (never silent Chromium fallback)

## Browser binary installation

Documented setup:

```bash
python -m playwright install chromium firefox
```

Normal `execute_operation` / `execute_plan` do **not** download browsers.
Missing binary → `browser_binary_unavailable` with install hint (not
`unsupported_browser_engine`).

## Backend capabilities

`PlaywrightBackend.capabilities()` reports engines `(chromium, firefox)`,
channel `(bundled)`, actions navigate/click/fill/press_key/select_option/
set_checked/hover/scroll_to_target, headed+headless.

## Public contract stability

Unchanged: Operation, Target, Expectation, ExecutionPlan, receipts, verdicts,
failure policy, skip semantics. Browser selection remains plan/session-level
`BrowserConfig` only.

## Lifecycle

Same ownership model as Chromium: one backend owns driver/browser/context/page;
owned plans start/stop once; injected backends are not closed by `execute_plan`.

## Compatibility findings

- Target resolution, fill `input_value()`, plans, stop-on-failure, and receipt
  invariants work on Firefox without public-API forks.
- Redirect-time observation hardening (from Chromium stabilization) applies to
  Firefox as well.
- No Firefox-specific locator healing, forced clicks, or engine fallback.

## Live / public sites

Public websites remain environmental targets for optional host experiments —
not CI dependencies and not part of DingDongDitch. Overlays, CAPTCHAs, and
bot challenges are honest stop boundaries (no auto-dismiss, no healing).

## Repeated stability

Full suite run twice after Firefox work; focused Firefox tests include 10
sequential owned plans and alternating success/stopped paths.

## Limitations

- WebKit not implemented → **superseded:** see [`WEBKIT_COMPATIBILITY_MILESTONE.md`](./WEBKIT_COMPATIBILITY_MILESTONE.md)  
- Public sites remain environmental, not CI  
- Firefox support ≠ universal website compatibility  

## WebKit readiness

**Complete** as a separate milestone: Playwright-bundled WebKit is supported.
Native Safari remains unsupported. See
[`WEBKIT_COMPATIBILITY_MILESTONE.md`](./WEBKIT_COMPATIBILITY_MILESTONE.md).
