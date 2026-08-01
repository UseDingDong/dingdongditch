# L04 — LLM context is a hostile place for raw browser state

## Lesson

Pushing full page state (snapshots, screenshots, tool schemas) through the model context repeatedly destroys cost, latency, and reasoning quality — yet stripping it destroys recovery.

## Why this lesson exists

MCP made tool I/O model-visible by default. Browsers generate the largest intermediate states in common agent tooling, so the general MCP bloat problem becomes acute.

## Evidence supporting it

- Published analyses: ~114k tokens MCP vs ~27k CLI for comparable browser tasks. **EVIDENCE**
- Anthropic engineering: code execution with MCP cutting huge fractions of tokens in general tool use. **EVIDENCE**
- Ask HN: Playwright MCP blows context; users need huge context windows. **EVIDENCE**
- Microsoft positioning Playwright CLI for coding agents. **FACT/EVIDENCE**

## Projects demonstrating it

Playwright MCP; Playwright CLI; general MCP tool hosts; computer-use screenshot token burn.

## Mistakes to avoid

- Equating “more page fidelity in context” with “more reliability”
- Ignoring tool-schema overhead
- Assuming summarization is lossless

## Engineering implication

Where page state **lives** (model context vs execution environment vs on-disk artifacts) is an architectural decision with first-order reliability/cost effects.
