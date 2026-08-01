# Reconnaissance Report — Universal Browser Execution Layer Opportunity Space

**Date:** 2026-07-25  
**Classification of content:** Institutional knowledge for a future open-source infrastructure project  
**Explicit non-goals of this document:** product design, feature invention, solution proposals

This report is the narrative spine. Detailed profiles live under `Research/` subfolders. Prefer updating those leaves over bloating this file.

---

# Epistemic legend

| Tag | Meaning |
|-----|---------|
| **Established facts** | Primary docs / protocol reality |
| **Evidence** | Cited secondary sources, issues, discussions |
| **Observed patterns** | Cross-project regularities |
| **Speculation** | Plausible but weakly supported |
| **Unknowns** | Explicit open questions |

---

# PART 1 — Ecosystem map

## Established facts

- Browser automation rests primarily on **CDP** (Chromium) and **WebDriver** (cross-browser standard), with **WebDriver BiDi** evolving.
- **Playwright**, **Puppeteer**, and **Selenium** are the dominant classic libraries, differing mainly by protocol path and auto-wait philosophy.
- **Playwright MCP** exposes Playwright to agents via **accessibility snapshots + refs**, with optional screenshots.
- **Anthropic Computer Use** is a **developer-implemented** screenshot/mouse/keyboard loop around a sandboxed desktop.
- **Chrome DevTools for agents** provides MCP/CLI access to live Chrome inspection and control.

## Evidence

- 2026 field surveys split the market into **browser agents** (vendor owns loop) vs **tooling for agents** (host agent owns loop), with four common postures: autonomous (Browser Use), code-hybrid (Stagehand), workflow/RPA (Skyvern), MCP tools (Playwright MCP / Chrome DevTools MCP).
- Browser Use is the breakout OSS autonomous agent; Stagehand is the leading TS hybrid with action caching; Skyvern differentiates on vision + CAPTCHA/2FA.
- OpenAI’s Operator was merged into broader ChatGPT Agent experiences (product details churn — re-verify).
- Hosted browser infra (Browserbase, Hyperbrowser, Steel, Anchor, Cloudflare, Bright Data) is where much operational money sits.

## Observed patterns

- Nearly all AI browser stacks are skins over CDP-class control plus an observation strategy (DOM/a11y, vision, or hybrid).
- Categories blur: tools ship `agent()` modes; agents expose primitives.
- Coding agents often want **drive + debug** (Playwright MCP + DevTools MCP), not a new autonomous product.

## Speculation

- Long-term differentiation may accrue to whoever owns **verification, synchronization, recovery, and trust boundaries**, not who wraps CDP next.

## Unknowns

- Exact current Stagehand/Browser Use internal drivers; OpenAI public API surface; independent star metrics — see `Open Questions/`.

**Canonical detail:** `Competitors/ECOSYSTEM_MAP.md` and per-project files.

---

# PART 2 — Failure analysis

## Established facts

- Playwright actionability waits for DOM interaction readiness, not application correctness.
- Computer use vendors document gesture/latency limitations.
- Auth systems and bot challenges exist as first-class web security mechanisms.

## Evidence

Fifteen recurring failure classes are cataloged in `Failure Analysis/RECURRING_ISSUES.md`, including: timing races, stale observation, selector invalidation, iframe/shadow blindness, a11y insufficiency, MCP token exhaustion, auth fragility, CAPTCHA loops, transport detection, false progress, dialog/download blindness, multi-tab loss, coordinate fragility, prompt injection, storageState poisoning.

## Observed patterns

- “AI dumb” failures often = stale/partial observation + weak verification.
- “Flaky automation” failures often = timing + selectors + frames.
- “Can’t do real work” failures often = auth + challenges + security policy.

## Speculation

- Freeze-between-turns protocols may reduce a large stale-state subclass but may break timer-dependent apps (unproven at scale).

## Unknowns

- Quantitative mix of failure classes on a fixed task suite (Q9).

---

# PART 3 — Comparison matrix

See `Architecture/COMPARISON_MATRIX.md`.

**Method note (important):** Cells are qualitative succeed/struggle statements relative to each project’s design center — **not scores**. Empty/weak cells remain UNKNOWN rather than filled with guesses.

