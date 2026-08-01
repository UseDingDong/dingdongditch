# L06 — Frame boundaries are first-class architecture

## Lesson

Iframes, OOPIFs, and shadow roots are not corner cases; they are how the modern web composes payment, auth, chat, and design systems. Flat document assumptions fail systematically.

## Why this lesson exists

Repeated engineering investment (Stagehand deepLocator, piercers, CDP session per frame) and repeated user issues show this is structural browser architecture, not a missing selector.

## Evidence supporting it

- Browserbase “Taming iframes” engineering post: node IDs not unique across frames; CDP session context per iframe. **EVIDENCE**
- Stagehand GitHub issues on shadow+iframe; v3 fixes ongoing. **EVIDENCE**
- HN critiques of Playwright MCP frame piercing. **EVIDENCE**
- Playwright frameLocator API existence. **FACT**

## Projects demonstrating it

Stagehand; Playwright; CDP Target sessions; Selenium switch_to.frame history.

## Mistakes to avoid

- Root-DOM-only snapshots as the sole world model
- Assuming backendNodeId / refs are globally unique
- Disabling web security as a “fix”

## Engineering implication

Any serious execution layer needs an explicit **composed document model** across browsing contexts — or will relearn Stagehand’s iframe lessons.
