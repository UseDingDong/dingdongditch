# Ecosystem Map — Browser Automation & AI Browser Execution

**Label discipline:** FACT / EVIDENCE / PATTERN / SPECULATION / UNKNOWN  
**Snapshot date:** 2026-07-25

## Categories

| Category | Role in the stack | Examples |
|----------|-------------------|----------|
| Protocol / primitive | Browser instrumentation wire protocols | CDP, WebDriver, WebDriver BiDi |
| Classic automation libraries | Deterministic scripted control for testing & scraping | Playwright, Puppeteer, Selenium |
| AI-facing tool adapters | Expose browser control to existing agents | Playwright MCP, Chrome DevTools MCP, Playwright CLI |
| Hybrid AI+code SDKs | Mix deterministic code with AI primitives | Stagehand, HyperAgent |
| Autonomous browser agents | Own the perception–action loop | Browser Use, Skyvern, Magnitude, OpenAI/ChatGPT Agent, Gemini Computer Use / Mariner |
| Computer-use APIs | Vision + input primitives (often desktop-wide) | Anthropic Computer Use, OpenAI CUA-class models |
| Hosted browser infrastructure | Remote Chrome/runtime for agents | Browserbase, Hyperbrowser, Steel, Anchor, Bright Data, Cloudflare Browser Run |
| Adjacent / second tier | Smaller communities, niches | Notte, LaVague, Agent-E, Nanobrowser, Browserable, Agent-TARS, ABP, Obscura |

---

## Protocol layer

### Chrome DevTools Protocol (CDP)

| Field | Content |
|-------|---------|
| **Purpose** | Instrument, inspect, debug, and profile Chromium/Blink browsers (FACT: official DevTools Protocol docs) |
| **Architecture** | JSON-RPC over WebSocket; domains (Page, DOM, Network, Runtime, Input, Target, Accessibility, …); attach to Targets (pages, workers, iframes) to get session IDs (FACT) |
| **Primary audience** | Browser tooling authors, DevTools, automation libraries |
| **Core design philosophy** | Expose browser internals as command/event domains rather than a high-level user API |
| **Strengths** | Event-driven; deep network/DOM/runtime control; foundation for Puppeteer/Playwright Chromium path (FACT/EVIDENCE) |
| **Weaknesses** | Chromium-centric; experimental domains change; low-level & verbose; enabling domains (e.g. Runtime) has detectable side effects (EVIDENCE: detection research) |
| **Adoption** | De facto substrate for modern Chromium automation (PATTERN) |
| **Relationship to AI agents** | Almost all AI browser stacks eventually speak CDP (or wrap something that does) (PATTERN) |

### W3C WebDriver (+ BiDi)

| Field | Content |
|-------|---------|
| **Purpose** | Standardized cross-browser automation protocol (FACT) |
| **Architecture** | Historically HTTP request/response via driver binaries; BiDi adds bidirectional capabilities (FACT) |
| **Primary audience** | Cross-browser QA, enterprise Selenium stacks |
| **Core design philosophy** | Vendor-neutral wire protocol; portability over deep engine access |
| **Strengths** | Broadest language/browser matrix historically (EVIDENCE) |
| **Weaknesses** | Extra hop latency; historically weaker event streaming; automation fingerprints via drivers (EVIDENCE) |
| **Adoption** | Entrenched in enterprise; losing greenfield mindshare to CDP-based tools (EVIDENCE/PATTERN) |
| **Relationship to AI agents** | Rarely the preferred AI substrate; Selenium 4 can still reach CDP features on Chromium (FACT/EVIDENCE) |

---

## Classic automation libraries

### Playwright (Microsoft)

