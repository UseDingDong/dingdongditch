# Google Earth loading diagnostic

## Conclusion

Most likely root cause: **readiness detection**, not a Google Earth loading
failure.

Google Earth did not remain on its splash screen. The first timed screenshot at
6.531 seconds shows the splash, while the second at 13.703 seconds shows the
fully rendered Earth interface and an in-product modal. The globe and controls
remain visibly rendered through the final 60.015-second screenshot.

The failed benchmark looked for an accessible button named `Search`. This
Google Earth build renders its UI through Flutter/Canvas and, without an
accessibility activation interaction, exposes only a visible
`flt-semantics-placeholder` labelled `Enable accessibility`. The visible Search
field is therefore not present as a discoverable role/button target even after
the application is ready.

## Evidence by suspected cause

### WebGL / GPU: not the cause

- WebGL available: yes
- WebGL 2: yes
- Renderer: hardware-backed ANGLE on AMD Radeon Graphics
- Backend: Direct3D 11, shader model 5.0
- Maximum texture size: 16,384
- GPU process crash count: 0
- Reported Earth rendering rate: approximately 55–58 FPS
- A non-fatal `WebGL: INVALID_ENUM` warning occurred once.
- A `No available adapters` warning refers to an unavailable adapter path, but
  Earth successfully used its WebGL/D3D11 renderer.

### Browser configuration: not the cause

- Headed bundled Chromium 130.0.6723.31 launched normally.
- Secure context and cross-origin isolation were active.
- WebAssembly, SharedArrayBuffer, OffscreenCanvas, WebGPU API exposure, and
  WebGL 2 were present.
- Earth initialized its threaded WASM renderer and emitted normal rendering
  telemetry.

### Network / resource loading: not the cause

- Navigation completed without error in 4.031 seconds.
- `main.dart.js` loaded in approximately 1.133 seconds.
- `earthplugin_web.wasm` loaded in approximately 1.343 seconds.
- There were no failed core Earth application requests.
- All 20 request-failure events were aborted Google Analytics fetches.
- HTTP errors were two unauthenticated user-quota requests (`401`) and one
  optional feedback-survey request (`429`). They did not prevent rendering.

### JavaScript / Google Earth initialization: not the cause

- Uncaught JavaScript errors: 0
- Firebase initialized.
- Startup connectivity reported Wi-Fi.
- Earth reported WASM and threaded-WASM operation, loaded scene/KML data, and
  continuously emitted frame-rate telemetry.
- The changing camera longitude in the URL and visibly changing globe frames
  demonstrate an active render loop.

### DOM and accessibility behavior: confirmed cause of false timeout

- The document reached `readyState=complete`.
- The DOM stabilized at 89 nodes and one canvas after approximately 15 seconds.
- Body text remained empty because the visible UI was canvas-rendered.
- The only visible ARIA-labelled DOM element in every sample was
  `Enable accessibility`.
- Consequently, an exact role/button lookup for `Search` remained at zero
  matches even while the Search field was visibly rendered.

## Timing

- 4.031 s: navigation completed
- 6.531 s: first sample, splash still visible
- 9.390 s: Earth reported startup connectivity
- 10.453 s: renderer emitted its WebGL warning
- 13.703 s: complete globe UI visibly rendered
- ~15 s: DOM structure stabilized
- 60.015 s: final sample still showed the active complete Earth UI

## Artifacts

- 12 screenshots at five-second targets
- 12 timestamped DOM snapshots
- Final DOM snapshot
- Console log
- JavaScript-error log
- Failed-request log
- HTTP-error-response log
- Performance/resource log
- GPU and feature-support diagnostics
- Terminal browser lifecycle evidence

The one-shot diagnostic ended normally. The browser lifecycle reached
`stopped`, the page was closed, cleanup errors were empty, and zero
DingDongDitch-owned Chromium, Playwright, or Node processes remained.

No production code was modified, no workaround was implemented, and the
diagnostic was not retried.
