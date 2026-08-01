# WebKit Compatibility Milestone

**Status:** Complete  
**Date:** 2026-07-26  
**Depends on:** Firefox compatibility + Basic Interaction Expansion  
**Not:** native Safari / SafariDriver / mobile Safari / Declared Wait Conditions  

## Purpose

Add Playwright-bundled **WebKit** as a third supported engine through the
existing shared Playwright backend — same contracts, executor, plans, target
resolver, verifier, receipts, and lifecycle ownership as Chromium and Firefox.

## Pre-modification architecture

- Supported: `playwright` + `chromium|firefox` + `bundled`
- `BrowserEngine.WEBKIT` existed but was rejected in `BrowserConfig.validate()`
- Launch translation mapped only chromium/firefox
- Capabilities excluded WebKit; limitation strings said `webkit_unsupported`
- Unsupported-engine probes used `engine=webkit`
- Baseline: **158 tests** collected/passing twice
- Receipt schema **1.3.0** (unchanged by this milestone)

## Installation

| Item | Value |
|------|--------|
| Playwright package | 1.48.0 |
| Install command | `python -m playwright install webkit` |
| WebKit | 18.0 (Playwright build v2083) |
| OS deps | None beyond Playwright’s bundled download on this Windows environment |
| Headless launch | Verified |
| Headed launch | Verified |

Missing binary continues to map to `browser_binary_unavailable` (not
`unsupported_browser_engine`).

## BrowserConfig / launch / capabilities

Supported matrix:

| provider | engine | channel |
|----------|--------|---------|
| playwright | chromium | bundled |
| playwright | firefox | bundled |
| playwright | webkit | bundled |

- Launch: `launch_playwright_browser()` → `playwright.webkit.launch(headless=…)`
- No second backend; no engine fallback
- Capabilities advertise `chromium`, `firefox`, `webkit`
- Notes include `safari_not_supported`
- `"safari"` is **not** an engine alias (rejected as unknown engine)

## Safari distinction

- **Safari** is a branded browser application / native automation surface.
- **WebKit** here is Playwright’s bundled engine/runtime.
- DingDongDitch does **not** claim native Safari, SafariDriver, STP, or mobile
  Safari support.

## Public contract stability

No Operation / Action / Expectation / ExecutionPlan / verdict changes.
Receipt schema remains **1.3.0**. Engine metadata may now truthfully be
`webkit` without a schema bump (enum value already existed; support status
changed).

Limitation strings updated:

- `playwright_bundled_chromium_firefox_webkit`
- `safari_not_supported`

(replacing `playwright_bundled_chromium_or_firefox` / `webkit_unsupported`)

## Action matrix (real WebKit)

All eight actions proven via parameterized + dedicated WebKit tests:

navigate, fill, click, press_key (target + active_page), select_option,
set_checked (incl. radio-false policy), hover, scroll_to_target.

## Plans / lifecycle

- Native `ExecutionPlan` on WebKit (comprehensive multi-action plan VERIFIED)
- `stop_on_failure` + skipped non-dispatch
- Stable session/context/page IDs
- Ten sequential owned plans
- Injected backend reuse (not closed by plan)
- Headless full matrix; headed basic plans verified on this environment

## Cross-engine parity

`ENGINES = [chromium, firefox, webkit]` in Firefox-compat and Basic Interaction
suites. Shared public contracts; engine differs only in metadata.

## Fixture / workarounds

No WebKit-only fixture branches. No browser-local action workarounds required
on this Windows + Playwright 1.48.0 matrix.

## Suite results

| Run | Result |
|-----|--------|
| Prior baseline | 158 passed (twice) |
| First full suite after WebKit | 182 passed (~10m12s) |
| Second full suite | 182 passed (~10m08s) |
| WebKit demos | basic_interactions + ordered_plan + browser_config VERIFIED (headless); basic_interactions VERIFIED headed |

## Explicitly not included

Native Safari, channels, custom executables, waits, iframes, tabs/popups,
dialogs, downloads/uploads, screenshots, auth state, retries, healing, recovery,
mixed-engine plans.

## Acceptance

Gate passed when BrowserConfig accepts webkit+bundled, real WebKit runs all
eight actions and plans, no Safari alias, no fallback, prior Chromium/Firefox
green, full suite twice, demos VERIFIED, documentation complete, waits not
started.

## Readiness for Declared Wait Conditions

Yes — WebKit support does not implement declared waits.
