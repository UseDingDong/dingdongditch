# L08 — Determinism is a spectrum you pay for

## Lesson

Autonomy, adaptability, and determinism trade off. Caching, code-gen, and scripts buy repeatability; open-ended LLM loops buy improvisation. You cannot maximize all three without a policy for when to switch.

## Why this lesson exists

Stagehand caching, Skyvern code-gen, Playwright scripts, and Browser Use autonomy are different points on the same spectrum. Cost and reliability complaints map to where teams sit on it.

## Evidence supporting it

- Stagehand action cache → near Playwright speed on replay. **EVIDENCE**
- Skyvern code-gen to cut vision costs. **EVIDENCE**
- Browser Use per-step LLM honesty about cost. **EVIDENCE**
- Dreaming.press: MCP expensive but self-correcting vs CLI cheap but brittle. **EVIDENCE**

## Projects demonstrating it

Stagehand; Skyvern; Browser Use; Playwright MCP vs CLI; classic Playwright scripts.

## Mistakes to avoid

- Promising “autonomous and deterministic and cheap”
- Evaluating only first-run discovery cost, ignoring steady-state
- Treating cache hits as proof the world didn’t change

## Engineering implication

Record where a workflow sits on the determinism spectrum as an explicit property of the execution, not an accident of implementation.
