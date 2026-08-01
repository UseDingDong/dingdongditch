# Browser Use

**Category:** Autonomous browser agent  
**Sources:** AgentsCamp 2026 comparison; State of Browser Use May 2026; CapSolver/browser-use challenge writeups; secondary star counts  
**Labels:** FACT / EVIDENCE / PATTERN / UNKNOWN

## Purpose

Provide a task-in / result-out autonomous agent that drives a real browser (navigate, click, type, extract) using an LLM perception–action loop.

## Architecture

- High-level `Agent(task=..., llm=...)` owns the control loop. **EVIDENCE**
- Originally Playwright-backed; mid-2026 field reports describe migration toward direct CDP with event-driven watchdog architecture. **EVIDENCE** (verify against upstream README/changelog before architectural decisions — **UNKNOWN** exact current commit architecture without reading source in this pass)
- Model-agnostic wiring (OpenAI/Anthropic/Google/Ollama etc.). **EVIDENCE**
- Cloud offering adds stealth, proxies, CAPTCHA, persistent filesystem. **EVIDENCE**

## Primary audience

Python developers and teams wanting autonomous web errands without writing selectors.

## Core design philosophy

Maximize autonomy and convenience; accept per-step LLM cost as the price of improvisation on unknown sites.

## Strengths

- Highest OSS visibility among browser agents in 2026 surveys (~85k–98k stars cited across sources — approximate). **EVIDENCE**
- Strong for open-ended / net-new sites where scripts don’t exist. **EVIDENCE**
- Ecosystem default entry point. **PATTERN**

## Weaknesses

- Nondeterministic paths for the same goal. **PATTERN**
- Token/cost heavy (LLM every step). **EVIDENCE**
- Challenge pages (Turnstile/CAPTCHA) can induce observe–act loops that worsen session health. **EVIDENCE**
- Debugging “why did it wander?” is harder than debugging a script. **PATTERN**
- Benchmarks (WebVoyager etc.) overstate real-world write/auth hardness. **EVIDENCE**

## Adoption

Breakout OSS project; cloud monetization attached. **EVIDENCE**

## Relationship to AI agents

It *is* an AI agent product (control loop owned by the framework), while also exposing primitives that blur into tooling mode.
