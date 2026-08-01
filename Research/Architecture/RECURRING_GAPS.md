# Recurring Gaps (Ecosystem-Wide)

These are problems that appear across **multiple independent projects**, not single-vendor bugs.  
No solutions proposed — gap statements only.

---

## G1. Observation/action desynchronization

**Gap:** Models often act on stale or incomplete state because the page mutates during deliberation, between snapshot and action, or across frames the observer didn’t include.

**Seen in:** Playwright MCP complaints; ABP’s motivating failure list (modals, autocomplete overlays, dynamic reflow); classic Playwright flake patterns; computer-use latency windows.

**Belongs to:** browser execution + state tracking (+ AI reasoning timing)

---

## G2. Verification is underspecified

**Gap:** Systems verify that an *action executed*, not that the *user goal* advanced. Few stacks have a first-class, composable “task-level oracle” separate from tool exceptions.

**Seen in:** Playwright auto-wait limits; agent loops treating tool success as progress; computer-use click ACKs; Stagehand/Browser Use production caveats (“verify after consequential actions”).

**Belongs to:** browser verification

---

## G3. Auth, step-up, and bot challenges are outside the happy path

**Gap:** Login, 2FA, CAPTCHA/Turnstile, and risk scoring are the real workflow — yet most architectures treat them as interruptions to an otherwise normal DOM loop.

**Seen in:** Skyvern differentiating on CAPTCHA/2FA; Browser Use Turnstile loops; Browserless/session guides; social-platform auth notes requiring human handoff; Stagehand login+2FA criticism.

**Belongs to:** authentication + browser permissions + AI reasoning (loop policy)

---

## G4. Context/cost explosion when making pages legible to LLMs

**Gap:** Faithful page state is large. Shipping it through LLM context (MCP snapshots, screenshots, DOM dumps) burns tokens and buries signal; omitting it blinds recovery.

**Seen in:** Playwright MCP vs CLI token analyses; Anthropic “code execution with MCP” general argument; HN “Playwright MCP unusable?”; computer-use screenshot costs.

**Belongs to:** integration glue + AI memory

---

## G5. Frame, shadow, and cross-origin boundaries break grounding

**Gap:** Real apps put critical UI in iframes, shadow roots, and OOPIFs. Flat “root DOM / single a11y tree” mental models fail repeatedly.

**Seen in:** Stagehand iframe engineering posts & issues; HN claim Playwright MCP frame piercing gaps; CDP node ID non-uniqueness across frames; Selenium/Playwright frameLocator complexity.

**Belongs to:** browser architecture + dynamic DOM handling

---

## G6. Recovery policies are ad hoc

**Gap:** Retries, backoff, human handoff, session reset, and “stop digging” on challenge pages are reinvented per project — often after damage (escalated bot score, duplicate purchases).

**Seen in:** CAPTCHA-loop articles; Playwright retries-as-mask; agent runaway loops; production safety blogs urging stop rules.

**Belongs to:** error recovery

---

## G7. Evidence packs are incomplete for postmortems

**Gap:** Many agents keep screenshots or traces *or* network *or* console — rarely a bundled, goal-linked evidence artifact that answers “what did the browser believe happened?”

**Seen in:** Playwright trace viewer excellence vs agent underuse; DevTools MCP rising to fill observability hole; download/dialog events missing from many agent observations (ABP motivation).

**Belongs to:** evidence collection / debugging

---

## G8. Security boundaries lag capability

**Gap:** Agents operate with user sessions on untrusted HTML. Programmatic allowlists/human gates exist unevenly; LLM self-policing is insufficient per 2026 threat reports.

**Seen in:** Prompt injection wild reports; OWASP AI #1; vendor lockdown modes; AgentsCamp “shared tax” warning across all four postures.

**Belongs to:** browser permissions / integration glue

---

## G9. Benchmarks diverge from production hardness

**Gap:** Leaderboards on saturated read-oriented suites do not predict live authenticated write workflows.

**Seen in:** WebVoyager saturation commentary; ClawBench/~30% live write; Illusion of Progress paper citations; vendor score vs field honesty posts.

**Belongs to:** something else (evaluation / incentives) — still shapes engineering false confidence

---

## G10. “Who owns the control loop” is unresolved in product architecture

**Gap:** The ecosystem keeps re-merging and re-splitting agent-vs-tooling, leaving no stable universal execution layer that any AI can drive with consistent semantics.

**Seen in:** Explicit two-shapes taxonomy; Stagehand/Browser Use dual marketing; MCP vs framework wars; code-mode rebellion against MCP verb flattening.

**Belongs to:** integration glue — **central to this project’s mission space** (observation only; no design here)
