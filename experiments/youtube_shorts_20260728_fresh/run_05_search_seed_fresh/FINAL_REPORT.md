# YouTube Shorts via DingDongDitch — final report

## Outcome

Successful. A fresh, headed Playwright-bundled Chromium session used
DingDongDitch for all browser actions and read-only inspection. It navigated
from YouTube Home to Shorts, entered the viewer through a normal YouTube search
after the anonymous feed was empty, and executed nine verified Arrow Down
advances. At least five distinct Shorts were visibly reviewed.

Session: `9f658d6b-17ad-4eef-b6b9-547537df1117`

Configuration: Playwright / Chromium / bundled / headless=false.

No sign-in, likes, dislikes, comments, subscriptions, or advertisement
interactions were performed.

## Five evidence-backed observations

1. **“KINDNESS CHANGED HER WORLD ❤️‍🩹” — @RozreX**
   - Visible description/title: `KINDNESS CHANGED HER WORLD ❤️‍🩹`
   - Other visible context: search prompt “heartwarming homecoming proposal”;
     audio “Impostor Syndrome · Sidney Gish.”
   - Apparent topic: a heartwarming prom-date/kindness story.
   - Evidence: `screenshots/advance_short_3__step-0__arrow-down-3__after_success__796f02c7-1b21-4957-b3d8-eb60e4392c3c.png`

2. **“Walking On Water Prank!” — @StokesTwins**
   - Visible description/title: `Walking On Water Prank!`
   - Apparent topic: a staged illusion/prank involving walking on a lake.
   - Evidence: `screenshots/advance_short_5__step-0__arrow-down-5__after_success__796f02c7-1b21-4957-b3d8-eb60e4392c3c.png`

3. **Dance rehearsal/performance clip — @xlnow**
   - Visible description: `Lara saving her energy for the high kick–|| credits
     in description || ...`
   - On-video text contrasts “Practice” with how Lara saves energy for the
     actual performance.
   - Apparent topic: dance rehearsal humor/performance.
   - Evidence: `screenshots/advance_short_6__step-0__arrow-down-6__after_success__796f02c7-1b21-4957-b3d8-eb60e4392c3c.png`

4. **“The crash at the end wasnt planned ...” — @luca.dittrichmtb**
   - Visible description/title: `The crash at the end wasnt planned ...`
   - On-video text: `Riding down 467 Steps (Crash)`.
   - Apparent topic: first-person mountain-bike stunt/crash.
   - Evidence: `screenshots/advance_short_7__step-0__arrow-down-7__after_success__796f02c7-1b21-4957-b3d8-eb60e4392c3c.png`

5. **“The truest brotherly bond.” — @huangcc-666 and @AniAvocado-p5t**
   - Visible description: `The truest brotherly bond. ❤️ 🤝 #funny #shorts
     #prank #comedy`
   - Apparent topic: a family/brother prank or physical-comedy clip.
   - Evidence: `screenshots/advance_short_8__step-0__arrow-down-8__after_success__796f02c7-1b21-4957-b3d8-eb60e4392c3c.png`

## Variety

The sample covered heartwarming human-interest content, an illusion/prank,
dance/performance humor, an action-sports stunt, and family physical comedy.
That is broad topical variety, although the `#shorts` search seed biased the
sample toward high-engagement entertainment and prank content.

## Limitations and adaptations

- The brand-new logged-out Shorts feed initially displayed “Try searching to
  get started,” so it contained no recommendations. The harness used normal
  YouTube search for `#shorts`, resolved one result by an exact accessible
  name, and entered the Shorts viewer without signing in.
- YouTube's live custom-element layout differed from the historical selector.
  The harness probed declared selectors and used DingDongDitch's unique `body`
  inspection as a temporary fallback.
- After the viewer hydrated, some active renderer inspections returned empty
  text despite the content being visibly rendered. DingDongDitch screenshots
  therefore provide the authoritative title/channel/description evidence for
  later Shorts.
- The harness's conservative text-deduplication counter recorded only two text
  observations, but the receipts, changing Shorts URLs, nine verified advances,
  and preserved screenshots independently establish that at least five
  distinct Shorts were browsed and reviewed.

## Evidence index

- `receipts/`: 13 plan receipts (home, Shorts navigation, search seed, seed
  click, and nine verified advances)
- `screenshots/`: before/after success evidence, including every advance
- `inspections/`: selector probes and preserved inspected text
- `logs/run_history.json`: ordered run history
- `terminal_browser.json`: terminal browser identity and cleanup state
- `run_result.json`: raw harness result (including the conservative counter)
- `../../ADJUSTMENTS.md`: all experiment-only harness changes across fresh runs
