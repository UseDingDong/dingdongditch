# L01 — Actionability is not correctness

## Lesson

A successful, actionable browser interaction (element visible, enabled, clicked without exception) does **not** mean the user goal advanced.

## Why this lesson exists

Automation frameworks optimized for reducing flake invented “actionability.” Agent systems inherited it as a proxy for progress. They are different predicates.

## Evidence supporting it

- Playwright official auto-wait docs: checks attach/visibility/stability/enabled/receives events — not business outcomes. **FACT**
- Community flake guides: click succeeds while async table refresh still pending. **EVIDENCE**
- Computer-use returns click acknowledgements without goal oracles. **PATTERN**
- Production guidance (“verify after consequential actions”) across agent surveys. **EVIDENCE**

## Projects demonstrating it

Playwright; Puppeteer locators; Selenium waits; Playwright MCP `browser_click`; Anthropic Computer Use; Browser Use observe–act loops.

## Mistakes to avoid

- Treating tool “OK” as task success
- Using only actionability waits as verification
- Retrying the same actionable click when the server already rejected silently

## Engineering implication

Any future execution layer must distinguish **interaction predicates** from **goal predicates**, and make the latter first-class — without this reconnaissance prescribing how.
