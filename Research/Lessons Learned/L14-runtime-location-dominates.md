# L14 — Where Chrome runs dominates framework choice

## Lesson

For many deployments, the hosted browser runtime (local profile vs Browserbase vs Hyperbrowser vs Cloudflare vs Bright Data) determines reliability more than whether the script uses Stagehand or raw Playwright.

## Why this lesson exists

Money and operational complexity concentrated in remote browsers: stealth, proxies, CAPTCHA, concurrency, session replay. Frameworks are clients of that layer.

## Evidence supporting it

- State of Browser Use: “framework choice matters less than runtime choice.” **EVIDENCE**
- Cloud infra landscape (Browserbase, Steel, Anchor, Hyperbrowser, Cloudflare, Bright Data). **EVIDENCE**
- Personal-errand thesis: ROI often requires user’s real machine/profile. **EVIDENCE/SPECULATION** mix — local vs remote tradeoff remains open

## Projects demonstrating it

All cloud browser providers; Stagehand+Browserbase coupling; Browser Use Cloud; Skyvern Cloud.

## Mistakes to avoid

- Evaluating only GitHub stars of agent frameworks
- Ignoring data residency / credential gravity of runtime location
- Assuming local headless equals production remote behavior

## Engineering implication

An execution layer must be honest about **runtime coupling** (local user browser vs remote fleet) as a first-class dimension.