| Field | Content |
|-------|---------|
| **Purpose** | Reliable end-to-end testing and browser automation across Chromium, Firefox, WebKit (FACT: playwright.dev) |
| **Architecture** | Library talks to browsers via CDP (Chromium) and engine-specific protocols (Firefox/WebKit); auto-waiting actionability; browser contexts; tracing (FACT) |
| **Primary audience** | QA engineers, full-stack developers, CI teams |
| **Core design philosophy** | Make flaky tests rare by auto-waiting for actionability; first-class tooling (trace viewer, codegen) |
| **Strengths** | Auto-wait, multi-browser, network interception, storageState, traces, strong docs (FACT/EVIDENCE) |
| **Weaknesses** | Designed for *tests*, not open-ended agent tasks; still flakes on dynamic apps; detectable automation surface (EVIDENCE) |
| **Adoption** | Dominant modern E2E framework in many stacks (EVIDENCE from 2025–2026 comparisons) |
| **Relationship to AI agents** | Substrate for Stagehand (historically), Playwright MCP, many agent wrappers; also escape hatch when MCP is too costly (EVIDENCE: HN) |

### Puppeteer (Chrome DevTools team / Google)

| Field | Content |
|-------|---------|
| **Purpose** | High-level Node API to control Chrome/Chromium via CDP (FACT) |
| **Architecture** | Direct CDP WebSocket; Chromium-first (FACT) |
| **Primary audience** | Node developers, scraping, Chrome-centric automation |
| **Core design philosophy** | Thin, CDP-faithful control of Chromium |
| **Strengths** | Low latency; deep Chrome features; Locator auto-wait improvements (EVIDENCE) |
| **Weaknesses** | Weak multi-browser story vs Playwright; still a scripting library, not an agent runtime (FACT/PATTERN) |
| **Adoption** | Mature, widely used; often compared as Playwright’s Chromium sibling (EVIDENCE) |
| **Relationship to AI agents** | Used under Chrome DevTools MCP / agent tooling; less often the “agent product” surface (EVIDENCE) |

### Selenium

| Field | Content |
|-------|---------|
| **Purpose** | Cross-language, cross-browser UI automation via WebDriver (FACT) |
| **Architecture** | Client → WebDriver protocol → browser driver → browser (FACT) |
| **Primary audience** | Enterprise QA, polyglot teams, legacy suites |
| **Core design philosophy** | Standards and reach over deep browser intimacy |
| **Strengths** | Language/browser breadth; institutional inertia (EVIDENCE) |
| **Weaknesses** | Slower; more explicit waits; historically flakier; stronger detection surface via drivers (EVIDENCE) |
| **Adoption** | Still large installed base; fewer new AI-agent foundations (PATTERN) |
| **Relationship to AI agents** | Occasionally wrapped; rarely the preferred AI execution layer in 2026 surveys (EVIDENCE) |

---

## AI-facing tool adapters

### Playwright MCP (`@playwright/mcp`)

| Field | Content |
|-------|---------|
| **Purpose** | Expose Playwright browser automation to MCP clients via accessibility snapshots (FACT: playwright.dev/mcp) |
| **Architecture** | MCP server → Playwright → browser; snapshot returns a11y tree with refs; tools for navigate/click/type/network/storage/tracing (FACT) |
| **Primary audience** | Coding agents & chat clients (Cursor, Claude Code, VS Code, etc.) |
| **Core design philosophy** | Structure over pixels; deterministic refs; no vision required by default (FACT) |
| **Strengths** | Cross-browser; rich tool surface; persistent sessions; pairs with screenshots as fallback (FACT) |
| **Weaknesses** | Context/token bloat; reported flakiness on frames/edge cases; MCP tool schemas costly (EVIDENCE: HN, technical blogs) |
| **Adoption** | Default “give my coding agent a browser” choice in many 2026 guides (EVIDENCE) |
| **Relationship to AI agents** | Tooling, not an autonomous agent — your model owns the loop (FACT) |

### Playwright CLI (+ skills)

| Field | Content |
|-------|---------|
| **Purpose** | Shell/code-execution oriented browser control for coding agents (FACT: Microsoft docs) |
| **Architecture** | Agent runs CLI commands; snapshots written to disk rather than always injected into LLM context (EVIDENCE: Microsoft comparison + independent token analyses) |
| **Primary audience** | Coding agents working in large codebases |
| **Core design philosophy** | Reduce token cost by inverting who holds page state (EVIDENCE) |
| **Strengths** | Reported large token savings vs MCP (~4× in published analyses) (EVIDENCE) |
| **Weaknesses** | Less self-correcting mid-flow than snapshot-every-step MCP; needs anticipated scripting (EVIDENCE/SPECULATION mix — see Evidence ledger) |
| **Adoption** | Growing as Microsoft’s recommended path for coding agents (EVIDENCE) |
| **Relationship to AI agents** | Same family as MCP; different transport of state into the model (FACT) |

