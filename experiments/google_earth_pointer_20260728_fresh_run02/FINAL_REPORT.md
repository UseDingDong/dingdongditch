# DingDongDitch Google Earth POINTER_MOVE benchmark

Verdict: **FAIL**

- Google Earth URL: https://earth.google.com/web/
- Browser: fresh headed bundled Chromium 130.0.6723.31
- Navigation plan: `VERIFIED`
- Dynamic Google Earth origin/path precondition: passed
- Interface ready verification: failed
- Successful `POINTER_MOVE` operations: 0
- Pointer targets visited: none
- Screenshot count: 1
- Search performed: no
- Drag performed: no

## Execution result

The fresh production session navigated successfully. Google Earth rewrote the
initial URL to its live camera-state URL, which was accepted using typed origin
and path preconditions. A bounded 40-second `ELEMENT_VISIBLE` wait then checked
for the visible Search control 381 times.

The control never appeared and the final observed match count was zero. The
preserved screenshot shows Google Earth still on its animated loading splash,
not the fully loaded main interface. The benchmark therefore stopped before
issuing any pointer movement, as required by the declared sequence.

No pointer receipt or cursor-location screenshot is claimed. Moving over the
loading splash would not validate pointer interaction with the ready Google
Earth interface.

## Cleanup

- Browser lifecycle: `stopped`
- Recorded pages: 1 closed of 1
- Cleanup errors: 0
- DingDongDitch-owned Chromium, Playwright, or Node processes after cleanup: 0

All browser work used DingDongDitch ExecutionPlans. No direct Playwright mouse
API, JavaScript injection, manual interaction, sign-in, search, or drag was
used. Production code and archived Google Earth experiments were not modified.