**Headline pattern:** Classic libraries win scripted reliability and network/evidence tooling; MCP adapters win agent integration but lose on tokens; autonomous agents win improvisation but lose determinism; vision agents win hostile UI but lose cost; computer-use APIs win generality but lose web-structured reliability.

---

# PART 4 — Shared assumptions

See `Architecture/SHARED_ASSUMPTIONS.md`.

Recurring assumptions across independent projects include:

1. One observation channel is enough  
2. Selectors/refs stay valid long enough to act  
3. Actionability equals readiness  
4. Execution success equals task success  
5. Sessions reconstruct from storage/cookies  
6. Navigation is roughly deterministic  
7. Re-observation enables recovery  
8. Reasoning and execution belong in one product loop  
9. Live pages can run while models think  
10. Pages are data, not adversaries  
11. Screenshots suffice as evidence  
12. Cross-browser is secondary  

Each has documented counter-signals.

---

# PART 5 — Recurring gaps

See `Architecture/RECURRING_GAPS.md`.

Ecosystem-wide gaps (not single-vendor bugs):

1. Observation/action desynchronization  
2. Underspecified verification  
3. Auth/challenges outside happy path  
4. Context/cost explosion for page legibility  
5. Frame/shadow/cross-origin grounding failures  
6. Ad hoc recovery without stop conditions  
7. Incomplete evidence packs  
8. Security boundaries lag capability  
9. Benchmarks diverge from production hardness  
10. Unstable ownership of the control loop / missing universal execution semantics  

**Mission alignment (observation only):** Gaps 1, 2, 6, 7, and 10 sit closest to “universal execution layer” language in the mission brief — without proposing a product.

---

# PART 6 — Lessons learned

See `Lessons Learned/LESSONS_INDEX.md` (L01–L15).

These are permanent engineering knowledge entries with evidence and anti-patterns. Do not collapse them into slogans during design.

---

# PART 7 — Knowledge archive

Created at repository root:

```
Research/
  README.md
  RECONNAISSANCE_REPORT.md          ← this file
  Competitors/                      ← ecosystem + per-project dossiers
  Architecture/                     ← assumptions, gaps, matrix, stack layers
  Failure Analysis/                 ← recurring issues
  Lessons Learned/                  ← L01–L15
  Evidence/                         ← source index + benchmark caveats
  Developer Feedback/               ← HN/GitHub/survey clusters
  Open Questions/                   ← Q1–Q17 + process debts
```

**Maintenance rule:** New discoveries become leaf documents with epistemic tags. Update the index in `Research/README.md`. Do not let findings die in chat transcripts.

---

# Cross-cutting synthesis (clearly labeled)

## Established facts

- CDP/WebDriver exist; higher layers wrap them.
- Accessibility trees and screenshots are different lossy projections of UI.
- MCP can expose browser tools to many hosts.
- Auth, permissions, and challenges are real browser/web security features.

## Evidence

- Practitioner dissatisfaction concentrates on tokens, frames, auth, flakiness, and weak debug — not on lack of yet another chat agent.
- Hybrid determinism (cache/code-gen/scripts) repeatedly appears as the production coping strategy.
- Security/injection concerns escalated in 2025–2026 reporting.

## Observed patterns

- Models change; engines change; the fragile middle is observation sync, verification, recovery, and privilege separation.
- Competing “AI browser agents” often share substrates and diverge on posture and packaging.

## Speculation

- There may be room for infrastructure that any agent can call with stronger execution semantics than today’s MCP verb bags or autonomous loops — **existence of opportunity is not proven**; this reconnaissance only maps pains and assumptions.

## Unknowns

- Whether a clean universal layer can be built without becoming “just another agent” or “just another Playwright wrapper.”
- Quantitative prioritization of gaps pending labeled failure studies.
- Legal/policy envelope for challenge handling.

---

# Recommended next research steps (still reconnaissance, not design)

1. Source-audit Stagehand v3 and Browser Use driver code (Q1–Q2)  
2. Primary-read security papers and threat reports cited secondarily (L11)  
3. Build a private, authenticated, write-oriented failure-labeling corpus (Q9) — measurement only  
4. Re-fetch adoption metrics with `gh`  
5. Deep-dive WebDriver BiDi readiness  
6. Adversarial review of this archive: which “patterns” are selection-biased toward HN?

---

**End of report.** All durable detail lives in the leaf documents linked above.