### Chrome DevTools MCP / Chrome DevTools for agents

| Field | Content |
|-------|---------|
| **Purpose** | Give coding agents live Chrome control + DevTools inspection (network, console, performance) (FACT: developer.chrome.com) |
| **Architecture** | MCP server (+ CLI + agent skills) over Chrome/Puppeteer-class control (FACT) |
| **Primary audience** | Frontend debugging by coding agents |
| **Core design philosophy** | Driving vs debugging split — Playwright MCP drives; DevTools MCP inspects (EVIDENCE: multiple 2026 surveys) |
| **Strengths** | First-party Google tooling; deep observability (FACT/EVIDENCE) |
| **Weaknesses** | Chrome-centric; not a full autonomous workflow engine (PATTERN) |
| **Adoption** | Rapidly becoming standard companion to Playwright MCP (EVIDENCE) |
| **Relationship to AI agents** | Tooling for existing agents |

---

## Hybrid AI + code SDKs

### Stagehand (Browserbase)

| Field | Content |
|-------|---------|
| **Purpose** | Code-first browser automation with AI primitives (`act`, `extract`, `observe`, optional `agent`) (EVIDENCE: docs & comparisons) |
| **Architecture** | Historically Playwright-based; v3 reported to use native CDP (“dropped Playwright”) for speed and deeper DOM/iframe/shadow support (EVIDENCE: Browserbase/engineering blogs — verify against current source when designing) |
| **Primary audience** | TypeScript engineers maintaining production automations |
| **Core design philosophy** | Deterministic where possible; AI only at brittle joints; cache successful actions to skip LLM on replay (EVIDENCE) |
| **Strengths** | Action caching; schema-validated extract; hybrid control (EVIDENCE) |
| **Weaknesses** | TS-centric; iframe/shadow historically painful (issues); still depends on LLM quality when AI path used (EVIDENCE) |
| **Adoption** | ~20k+ GitHub stars cited in mid-2026 secondary sources (EVIDENCE — approximate) |
| **Relationship to AI agents** | Tooling that can become an agent via `agent()` primitive (PATTERN of blurred categories) |

---

## Autonomous browser agents

### Browser Use

| Field | Content |
|-------|---------|
| **Purpose** | Autonomous Python browser agent: task in → perception–action loop → result (EVIDENCE) |
| **Architecture** | Originally Playwright; 2026 reports of migration to direct CDP + event-driven watchdogs; model-agnostic LLM wiring (EVIDENCE) |
| **Primary audience** | Python teams wanting task-level autonomy |
| **Core design philosophy** | Maximum convenience autonomy; model calls per step (EVIDENCE) |
| **Strengths** | Ecosystem default / breakout adoption; flexible (EVIDENCE: ~85k–98k stars cited — approximate) |
| **Weaknesses** | Cost per step; nondeterminism; loops on CAPTCHA/challenges; harder to debug than scripted flows (EVIDENCE) |
| **Adoption** | Highest OSS visibility among browser agents in 2026 surveys (EVIDENCE) |
| **Relationship to AI agents** | It *is* the agent product shape |

### Skyvern

| Field | Content |
|-------|---------|
| **Purpose** | Vision+LLM workflow automation aimed at RPA replacement (forms, portals, CAPTCHA/2FA) (EVIDENCE) |
| **Architecture** | Vision-first grounding; workflow builder; code-gen mode to emit Playwright to cut vision cost; AGPL + commercial (EVIDENCE) |
| **Primary audience** | Operations / business process automation |
| **Core design philosophy** | Survive hostile/legacy UIs where DOM selectors fail; include auth friction in product scope (EVIDENCE) |
| **Strengths** | CAPTCHA/2FA/proxy story; self-host or cloud (EVIDENCE) |
| **Weaknesses** | Vision cost/latency; open-source license constraints (AGPL); still fails hard live-site writes at scale (EVIDENCE: harder benchmarks) |
| **Adoption** | ~20k+ stars cited; strong Reddit mindshare for hard portals (EVIDENCE) |
| **Relationship to AI agents** | Browser agent + APA platform; also MCP wrapper |

