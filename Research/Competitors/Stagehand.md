# Stagehand (Browserbase)

**Category:** Hybrid AI + code SDK (tooling; optional agent mode)  
**Sources:** Stagehand docs; Browserbase iframe blog; GitHub issues #848, #1509; PR #2220; industry comparisons  
**Labels:** FACT / EVIDENCE / PATTERN / UNKNOWN

## Purpose

Let engineers write mostly deterministic browser automations while calling AI only where selectors would be brittle (`act`, `extract`, `observe`), with optional autonomous `agent` mode.

## Architecture

- TypeScript-first SDK historically built on Playwright. **EVIDENCE**
- **v3:** multiple 2026 sources report a native CDP layer that dropped Playwright dependency for speed and deeper DOM handling (44% faster claimed on shadow DOM/iframe interactions in secondary blogs). **EVIDENCE** — confirm against current package source before relying (**UNKNOWN** without source audit this pass)
- **Action caching:** map NL action → selector/action once; replay without LLM when page is similar. **EVIDENCE**
- **deepLocator / frame traversal:** explicit work to pierce iframes and shadow DOM; MutationObserver-based waits. **EVIDENCE** (docs + issues)

## Primary audience

TypeScript teams maintaining repeatable production automations; Browserbase cloud users.

## Core design philosophy

Control-first: reliability of code where possible; AI as surgical escape hatch; amortize LLM cost via cache.

## Strengths

- Hybrid posture matches production engineering instincts. **PATTERN**
- Caching converts AI discovery into deterministic replay. **EVIDENCE**
- Schema-validated extraction (Zod) reduces unstructured hallucination at extract step. **EVIDENCE**
- Active investment in iframe/shadow correctness. **EVIDENCE**

## Weaknesses

- Language niche (TS) vs Browser Use’s Python gravity. **EVIDENCE**
- AI path still fails on login+2FA without external help (criticized across frameworks). **EVIDENCE**
- Cache invalidation / page drift can silently reintroduce LLM dependence or wrong replay — **SPECULATION** on failure modes; needs deeper evidence
- Historical user pain: shadow+iframe combinations wasted LLM calls before v3 fixes. **EVIDENCE** (issue #848)

## Adoption

~20k+ stars cited mid-2026. **EVIDENCE** (approximate)

## Relationship to AI agents

Primarily **tooling for agents/engineers**; `agent()` blurs into autonomous product. Important example of separating “AI at the joints” from “AI owns the loop.”
