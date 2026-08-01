# L11 — Untrusted HTML + privileged session is a security architecture problem

## Lesson

Browser agents combine adversarial content with the user’s authenticated power. This is not a prompt-engineering issue; it is a privilege-separation issue.

## Why this lesson exists

2026 moved prompt injection from theory to wild exploitation reports. Every major posture inherits the same tax: domain allowlists, isolated profiles, human gates on irreversible actions.

## Evidence supporting it

- Google threat intel / Unit 42 / Vectra / OWASP citations in May 2026 field survey. **EVIDENCE** (secondary — verify primaries before security claims in public)
- OpenAI Lockdown Mode; Anthropic browser-use injection defenses ongoing. **EVIDENCE**
- AgentsCamp: shared security reality across Browser Use, Stagehand, Skyvern, MCP. **EVIDENCE**
- Anthropic recommends sandboxed computer-use environments. **FACT**

## Projects demonstrating it

All browser agents; ChatGPT Agent; Claude Computer Use; MCP browser tools with user profiles.

## Mistakes to avoid

- Relying on the model to “not fall for” page instructions
- Giving ambient credentials broader than the task
- Testing only on trusted first-party pages

## Engineering implication

Safety boundaries must be **programmatic** (what can execute) not merely advisory (what model should decide).
