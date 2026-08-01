# Architecture Notes — Stack Layers & Postures

## Layer cake (PATTERN)

```
┌─────────────────────────────────────────────┐
│  AI reasoning host (Claude, GPT, local, …)  │  changes fast
├─────────────────────────────────────────────┤
│  Agent product OR coding agent harness      │  Browser Use, Cursor, ChatGPT Agent, …
├─────────────────────────────────────────────┤
│  Tool adapter (MCP / CLI / SDK primitives)  │  Playwright MCP, Stagehand act(), …
├─────────────────────────────────────────────┤
│  Automation library / policy                │  Playwright auto-wait, waits, asserts
├─────────────────────────────────────────────┤
│  Wire protocol                              │  CDP / WebDriver / BiDi
├─────────────────────────────────────────────┤
│  Browser engine + OS session                │  Chromium/Firefox/WebKit + profile
└─────────────────────────────────────────────┘
```

**Mission-relevant observation (not a design):** Most competition today is at the agent-product and tool-adapter layers. The wire protocol and engine layers are shared. Reliability failures often originate at **policy gaps between layers** (verification, sync, auth, recovery), not at “missing a click API.”

## Four postures (EVIDENCE: AgentsCamp 2026)

| Posture | Who drives | Examples |
|---------|------------|----------|
| Autonomous agent | Framework loop | Browser Use |
| Code-first hybrid | Engineer + AI joints | Stagehand |
| Workflow/RPA platform | Ops-defined workflows | Skyvern |
| Tools for existing agent | Host coding agent | Playwright MCP, Chrome DevTools MCP |

## Grounding strategies (PATTERN)

| Strategy | Pros | Cons |
|----------|------|------|
| Accessibility / DOM structure | Cheap, deterministic refs | Blind to unlabeled/visual-only UI; frame/shadow hard |
| Vision / pixels | Works when DOM hostile | Costly, ambiguous, coordinate fragility |
| Hybrid | Practical default in 2026 | Complexity; when to switch? |
| Code-mode / cached actions | Amortizes LLM | Cache drift; discovery still hard |

## Driving vs debugging (EVIDENCE)

Steve Kinney / field consensus: Playwright MCP **drives**; Chrome DevTools MCP **debugs**. Systems that only drive without inspectability struggle in production.
