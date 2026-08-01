# L05 — Auth and challenges are the product, not edge cases

## Lesson

For valuable browser work, authentication, session continuity, step-up MFA, and bot challenges dominate failure — demos on logged-out marketing sites hide the real problem.

## Why this lesson exists

Field analysts note browser use exists *because* agents need account state. Frameworks that ignore CAPTCHA/2FA look fine on benchmarks and die on portals.

## Evidence supporting it

- State of Browser Use May 2026: agent without account access is a demo. **EVIDENCE**
- Skyvern product differentiation on CAPTCHA/2FA. **EVIDENCE**
- Browser Use + Turnstile loop writeups. **EVIDENCE**
- Social platform auth notes: headed human handoff as only reliable approach. **EVIDENCE**
- Stagehand criticized at 6/10 on login+2FA without help (secondary). **EVIDENCE**

## Projects demonstrating it

Skyvern; Browser Use Cloud; Anchor login reputation; Playwright storageState patterns; OpenAI HITL login; Browserless session guides.

## Mistakes to avoid

- Designing happy-path DOM loops first and “adding auth later”
- Treating CAPTCHA as a captcha-solver plugin instead of a control-flow state
- Storing session secrets casually in repos (storageState pitfalls)

## Engineering implication

Session identity, challenge classification, and human handoff boundaries must be modeled as core execution states — not exceptions.
