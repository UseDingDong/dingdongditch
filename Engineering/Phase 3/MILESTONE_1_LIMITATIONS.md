# Milestone 1 — Limitations

This milestone is a **thin proof**, not a product.

## Explicitly not built

| Limitation | Notes |
|------------|-------|
| Engines | Playwright-bundled Chromium + Firefox + WebKit; native Safari unsupported |
| Playwright only | No Selenium/Puppeteer/raw CDP public backend |
| Bundled channel only | chrome/msedge/brave channels not implemented |
| One operation / one action | Standalone API still single-op; Milestone 2 adds ordered plans of those ops |
| No multi-step *planning* | Plans are host-authored; runtime does not invent steps |
| No AI planning | Host supplies the plan |
| No autonomous recovery | Locate retry + expectation poll only |
| No cross-step state | No session workflow engine |
| No production-site testing | Local fixture only |
| Browser-visible evidence only | No external-world truth claims |
| Limited locators | test_id, role+name (+ name_match), css; host-declared constraints only |
| Limited expectations | url, exists, visible, in_viewport, text, attribute, network |
| HTML select only | `select_option` does not treat custom JS dropdowns as selects |
| No pixel / infinite scroll | `scroll_to_target` only; declared waits are a later milestone |
| No arbitrary sleep | `wait_for` is condition observation only; no fixed-duration sleep action |
| No compound waits | One condition per wait_for |
| No networkidle wait | Only `domcontentloaded` / `load` load_state values |
| Embed / YouTube / Vimeo media waits | `video_ended` is HTML5 `<video>` only (main doc or declared frame) |
| Adaptive plan timeout | Extends only for `video_ended` from finite HTML5 media facts; never exceeds `max_plan_timeout_ms` |
| Plan deadline ≠ action timeout | Longer plan deadline does not inflate ordinary `timeout_ms` |
| Nested iframe paths | One declared same-page iframe level only; see IFRAME_TARGETING.md |
| No popup / new-tab handling | Still out of scope |
| No MCP / cloud / UI / auth / billing | Per Milestone 1 scope |
| No concurrency / persistence / plugins | Deferred |
| No locator healing | No alternate strategies, ranking, or first-match |
| No positional index selection | Rejected; DOM order is unstable |
| Constraints need live semantics | Some sites still require explicit CSS after inspection |
| No visual / AI disambiguation | Host must declare constraints explicitly |
| No cross-run learning | Each operation is self-contained |

## Freshness policy limitations

- Uses local monotonic timestamps, not a browser freeze barrier  
- Does not stop page JS while the host “thinks” (G1 remains partially open)  
- Verification re-reads live state; max-age primarily rejects aged buffered signals and forbids pre-action proof reuse  
- Not a full observation-epoch protocol

## Network observation limitations

- Page-level response listener; not a full HAR/trace system  
- Matching is substring/method/status based  
- Service workers / cached responses may behave differently than naive expectations

## Ambiguity / missing targets

- Missing → `EXECUTION_FAILED` (`zero_after_primary` / `zero_after_constraints`)  
- Ambiguous after constraints → `EXECUTION_FAILED` (`multiple_after_*`)  
- Ambiguous / missing `within` container → `EXECUTION_FAILED`  
- No silent first-match policy  
- Structured `target_resolution` trace records candidate counts per stage  

See [`MILESTONE_1_TARGET_RESOLUTION_HARDENING.md`](./MILESTONE_1_TARGET_RESOLUTION_HARDENING.md).

## Epistemic boundary

A `VERIFIED` verdict means declared **browser-observable** expectations held under
freshness rules. It does **not** mean an external organization fulfilled a
real-world obligation (`SUCCESS_SEMANTICS.md` L8).

## What Milestone 1 does prove

DingDongDitch can consume one externally planned browser operation, execute it
through Playwright, evaluate fresh browser-visible evidence, and return an
honest attested receipt—without equating action completion with verified
outcome success.
