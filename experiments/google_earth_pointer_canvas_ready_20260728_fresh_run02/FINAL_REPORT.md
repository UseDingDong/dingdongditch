# Google Earth canvas-readiness POINTER_MOVE benchmark

Verdict: **PASS**

- Google Earth URL: https://earth.google.com/web/
- Browser: fresh headed bundled Chromium 130.0.6723.31
- Navigation plan: `VERIFIED`
- Rendered readiness: verified 13.109 seconds after navigation
- Successful typed `POINTER_MOVE` operations: 9
- Materially distinct pointer positions: 9
- Screenshots: 16

## Readiness evidence

Readiness used no Search-field, button-role, or ordinary text-field target.

- Exact render surface: `canvas#earth-canvas`
- Canvas match count: 1
- Canvas visible: true
- Canvas bounds: approximately 1280.31 × 720.47 CSS pixels
- Loading splash no longer dominant: the top-toolbar bright-pixel ratio reached
  the loaded-interface threshold and remained stable.
- Stability: two loaded observations were separated by at least two seconds.
- Active rendering: the frame hashes differed and the rendered region changed
  by a mean 3.959 pixel levels between stable observations.
- Visual evidence: the readiness screenshot visibly shows the complete toolbar,
  globe, star field, controls, attribution, and scale—not the splash screen.

## Pointer results

Every pointer plan was `VERIFIED` and recorded its requested origin and
coordinates/element target, resolved coordinates, previous position, final
position, step count, viewport, verification result, and screenshot artifact.

1. Globe canvas center: `(640.1574, 360.2362)`, 12 steps
2. Upper-left: `(220, 140)`, 10 steps
3. Upper-right: `(1060, 140)`, 14 steps
4. Lower-right: `(1060, 590)`, 13 steps
5. Lower-left: `(220, 590)`, 15 steps
6. Center return: `(640, 360)`, 12 steps
7. Upper-middle: `(700, 180)`, 11 steps
8. Right-middle: `(1120, 390)`, 16 steps
9. Left-middle: `(360, 420)`, 14 steps

Playwright page screenshots do not include the operating-system cursor. The
screenshots therefore prove the loaded and progressively rendered globe state,
while the typed receipts provide authoritative pointer-position evidence.

## Cleanup

- Browser lifecycle: `stopped`
- Pages closed: 1 of 1
- Cleanup errors: 0
- Remaining DingDongDitch-owned Chromium, Playwright, pytest, Python benchmark,
  or Node processes: 0

All browser actions used DingDongDitch ExecutionPlans. No direct Playwright
mouse action, JavaScript interaction injection, manual interaction, sign-in,
drag, pointer-button press, search, or Mogadishu navigation occurred.
Production code and archived experiments were not modified.
