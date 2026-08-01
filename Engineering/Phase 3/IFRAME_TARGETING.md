# Iframe Targeting

**Status:** Implemented (one-level same-page frames)  
**Depends on:** Milestone 1 target resolution, declared waits, shared Playwright backend

## What it is

Hosts may declare an optional **`frame`** locator on element-scoped actions,
target-based waits, and element expectations. The runtime:

1. Resolves the iframe element uniquely in the **main document**
2. Obtains its Playwright `Frame` via normal content-frame APIs
3. Resolves the action/wait target **inside that frame**
4. Dispatches through the existing action/wait path

The owned page does not change. There is no global “current frame” state and no
second executor.

## Contract shape

```json
{
  "type": "click",
  "frame": { "strategy": "test_id", "value": "unique-frame" },
  "locator": { "strategy": "test_id", "value": "frame-click" }
}
```

For `wait_for`, `frame` belongs on `wait_condition` (not `action.frame`).

| Field | Where | Meaning |
|-------|--------|---------|
| `frame` omitted | Action / wait / expectation | Main document (unchanged) |
| `frame` present | Same | Unique iframe/frame element in the main document |

## Supported

- `click`, `fill`, `press_key` (scope=`target`), `select_option`, `set_checked`,
  `hover`, `scroll_to_target`
- Target-based `wait_for` conditions (including `video_ended` on HTML5 `<video>`
  **inside** a declared frame document)
- Element expectations with matching `frame`
- Same-origin and cross-origin frames via Playwright frame APIs (no security bypass)
- Chromium, Firefox, WebKit
- `run-plan` file and stdin JSON

## Fail-closed semantics

| Situation | Outcome |
|-----------|---------|
| Missing iframe | `EXECUTION_FAILED` / `missing_frame` |
| Ambiguous iframe | `EXECUTION_FAILED` / `ambiguous_frame` |
| Detached / unavailable content frame | `EXECUTION_FAILED` / `detached_frame` |
| Non-iframe element used as frame | `EXECUTION_FAILED` / `not_a_frame` |
| Missing/ambiguous target inside frame | Existing target-resolution failure kinds |
| Wait timeout inside frame | `NOT_VERIFIED` |
| Success inside declared frame | `VERIFIED` when expectations/conditions pass |

No auto-search across frames. No silent fallback to the main document.

## Page-scoped (no `frame`)

- `navigate`
- `wait_for` `url_matches` / `load_state`
- `press_key` with `key_scope=active_page`
- URL and network expectations

## Explicitly not supported

- Nested iframe paths / multi-level frame chains
- Popup / new-tab handling
- Auto-discovery of “the” frame
- YouTube/Vimeo **embed player** media as `video_ended` (still unsupported;
  HTML5 `<video>` in a declared frame document is allowed)
- Retries, healing, browser fallback, CAPTCHA handling

## Receipts

Operation receipts use schema **1.6.0**. When a frame is declared,
`target_resolution.frame_locator` is present and stages include
`frame_primary` / `frame_cardinality` / `frame_attached` before in-frame target
stages. Plan receipts still preserve stable `browser_session_id`, `context_id`,
and `page_id`.

## Limitations stamped on receipts

- `iframe_one_level_same_page_only`
- `no_nested_iframe_path`
- `no_popup_or_new_tab_handling`
