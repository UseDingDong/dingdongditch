# Experiment-only harness adjustments

- Created a fresh host harness for YouTube's live layout. No production runtime
  files were changed.
- The harness probes a small declared list of current and legacy YouTube CSS
  selectors using DingDongDitch's `inspect_target` interface.
- It chooses targets only when they resolve to exactly one visible element.
- If the home-page Shorts link does not resolve uniquely, the harness performs
  an explicit DingDongDitch navigation to `https://www.youtube.com/shorts`.
- All browser interactions are DingDongDitch `ExecutionPlan` operations. The
  harness does not invoke Playwright page actions directly.
- Fresh run 01 stopped after successful home navigation because the Windows
  console rejected Unicode from inspected YouTube text (`OSError 22`). Its
  evidence is preserved. Fresh run 02 uses JSON Unicode escapes only for live
  console output and has a wholly separate artifact root and browser session.
- The command monitor closed stdout for run 02, producing the same console-only
  failure even with escaped text. Run 03 is launched detached, preserves logs
  to files, and treats closed stdout as non-fatal. It has another new artifact
  root and browser session.
- Run 03 proved that the unique Shorts link navigates successfully, but this
  YouTube build did not expose the historical `ytd-reel-video-renderer`
  elements. Run 04 adds the unique page `body` as a renderer-agnostic
  `inspect_target` text fallback and declares URL expectations so successful
  navigation/advances produce verified receipts and screenshots.
- Run 04's screenshot showed YouTube's logged-out empty-feed notice: "Try
  searching to get started." Run 05 uses normal YouTube search for `#shorts`,
  inspects result-link candidates through DingDongDitch, and opens only a link
  that resolves uniquely by exact accessible name. This seeds the anonymous
  Shorts viewer without signing in or engaging with content.