### Magnitude / Notte / HyperAgent / second tier

Documented lightly in Evidence; not full peers in adoption. See `Competitors/SECOND_TIER.md`.

---

## Computer-use / foundation-model tooling

### Anthropic Computer Use

| Field | Content |
|-------|---------|
| **Purpose** | API tool letting Claude operate a computer via screenshots + mouse/keyboard (FACT: Anthropic docs/news) |
| **Architecture** | Model returns tool actions; *developer* implements sandbox (Xvfb desktop), screenshot loop, action execution (FACT) |
| **Primary audience** | Developers embedding desktop/browser agents |
| **Core design philosophy** | Human-like GUI control; pixels as ground truth; experimental/error-prone by vendor admission (FACT) |
| **Strengths** | Desktop breadth beyond web; developer-owned loop (FACT) |
| **Weaknesses** | Latency; scrolling/drag/zoom hard; screenshot token cost; coordinate mapping pitfalls; safety risks (FACT/EVIDENCE) |
| **Adoption** | Widely referenced primitive; not a turnkey browser product (PATTERN) |
| **Relationship to AI agents** | Perception/action API; execution environment is separate |

### OpenAI browser / computer-use lineage (Operator → ChatGPT Agent / CUA)

| Field | Content |
|-------|---------|
| **Purpose** | Managed agentic browsing / computer-using agent experiences (EVIDENCE: product history through 2025–2026) |
| **Architecture** | Historically server-side managed virtual browser; human-in-the-loop for sensitive actions; later merged into broader ChatGPT Agent mode combining visual browser + text browser + terminal (EVIDENCE — product details shift; re-verify before citing specifics) |
| **Primary audience** | End users and teams wanting packaged agent, not DIY control plane |
| **Core design philosophy** | Productized safety + hosted runtime over DIY orchestration |
| **Strengths** | Lower setup; built-in gates; polished UX (EVIDENCE) |
| **Weaknesses** | Less hackable; vendor lock-in; web-focused historically vs full desktop (EVIDENCE) |
| **Adoption** | High consumer awareness; API/developer surface less open than Anthropic’s DIY model historically (EVIDENCE) |
| **Relationship to AI agents** | Closed product agent, not a universal execution layer |

### Google Project Mariner / Gemini Computer Use

| Field | Content |
|-------|---------|
| **Purpose** | Foundation-model browser/computer use variants (EVIDENCE: industry surveys) |
| **Architecture** | Vendor-specific; less OSS-hackable (EVIDENCE) |
| **Notes** | Track as competitive agents; not open infrastructure (PATTERN) |

---

## Hosted browser infrastructure (execution hosts)

Not “agents,” but shape reliability:

| Provider | Noted strengths (EVIDENCE from May 2026 surveys) |
|----------|--------------------------------------------------|
| Browserbase | Production default; Stagehand home court; Model Gateway |
| Hyperbrowser | Stealth, concurrency, CAPTCHA |
| Steel.dev | OSS-friendly, leaderboard host |
| Anchor Browser | Login-handling reputation |
| Cloudflare Browser Run | Cheap at small scale on Workers |
| Bright Data Agent Browser | Enterprise proxy+CAPTCHA |

**PATTERN:** Framework choice often matters less than *where Chrome runs* and *what credentials attach*.

---

## Related experimental approaches (watchlist)

| Project | Claim (treat carefully) | Why it matters to us |
|---------|-------------------------|----------------------|
| Agent Browser Protocol (ABP) | Freeze JS/render between agent steps; bundle events with state (EVIDENCE: HN Show HN) | Challenges “live mutating page while model thinks” assumption |
| Obscura | Automation-first Rust headless browser with CDP compatibility (EVIDENCE: secondary blog) | Challenges “always strip Chromium” assumption |
| Code-mode / scan-then-script | Catalog elements; model writes short sandboxed scripts (EVIDENCE: browsemode thesis) | Challenges per-step tool-call MCP shape |

See Open Questions for verification needs.
