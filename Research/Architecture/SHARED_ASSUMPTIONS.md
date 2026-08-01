# Shared Architectural Assumptions

Only assumptions that **recur across multiple independent projects** are listed.  
Each item: assumption → where it appears → counter-signals → label.

---

## A1. The page is legible through one privileged observation channel

**Assumption:** Either the accessibility/DOM tree **or** screenshots are sufficient to decide the next action.

**Appears in:** Playwright MCP (a11y snapshots); Browser Use / Stagehand (DOM+a11y±vision); Skyvern / Anthropic / OpenAI CUA (vision); Magnitude (pixels).

**Counter-signals:** Canvas/WebGL UIs; unlabeled controls; a11y-hostile apps; screenshots missing modal timing; hybrid “structure default + vision fallback” becoming common. **EVIDENCE/PATTERN**

**Category:** browser verification / AI reasoning interface

---

## A2. Selectors or refs remain valid long enough to act

**Assumption:** Once an element is identified (CSS/XPath/ref/cached action), it can be acted on before identity invalidation.

**Appears in:** Playwright locators; Stagehand action cache; Playwright MCP refs; Selenium locators.

**Counter-signals:** SPA re-renders; virtualized lists; React key churn; iframe remounts; stale refs after navigation. **PATTERN**

**Category:** browser automation / dynamic DOM

---

## A3. Actionability equals readiness

**Assumption:** If the element is visible/stable/enabled, it is safe and meaningful to interact.

**Appears in:** Playwright auto-wait philosophy; many agent “click when visible” policies.

**Counter-signals:** Enabled button that triggers async work; optimistic UI; disabled-by-business-logic not reflected in DOM; overlays intercepting clicks. **FACT/PATTERN** (Playwright docs themselves distinguish actionability from app correctness)

**Category:** browser verification

---

## A4. Execution success equals task success

**Assumption:** A successful click/type/navigation (no exception) means the agent made progress toward the goal.

**Appears in:** Most agent loops that treat tool return “ok” as positive reward signal; computer-use click acknowledgements.

**Counter-signals:** Silent validation failures; wrong item clicked; CAPTCHA loops; navigated but logged out; download started but incomplete. **PATTERN** strongly evidenced across HN/agent writeups

**Category:** browser verification / AI reasoning

---

## A5. Browser state is reconstructible from cookies + storage (+ maybe URL)

**Assumption:** `storageState` / cookie jars / profiles can rehydrate “being logged in” and continue.

**Appears in:** Playwright storageState; Playwright MCP storage tools; hosted browser session products; Browserless guides.

**Counter-signals:** Device binding; short-lived tokens; fingerprint/IP binding; HttpOnly+rotation; 2FA step-up; bot scores on restored sessions. **EVIDENCE/PATTERN**

**Category:** authentication / session persistence

---

## A6. Navigation and page lifecycle are approximately deterministic

**Assumption:** goto → load → interact is a stable sequence; waits can make it reliable.

**Appears in:** Classic test frameworks; agent navigate tools.

**Counter-signals:** A/B experiments; client-side redirects; service workers; intermittent third-party scripts; geo/IP variance. **PATTERN**

**Category:** browser architecture / automation

---

## A7. The model can recover if it can see the page again

**Assumption:** Re-observing (snapshot/screenshot) after failure is sufficient recovery.

**Appears in:** MCP per-step snapshots; computer-use screenshot loops; Browser Use observe–act.

**Counter-signals:** Poisoned sessions (bot score escalations); irreversible submits; context window already full of junk; model loops on same failing action. **EVIDENCE/PATTERN**

**Category:** recovery / AI memory / AI reasoning

---

## A8. AI reasoning and browser execution belong in the same loop product

**Assumption:** The system that decides what to do should also be the system that owns browser semantics (or vice versa: one vendor ships both).

**Appears in:** Browser Use, Skyvern, Operator/ChatGPT Agent, Stagehand `agent()`, many “browser agent” startups.

**Counter-signals:** Playwright MCP / Chrome DevTools MCP / Stagehand-without-agent / code-mode tooling — all separate reasoning host from browser driver. **PATTERN** (field explicitly split into two shapes)

**Category:** integration glue / product architecture

---

## A9. Live browsers can be driven while the model thinks

**Assumption:** It is acceptable for JS timers, animations, and network responses to continue while the LLM is deliberating.

**Appears in:** Default Playwright/Puppeteer/agent setups.

**Counter-signals:** ABP and similar proposals freeze JS/render between turns specifically because stale-state is a dominant failure mode. **EVIDENCE** (HN Show HN claims)

**Category:** browser execution / state tracking

---

## A10. Hostile pages are still “just UI”

**Assumption:** Page content is data to parse, not an adversary controlling the agent.

**Appears in:** Most demos and benchmarks (benign sites).

**Counter-signals:** Indirect prompt injection growth reports 2025–2026; OWASP #1; vendor lockdown modes; arXiv production-agent papers urging programmatic boundaries. **EVIDENCE/PATTERN**

**Category:** browser permissions / security (often under-modeled as “safety”)

---

## A11. Screenshots are adequate evidence

**Assumption:** Capturing pixels (or a11y text) after an action is enough for humans/models to audit what happened.

**Appears in:** Computer use; many agents’ debug modes; RPA recordings.

**Counter-signals:** Need network waterfalls, console errors, dialog/download events, permission prompts — DevTools MCP popularity is a counter-signal that screenshots aren’t enough. **PATTERN**

**Category:** evidence collection / verification

---

## A12. Cross-browser differences are secondary

**Assumption:** Chromium behavior generalizes, or multi-browser is a checkbox.

**Appears in:** Most AI agents (Chromium-only in practice); Puppeteer; many cloud browser hosts.

**Counter-signals:** Playwright’s multi-engine investment; real engine differences in input/IME/PDF/downloads. **FACT/EVIDENCE**

**Category:** cross-browser behavior

---

## Assumptions we did **not** elevate (insufficient multi-project evidence yet)

- “Cached AI actions remain correct indefinitely” — Stagehand-centric; needs more cross-project evidence
- “Benchmarks predict production reliability” — actively contradicted (**PATTERN** of benchmark theater)
