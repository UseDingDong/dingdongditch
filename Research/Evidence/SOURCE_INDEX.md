# Source Index & Citation Ledger

**Reconnaissance date:** 2026-07-25  
**Note:** `gh` CLI was unavailable in the research environment; GitHub star counts are from secondary surveys and should be re-fetched.

## Primary / official

| Source | URL | Used for |
|--------|-----|----------|
| Playwright MCP introduction | https://playwright.dev/mcp/introduction | Playwright MCP purpose, tools, a11y refs |
| Playwright auto-waiting | https://playwright.dev/docs/actionability | Actionability definition |
| Chrome DevTools Protocol | https://chromedevtools.github.io/devtools-protocol/ | CDP architecture |
| Anthropic computer use announcement | https://www.anthropic.com/news/3-5-models-and-computer-use | Experimental limitations honesty |
| Anthropic computer-use tool docs | https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool | Sandbox loop architecture |
| Chrome DevTools for agents | https://developer.chrome.com/docs/devtools/agents/get-started | DevTools MCP suite |

## High-value secondary surveys (treat as EVIDENCE, not FACT)

| Source | URL | Used for |
|--------|-----|----------|
| Browser Agents compared 2026 (AgentsCamp) | https://agentscamp.com/guides/comparisons/browser-agents-compared-2026 | Four postures; relative positioning |
| State of Browser Use, May 2026 | https://michaellivs.com/blog/state-of-browser-use-2026/ | Two shapes; infra landscape; benchmark skepticism; security |
| MCP browser automation landscape (ChatForest) | https://chatforest.com/guides/mcp-browser-automation/ | MCP pattern; a11y vs vision |
| Playwright MCP vs CLI token analysis | https://dreaming.press/posts/playwright-mcp-vs-cli-token-cost-browser-agents.html | Token cost tradeoff |
| WorkOS Anthropic vs OpenAI CUA | https://workos.com/blog/anthropics-computer-use-versus-openais-computer-using-agent-cua | Computer-use product split |
| Stagehand iframe engineering | https://browserbase.com/blog/taming-iframes-a-stagehand-update/ | Frame architecture pain |
| Playwright flake patterns (Mergify) | https://mergify.com/learn/flaky-tests/playwright | Classic automation failure modes |
| Detection surfaces (Crawlex) | https://blog.crawlex.net/blog/playwright-puppeteer-selenium-detection/ | Transport detection |

## GitHub issues / discussions (samples)

| Item | URL | Signal |
|------|-----|--------|
| Stagehand shadow+iframe | https://github.com/browserbase/stagehand/issues/848 | Frame/shadow pain; LLM call waste |
| Stagehand waitForSelector pierce | https://github.com/browserbase/stagehand/issues/1509 | Cross-frame waits as product need |
| Stagehand shadow hop PR | https://github.com/browserbase/stagehand/pull/2220 | Selector semantics fragility |

## Hacker News

| Item | URL | Signal |
|------|-----|--------|
| Ask HN: Playwright MCP Unusable? | https://news.ycombinator.com/item?id=45764043 | Context blowup |
| Tools: Code Is All You Need (MCP flaky/token) | https://news.ycombinator.com/item?id=44456806 | Prefer direct Playwright |
| Local OSS browser agents thread | https://news.ycombinator.com/item?id=46913495 | MCP unreliable; a11y limits; DevTools MCP praise |
| Show HN: ABP deterministic control | https://news.ycombinator.com/item?id=47275862 | Stale state thesis |
| Show HN: agent-browser / freeze | https://news.ycombinator.com/item?id=47336171 | Event blindness list |

## Failure-mode articles

| Source | URL | Signal |
|--------|-----|--------|
| Browser Use blocked by Turnstile | https://www.capsolver.com/blog/cloudflare/browser-use-agent-blocked-by-turnstile-fix | Challenge loops |
| Breaking CAPTCHA loops in AI agents | https://www.capsolver.com/blog/ai/breaking-the-captcha-loop-in-ai-web-agents | Stop/classify needs |
| Browserless AI automation guide | https://www.browserless.io/blog/browser-automation-api-ai-coding-platforms | Session persistence, CAPTCHA strategies |

## Benchmark caveat references (verify before citing publicly)

- WebVoyager leaderboard numbers as quoted in May 2026 survey
- Online-Mind2Web claims (Browser Use, ABP)
- ClawBench / Illusion of Progress (Xue et al., COLM 2025) — **read original papers** in follow-up
- Skyvern WebBench figures from vendor/survey

## Evidence quality policy

1. Prefer official docs for architecture FACTS  
2. Prefer multiple independent complaints for PATTERN  
3. Vendor benchmarks = weak evidence of absolute capability  
4. Mark product details that churn (OpenAI Operator→Agent) as needing re-verification
