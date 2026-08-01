# Windows desktop vertical slice: FAIL

## Outcome

The production desktop domain was implemented and its unit/browser-compatibility
tests passed. The one fresh benchmark run failed at controlled-folder
navigation. It was not retried.

## Architecture and technology

- Architecture: narrowly separated Windows desktop execution domain sharing
  ordered-plan, verdict, lifecycle, screenshot-policy, and receipt conventions.
  Existing browser contracts/executors were not changed.
- Automation: `pywinauto` 0.6.9 with the Microsoft UI Automation (`uia`)
  backend; PyWin32 is used internally for foreground/process/window identity;
  Pillow captures desktop screenshots.
- Typed actions: `launch_application`, `open_path_in_explorer`,
  `wait_for_window`, `focus_window`, `activate_ui_target`, and `close_window`.
- Launch is allowlisted to Explorer and Notepad. No arbitrary executable,
  arguments, shell command, elevation, or implicit adoption is exposed.

## Tests

- New desktop unit tests: 13 passed.
- Complete unit suite: 225 passed, 1 skipped.
- Complete integration suite: inconclusive; the command exceeded its 10-minute
  budget and returned no terminal test result. No Python test runner remained.

## Fresh benchmark

- Plan verdict: `EXECUTION_FAILED`
- Declared operations: 8
- Attempted operations: 2
- Verified operations: 1
- Skipped operations after stop-on-failure: 6
- Per-action receipts: 2
- Screenshots: 1
- Cleanup errors: 0
- Remaining DingDongDitch-owned process count: 0

### Step results

1. Explorer launch: VERIFIED.
   - typed requested application: `explorer`
   - constrained executable: `explorer.exe`
   - launch PID: 7128
   - discovered Explorer PID: 10488
   - window handle: 1901978
   - title: `Documents - File Explorer`
   - foreground verification: passed
   - ownership: session-owned window and recorded launched/discovered PIDs
2. Controlled-folder navigation: EXECUTION_FAILED.
   - UIA address-edit interaction returned COM error `0x800704C7`:
     `The operation was canceled by the user.`
   - The controlled path and visible test file were therefore not verified.
3. File activation and associated application: skipped.
4. Associated application close: skipped.
5. Notepad launch/focus/close: skipped.
6. Explicit Explorer close operation: skipped; terminal safe cleanup closed the
   owned Explorer window successfully.

## Evidence

- `execution_plan.json`: exact typed plan
- `final_receipt.json`: structured plan and action receipts
- `run_summary.json`: counts and cleanup terminal state
- `screenshots/`: Explorer launch screenshot
- `desktop_test_folder/hello_from_dingdongditch.txt`: isolated harmless fixture

## Known limitations

- Windows 11 Explorer's address edit did not accept this UIA value-setting path
  reliably. A production fix should locate and use Explorer's navigation
  breadcrumb/address patterns by stable AutomationId/control hierarchy, with a
  bounded UIA keyboard fallback and explicit navigation-state observation.
- Associated-application discovery is currently scoped to the allowlisted text
  viewer expected for this slice (Notepad), not arbitrary file associations.
- The desktop domain is Python-API selected; a unified multi-domain JSON/CLI
  dispatcher is intentionally outside this slice.

## Recommended next capability

Harden typed Explorer navigation (and only that capability) against current
Windows 11 UIA control variants, then rerun a separately authorized fresh
vertical-slice benchmark. Do not add file manipulation, clipboard, drag/drop,
or general desktop automation before this baseline passes.
