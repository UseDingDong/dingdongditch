# Iframe Targeting

**Status:** Implemented (bounded same-page frame paths)
**Depends on:** target resolution, declared waits, and the shared Playwright backend

## What it is

Element-scoped actions, target waits, element expectations, page
preconditions, and inspection may use either a legacy one-hop `frame` locator
or an explicit `frame_path` of up to eight locators. `frame_path` resolves each
iframe/frame element in order, starting in the main document and then in the
previously declared frame.

```json
{
  "type": "click",
  "frame_path": [
    { "strategy": "test_id", "value": "outer-frame" },
    { "strategy": "test_id", "value": "inner-frame" }
  ],
  "locator": { "strategy": "test_id", "value": "frame-click" }
}
```

`frame` and `frame_path` are mutually exclusive. For `wait_for`, the frame
scope belongs to `wait_condition`, not `action`.

There is no global current-frame state, second executor, automatic frame
search, cross-path fallback, or fallback to the main document.

## Supported

- `click`, `fill`, target-scoped `press_key`, `select_option`, `set_checked`,
  `hover`, `scroll_to_target`, `upload_file`, and `select_combobox_option`
- Target-based `wait_for` conditions and element expectations
- Element-visible page preconditions and read-only target inspection
- Same-origin and cross-origin frames through Playwright frame APIs, without a
  security bypass
- Chromium, Firefox, and WebKit
- JSON plans and the Python API

Page-scoped URL/load-state waits and URL/network expectations do not accept a
frame scope.

## Fail-closed semantics

| Situation | Outcome |
|---|---|
| Missing frame at hop *n* | `EXECUTION_FAILED` / `missing_frame`, `failure_hop=n` |
| Ambiguous frame at hop *n* | `EXECUTION_FAILED` / `ambiguous_frame`, `failure_hop=n` |
| Detached or unavailable content frame | `EXECUTION_FAILED` / `detached_frame` |
| Non-frame element | `EXECUTION_FAILED` / `not_a_frame` |
| Missing/ambiguous target in final frame | Existing target-resolution failure kinds |
| Wait timeout in final frame | `NOT_VERIFIED` |
| Success in declared frame path | `VERIFIED` when normal expectations pass |

Each operation resolves its path freshly, including after a frame reload.
Receipts include only safe, bounded frame fingerprints plus the declared path,
resolved depth, and failed hop; they never expose a browser `Frame` object.

## Explicitly not supported

- Frame auto-discovery or a heuristic choice of "the" frame
- Cross-page frame attachment or browser-security bypasses
- Popup/new-tab behavior as a side effect of selecting a frame
- Retries, locator healing, browser fallback, CAPTCHA handling, or arbitrary
  workflow control flow

## Receipt impact

Execution receipt schema **1.8.0** records frame-path resolution in bounded
target evidence. Core receipts expose `frame_path_depth` and `failure_hop` only;
the detailed resolution trace remains bounded evidence.
