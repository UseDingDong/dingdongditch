# Comparison Matrix

**Method:** Qualitative “succeeds / struggles” — **no subjective numeric scores**.  
**Empty cells mean UNKNOWN / not enough comparable evidence** — we do not invent.

Legend for cell text:
- **S** = generally succeeds / first-class
- **M** = mixed / possible with care
- **W** = recurrently struggles / out of design center
- **—** = not a primary concern / insufficient evidence in this reconnaissance

Rows are capability concerns. Columns are major frameworks.

---

## Matrix

| Concern | Playwright | Puppeteer | Selenium | CDP (raw) | Playwright MCP | Chrome DevTools MCP | Stagehand | Browser Use | Skyvern | Anthropic CU | OpenAI agent/CUA lineage |
|--------|------------|-----------|----------|-----------|----------------|---------------------|-----------|-------------|---------|--------------|---------------------------|
| **Reliability** | S for scripted tests with auto-wait; M on highly dynamic apps | M–S on Chromium scripts | M; more wait discipline required | W alone (no policy layer) | M; token/frame issues hurt | M for debug loops | S–M when cache/deterministic path; M on AI path | M; autonomy variance | M; vision helps hostile UI, cost/latency | W–M experimental | M productized but opaque |
| **Verification** | S assertions + traces | M (DIY asserts) | M | W | M tools exist (`verify_*`) but agent may skip | S observability | M schema extract helps; goal oracles weak | W–M loop-internal | M workflow checks vary | W action ACK ≠ goal | M HITL helps sensitive steps |
| **Recovery** | M retries/traces | M | M | W | M re-snapshot costly | M inspect then re-drive | M cache miss → LLM again | M replan; can loop badly | M product workflows | M re-screenshot | M product policies |
| **Dynamic DOM** | S locators/auto-wait | M–S | M | M if skilled | M a11y gaps | M | S–M v3 piercers | M | S vision fallback | M pixels | M |
| **Network inspection** | S | S | M (improving w/ BiDi/CDP) | S | S tools | S first-class | M via underlying | M depends build | M | W (pixels) | — hosted |
| **Authentication** | M storageState | M | M | M | M storage tools | M | W–M (2FA criticized) | W–M | S relative (2FA/CAPTCHA in scope) | W–M | M HITL login |
| **Session persistence** | S contexts/storageState | S | M | M | S claimed default | M | M | M / cloud profiles | M–S | M env-dependent | S managed |
| **Evidence collection** | S traces/video | M | M | M raw events | M trace/video tools | S DevTools | M | M screenshots/logs | M recordings | M screenshots | M product logs |
| **Replay** | S traces; codegen | M | M | W | M | — | S action cache replay | W nondeterministic | M code-gen replay | W | — |
| **Downloads** | S | S | M | M | M tools | M | M | M | M claimed | W–M OS dialogs | — |
| **Uploads** | S | S | M | M | S `file_upload` | M | M | M | M | M | — |
| **Multiple tabs** | S | S | M | M Target domain | S `browser_tabs` | M | M | M | M multi-tab hard flows | M window mgmt | — |
| **Cross-browser** | S | W Chrome-first | S breadth | W Chromium | S via Playwright | W Chrome | M Chromium-practical | W–M Chromium | W–M | OS/desktop not browsers | hosted Chrome |
| **Permission handling** | M APIs | M | M | M | M dialogs | M | M | M | M | M | M HITL |
| **Developer ergonomics** | S | S Node | M verbose | W low-level | S install; W cost | S for FE debug | S TS hybrid | S Python autonomy | M ops-oriented | W DIY sandbox | S consumer |
| **Debugging** | S trace viewer | M | M | M | M | S | M | W–M | M | W screenshot archaeology | M |
| **Performance** | S vs WebDriver | S | W slower | S raw | W token/latency | M | S when cached | W per-step LLM | W vision | W screenshot loop | M |
| **Vision dependence** | Low | Low | Low | None | Low default | Low | Low–M | M optional | High | High | High |
| **State tracking** | M contexts; not agent memory | M | M | DIY | M session; weak task state | M | M | M agent memory varies | M workflow state | W pixels only | M product |
| **Error recovery** | M | M | M | W | M | M | M | M–W loops | M | M | M |

---

## How to read this (important)

1. **Playwright “S” on reliability** means reliability *for its design center* (tests), not for open-ended agents.
2. **Skyvern “S” on auth** is *relative* to peers that ignore CAPTCHA/2FA — not absolute solved auth.
3. **CDP “S” on network** means capability exists, not that apps using raw CDP are reliable.
4. Cells marked from secondary surveys should be re-validated against primary docs during design.

## Source basis

See `../Evidence/SOURCE_INDEX.md` and competitor profiles. Matrix is a synthesis (**PATTERN** level), not a lab benchmark.
