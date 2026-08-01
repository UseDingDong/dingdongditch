# DingDongDitch Google Earth benchmark

Verdict: **FAIL**

- Google Earth URL: https://earth.google.com/web/
- Browser: fresh headed bundled Chromium 130.0.6723.31
- Navigation plan: `VERIFIED`
- Navigation completion: `completed`
- Visible evidence captured: Google Earth loading splash
- Main interface visibly ready: not verified before the capability boundary
- Verified rotation drags: 0
- Total rotation duration: 0 seconds
- Distinct rotated globe positions evidenced: 0
- Search query used: none
- Final verified location: none
- Final Mogadishu screenshot: none

## Confirmed blocking condition

DingDongDitch's production `ActionType` contract has no pointer drag action and
no pointer-down, pointer-move, or pointer-up parameters. Its available typed
actions are navigate, click, fill, press key, select option, set checked, hover,
scroll to target, wait, page management, and download.

Consequently, the required eight genuine pointer drags cannot be represented as
DingDongDitch ExecutionPlans. Using Playwright mouse APIs from the benchmark
harness would have violated the exclusive-runtime boundary. No such fallback
was used, and production code was not modified.

## Cleanup

The browser lifecycle reached `stopped`; the page was recorded as `closed`;
cleanup errors were empty. A post-run command-line audit found zero
DingDongDitch-owned Chromium, Playwright, or Node processes.
