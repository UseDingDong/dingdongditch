# Browser-Boundary Hardening

**Status:** Complete (between Milestone 1 and Milestone 2); **updated** by
Firefox and WebKit compatibility milestones  
**Date:** 2026-07-26  

## Why this pass occurred before Milestone 2

Milestone 2 introduced native ordered plans that share one browser session
across multiple operations. Chromium launch was previously hardcoded. This pass
made **bundled Chromium an explicit supported configuration** behind a
backend-owned launch boundary.

## Current supported truth

DingDongDitch **supports**:

| Field | Values |
|-------|--------|
| provider | `playwright` |
| engine | `chromium`, `firefox`, `webkit` |
| channel | `bundled` |
| headed / headless | both |

**Still unsupported:** native Safari, chrome/msedge/brave channels, custom
executables. WebKit here is Playwright’s bundled runtime — not Safari branding.

See [`WEBKIT_COMPATIBILITY_MILESTONE.md`](./WEBKIT_COMPATIBILITY_MILESTONE.md).

## Browser configuration contract

Session-level `BrowserConfig` (`dingdongditch/contract/browser.py`):

- `provider`: `playwright`
- `engine`: `chromium` | `firefox` | `webkit`
- `channel`: `bundled` | `chrome` | `msedge` | `brave` (non-bundled unsupported)
- `headless`: bool

Defaults preserve Milestone 1: Playwright + bundled Chromium + `headless=True`.
`"safari"` is not accepted as an engine alias.

## Launch translation

`launch_playwright_browser()` is the only place that calls
`playwright.<engine>.launch(...)`. No silent Chromium/Firefox/WebKit fallback.

Maps validated `BrowserConfig` →:

- `playwright.chromium.launch(headless=...)`
- `playwright.firefox.launch(headless=...)`
- `playwright.webkit.launch(headless=...)`

Still rejected before/at launch: non-bundled channels, invalid pairs, unknown
providers. No silent fallback between engines.

## Backend-owned launch translation

Single function:

`dingdongditch.backends.playwright_backend.launch_playwright_browser`

No other runtime module may call `*.launch`.

## Lifecycle ownership

`PlaywrightBackend` owns:

1. Playwright driver  
2. Browser process  
3. Browser context  
4. Page  
5. Shutdown / cleanup on failure  

`start()` is idempotent for an already-started session (reuses IDs;  
`newly_launched=false`). `stop()` clears resources and identifiers.

Prepared for Milestone 2:

```text
Plan → one BrowserConfig → one backend session → many ordered operations
```

## Session identifiers

Opaque UUIDs assigned at successful start:

- `browser_session_id`
- `context_id`
- `page_id`

Evidence only—no persistence, no reattachment API.

## Receipt metadata

Schema **1.2.0** adds `browser` object:

- provider, engine, channel, headless  
- backend_identity, browser_version  
- browser_session_id, context_id, page_id  
- newly_launched  
- capabilities snapshot  

Also `failure_kind` for structured pre-dispatch failures.

## Validation and errors

`BrowserConfig.validate()` / `BrowserConfigError` before launch.

Failure kinds include:

- `unsupported_browser_engine`  
- `unsupported_browser_channel`  
- `unsupported_engine_channel_combination`  
- `unsupported_browser_provider`  
- `browser_launch_failed` / context / page creation failures  
- `contradictory_browser_config`  

Verdict remains `EXECUTION_FAILED` (not NOT_VERIFIED / INDETERMINATE).

## Backward compatibility

- Omitted config → bundled Chromium, prior headless default  
- `PlaywrightBackend(headless=False)` still works  
- `execute_operation(..., headless=...)` still works  
- Operations do not require per-op browser fields  
- Target resolution, input_value, expectations, freshness unchanged  

## Milestone 2 inheritance

Milestone 2 puts one `BrowserConfig` on `ExecutionPlan`, starts one
`PlaywrightBackend`, runs ordered operations with `backend=`, emits step
receipts sharing `browser_session_id` / `context_id` / `page_id`, and stops the
session once when the plan owns the backend. Injected backends are not closed by
`execute_plan`. See [`MILESTONE_2_NATIVE_ORDERED_PLANS.md`](./MILESTONE_2_NATIVE_ORDERED_PLANS.md)
and [`MILESTONE_2_CHROMIUM_STABILIZATION.md`](./MILESTONE_2_CHROMIUM_STABILIZATION.md).

## Rejected over-abstractions

No BrowserFactoryFactory, plugin registry, DI container, Selenium/CDP layer,
cloud browsers, or per-engine empty subclasses.

## Limitations / future milestones

- Firefox / WebKit bundled engines: **supported** (see compatibility milestones);
  native Safari still unsupported  
- Chrome / Edge / Brave channels: **not implemented**  
- Custom executables: **not supported**  
- Only Playwright provider  

## Governance

- EP-08 / EP-14: backend isolation, minimal deps  
- NG: no false multi-browser claims; no silent healing of config  
- Phase 2 boundaries: runtime executes declared work; does not invent browsers  
