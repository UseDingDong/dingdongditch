# L02 — Observation channels are lossy and non-equivalent

## Lesson

DOM, accessibility tree, screenshots, and network events each omit different critical information. No single channel is “the page.”

## Why this lesson exists

Each camp marketed one channel as sufficient (a11y for MCP, pixels for computer use, DOM for classic automation). Production systems converge on hybrids because each channel fails on important site classes.

## Evidence supporting it

- Playwright MCP: a11y snapshots + optional screenshots. **FACT**
- HN: a11y “not viable for a huge number of websites.” **EVIDENCE**
- Skyvern/Magnitude: vision when DOM fails. **EVIDENCE**
- Chrome DevTools MCP demand: network/console missing from click-only tools. **EVIDENCE**
- Anthropic: scrolling/drag/zoom hard from pixels. **FACT**

## Projects demonstrating it

Playwright MCP; Skyvern; Anthropic CU; Chrome DevTools MCP; Stagehand (structure + AI).

## Mistakes to avoid

- Designing as if one observation mode wins forever
- Equating “model saw something” with “model saw enough”
- Dumping raw DOM into context as a completeness strategy (see L04)

## Engineering implication

Observation is a **multi-signal** problem with explicit coverage gaps; verification and grounding policies must know which signals are absent.
