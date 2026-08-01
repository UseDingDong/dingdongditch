# L13 — Recovery without stop conditions digs deeper holes

## Lesson

Blind retries and open-ended replanning on challenge pages, auth walls, and irreversible actions often reduce recoverability (bot score escalation, duplicate submits, session death).

## Why this lesson exists

Agent loops optimize for “try something else.” Challenge systems optimize for “stable human decision.” These objectives conflict.

## Evidence supporting it

- CapSolver/browser-use Turnstile: observe–act loops worsen session health; need classify/stop/handoff vocabulary. **EVIDENCE**
- Playwright CI retries without traces mask flakes. **EVIDENCE**
- Production agent advice: human gates on payments/sends. **EVIDENCE**

## Projects demonstrating it

Browser Use; general LLM agents; Playwright retry configs; Skyvern exception handling (relative positive case).

## Mistakes to avoid

- Infinite replans on the same URL
- Retrying submits without idempotency
- Treating “model is trying hard” as recovery quality

## Engineering implication

Recovery policies need **typed failure classes** and **stop/handoff rules**, not only “ask the model again.”
