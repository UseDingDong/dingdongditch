# Monkeytype production benchmark

Status: completed successfully.

Configuration: Playwright / bundled Chromium / headed. Browser session
`58891c37-5dbd-47d0-a153-f82ff2a92286`.

Monkeytype official result:

- WPM: 104
- Accuracy: 100%
- Consistency: 76%
- Characters: 521/0/0/0
- Test: time 60, English
- Raw WPM: 104

DingDongDitch navigated to Monkeytype, accepted the visible cookie consent,
selected the visible 60-second control, inspected 100 rendered English words,
and dispatched 521 ordinary per-key `PRESS_KEY` operations. Every keystroke in
the typing plan was verified. It then waited for and inspected Monkeytype's
visible official result UI.

No fill, paste, JavaScript injection, direct Playwright control, sign-in,
Monkeytype shortcut, or operator interaction was used.

Evidence preserved: five receipts, three screenshots, four inspections, the
ordered run log, raw result JSON, and terminal browser state. The browser
reached `stopped`, cleanup errors were empty, and the post-run inspection found
zero DingDongDitch-owned Playwright or bundled-browser processes.

The cookie-consent screenshot filename contains `failure` because that
single-action plan had no declared post-action expectation and was therefore
conservatively INDETERMINATE; its receipt confirms the click itself executed
successfully. This did not affect the verified typing plan or official result.
