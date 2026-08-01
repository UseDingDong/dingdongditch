# L07 — Agent vs tooling is a control-loop ownership decision

## Lesson

The important fork in the ecosystem is not “which LLM,” but **who owns the control loop**: a browser-agent product, or an external agent calling browser tooling.

## Why this lesson exists

Marketing blurs categories (everyone ships both an agent mode and an SDK). Engineering consequences diverge: debugging, determinism, cost, and integration paths.

## Evidence supporting it

- Explicit two-shapes taxonomy in State of Browser Use May 2026. **EVIDENCE**
- AgentsCamp four postures. **EVIDENCE**
- Stagehand `agent()` vs primitives; Browser Use primitives vs Agent(). **EVIDENCE**
- MCP servers as “hands for existing agents.” **FACT/EVIDENCE**

## Projects demonstrating it

Browser Use; Stagehand; Skyvern; Playwright MCP; ChatGPT Agent; Claude Computer Use (DIY loop).

## Mistakes to avoid

- Comparing products across postures with one leaderboard number
- Assuming a universal execution layer must also be an autonomous agent
- Ignoring that our mission statement points at **tooling/execution**, not assistant product

## Engineering implication

Clarify control-loop ownership before any API design; many “competitor features” are posture-specific and non-transferable.
