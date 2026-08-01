# Browser-native dialog handling implementation report

## Architecture changes

DingDongDitch now keeps native dialog policy in the existing host-authored
`Operation` contract. The runtime installs a Playwright page dialog listener
before dispatching the operation, handles only the declared policy, resumes
the existing observation/verification pipeline, and returns the same
evidence-backed `ExecutionReceipt`/`PlanReceipt` models.

No planner, autonomous browsing, locator healing, hidden retry, or guessed
dialog action was introduced.

## Typed host API

The additive `DialogContract` supports:

- `DialogType.ALERT`, `CONFIRM`, `PROMPT`, and `BEFOREUNLOAD`;
- `DialogRequirement.REQUIRED`, `OPTIONAL`, or `FORBIDDEN`;
- `DialogAction.ACCEPT` or `DISMISS`;
- exact or contains message matching;
- prompt text for accepted prompts;
- bounded `timeout_ms` and optional prompt redaction.

Example:

```python
Operation(
    operation_id="accept-login-alert",
    url=url,
    action=Action(type=ActionType.CLICK, locator=login_locator),
    dialog_contract=DialogContract(
        requirement=DialogRequirement.REQUIRED,
        dialog_type=DialogType.ALERT,
        message="Login complete",
        action=DialogAction.ACCEPT,
        timeout_ms=1_000,
    ),
)
```

JSON plan loading accepts the same `dialog_contract` shape. Hosts can inspect
history read-only with `list_dialog_history(backend)`.

## Dialog lifecycle and failure classifications

The listener is installed before dispatch and removed after the operation. Each
event is associated with operation ID and active page ID. Contract-authorized
dialogs are handled immediately. Forbidden or mismatched dialogs are
emergency-dismissed only to release a potentially blocking browser resource;
the receipt still fails and marks `cleanup_only: true`.

Stable failure kinds are:

- `expected_dialog_not_appeared`;
- `unexpected_dialog`;
- `dialog_type_mismatch`;
- `dialog_message_mismatch`;
- `prompt_text_missing`;
- `multiple_dialogs_opened`;
- `dialog_handling_failed`.

Existing `plan_deadline_expired` remains authoritative when the plan budget is
exhausted during dispatch or dialog waiting.

## Receipt fields and cleanup

Action evidence retains `dialog_appeared`, the declared policy, dialog type and
message, triggering operation ID, page ID, action taken, prompt text (redacted
when requested), appearance/handling timestamps, handling duration,
contract-authorized versus cleanup-only status, dialog history size, and
deadline state. Terminal lifecycle identity retains dialog history alongside
closed page evidence. Runtime shutdown continues to close context, browser,
and Playwright normally.

## Deterministic local tests

Added `tests/fixtures/local_test_app/dialog_fixture.html` and
`tests/integration/test_dialogs_e2e.py`, covering alert accept, confirm
dismiss, prompt accept/redaction, unexpected dialog cleanup, required-dialog
absence, wrong message, and multiple dialogs. A beforeunload test is included
as a non-strict xfail because bundled Chromium/Playwright does not consistently
surface beforeunload as a `Dialog` event; the report does not claim that case is
green.

Focused result: **6 passed, 1 xfailed**.

## Test results and compatibility concerns

- Focused dialog suite: **6 passed, 1 xfailed**.
- Two full-suite runs were attempted; both exceeded the 120-second outer
  command limit without a pytest completion summary. This is recorded as an
  unresolved suite-run/environment limitation, not a pass.
- Sandboxed browser startup can fail because the Node Playwright driver cannot
  `lstat` the managed user profile; focused browser tests pass with the required
  local-browser permission.
- The runtime capability limitation was updated from the obsolete
  `no_popup_or_new_tab_handling` label to `native_dialogs_host_declared_only`.

## Recommended next action

Investigate the full-suite timeout with per-file isolation and a test-timeout
plugin. Separately decide whether to provide a browser-engine-specific
beforeunload capability probe or keep the current explicit non-strict support
boundary.
