# L03 — Live pages race the model

## Lesson

If JavaScript and rendering continue while the model deliberates, the action eventually executed may target a world that no longer matches the observation.

## Why this lesson exists

LLM inference latency (hundreds of ms to many seconds) is long compared to UI animation and network-driven DOM updates. Classic scripts are faster and still race; agents are slower and race more.

## Evidence supporting it

- ABP Show HN: lists modal-after-screenshot, autocomplete overlay, dynamic reflow as common failures; freezes JS/render between turns as response. **EVIDENCE** (author claims; independent replication UNKNOWN)
- Computer-use cycle times often multi-second. **EVIDENCE**
- Playwright flake literature: actionable now ≠ actionable at event dispatch under overlays. **EVIDENCE**

## Projects demonstrating it

Default Playwright/Puppeteer agent wrappers; Browser Use; Anthropic CU; MCP snapshot-then-act; ABP (counter-approach).

## Mistakes to avoid

- Assuming “we just took a snapshot” means the next click is synchronized
- Blaming only the model for mis-clicks that are timing bugs
- Adding more retries without addressing desynchronization

## Engineering implication

Synchronization between **observation epoch** and **action epoch** is a core reliability variable of the execution layer — currently under-modeled in mainstream stacks.
