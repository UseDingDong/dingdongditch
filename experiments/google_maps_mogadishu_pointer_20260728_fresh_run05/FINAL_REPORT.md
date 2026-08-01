# Google Maps POINTER_MOVE Benchmark

Verdict: **PASS**

- Google Maps entry URL: `https://maps.google.com`
- Final URL: Google Maps place page for Mogadishu, Somalia
- Interface readiness: **6,500 ms** after navigation
- Navigation plan: **VERIFIED**
- Interface evidence: unique visible search field and visible zoom controls; two
  rendered map-tile screenshots separated by 2,022 ms; non-white map ratio
  0.3434; 151 quantized colors; loading overlay absent
- POINTER_MOVE operations: **6 / 6 VERIFIED**
- Targets: viewport center, search box, map area, zoom-in control, zoom-out
  control, map center
- Search query: `Mogadishu, Somalia`
- Search fill plan: **VERIFIED**
- Search submit plan: **VERIFIED**
- Final-location plan: **VERIFIED**
- Final visible location: **Mogadishu, Somalia**
- Screenshots: **15**
- Receipts: **15**
- Inspections: **5**
- Browser cleanup: lifecycle `stopped`; no cleanup errors
- Remaining DingDongDitch-owned Chromium, Playwright, Node, Python, or pytest
  processes: **0**

The final screenshot visibly shows the Mogadishu place panel, the country label
Somalia, and the map centered on Mogadishu. Playwright page screenshots do not
capture the operating-system cursor. Pointer movement is therefore evidenced by
the typed receipts, which record requested target, resolved coordinates,
previous position, final position, step count, viewport, screenshots, and a
successful position-verification result for every move.

Evidence:

- `run_result.json`: authoritative benchmark summary and pointer evidence
- `terminal_browser.json`: browser lifecycle and cleanup evidence
- `receipts/`: all typed plan and operation receipts
- `screenshots/`: readiness, pointer, search, and final-location screenshots
- `inspections/`: search/control readiness and final visible text
- `logs/run_history.json`: ordered run history
- `logs/readiness_observations.json`: map-render readiness measurements
