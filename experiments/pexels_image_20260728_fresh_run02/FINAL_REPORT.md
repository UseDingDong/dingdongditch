# DingDongDitch real-world image download benchmark

Verdict: **PASS**

- Website: Pexels
- Source page: https://www.pexels.com/photo/landscape-photo-of-mountains-939714/
- Visible description: “Breathtaking view of snow-capped mountains, green meadows, and a clear blue sky”
- License indication observed: “Free to use”
- Download method: the visible “Free download” link, triggered by the declared DingDongDitch `DOWNLOAD` ExecutionPlan using `Alt+Enter`
- Browser: fresh headed bundled Chromium 130.0.6723.31
- Navigation plan: `VERIFIED`
- Download plan: `VERIFIED`
- Download lifecycle state: `completed`

## Artifact verification

- Filename: `pexels-mountain-landscape.jpg`
- Extension: `.jpg`
- Size: 3,369,681 bytes
- MIME: `image/jpeg`
- MIME evidence source: `content_signature`
- Content signature: JPEG `FF D8 FF`
- Receipt SHA-256: `8de0386a6111979bab9a6f6bc036e91f21c4fc0cc0ed50007f907e19ec70f66e`
- Independent SHA-256: `8de0386a6111979bab9a6f6bc036e91f21c4fc0cc0ed50007f907e19ec70f66e`
- Portable artifact path: `completed\pexels-mountain-landscape.jpg`
- Completed images: 1
- Staging files: 0
- Temporary/partial files: 0

## Cleanup

The browser lifecycle reached `stopped`, with the page recorded as `closed` and no cleanup errors. A post-run command-line process audit found zero DingDongDitch-owned Chromium, Playwright, or Node processes.

All browser navigation, cookie dismissal, inspection, and download execution occurred through DingDongDitch. No production code was modified, no JavaScript was injected, and no direct Playwright or manual browser actions were used.
