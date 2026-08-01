# Non-Goals ↔ Principles / Research Crosswalk

**Purpose:** Show that each non-goal is intentional, principle-aligned, and
backed by reconnaissance patterns—not an arbitrary restriction.

**Rule:** Promoting a non-goal to a goal requires evidence (NG-13, EP-06, EP-15)
and a dated change in `NON_GOALS.md`. Feature creep is not a process.

| Non-goal | Related principles | Research anchors | Boundary clarification |
|----------|--------------------|------------------|------------------------|
| **NG-01** Not an AI model | EP-07 | L07; mission statement | Work *with* models; do not *be* one |
| **NG-02** Not a chatbot | EP-12, EP-14 | Developer feedback: demand is infra-shaped | UIs may wrap it; chat is not the product |
| **NG-03** Not a browser | EP-08 | Stack layers; CDP/engine profiles | Engines render; we do not |
| **NG-04** Not an automation framework | EP-08, EP-14 | Playwright/Puppeteer/Selenium dossiers; L08 | Alongside Playwright-class tools, not a replacement |
| **NG-05** Not an MCP replacement | EP-07, EP-14 | Playwright MCP / DevTools MCP profiles; L04 | MCP is integration glue; different problem |
| **NG-06** Not an RPA platform | EP-12, EP-14 | Skyvern posture vs tooling posture (L07) | Do not absorb workflow-builder product scope |
| **NG-07** Not a CAPTCHA solver | EP-09, EP-05 | L05, L11, L13; F7, F8; G3 | Challenges are architectural realities |
| **NG-08** Not AI reasoning | EP-07, EP-01, EP-04 | L01, L15; G2 | Reasoning stays in the AI; execution/verification elsewhere |
| **NG-09** Not user intent | EP-13 | L07; EP-13 text | User owns goals; no silent redefinition of success |
| **NG-10** Not vendor-specific | EP-07, EP-08 | L14; shared substrate pattern | Replaceable dependencies |
| **NG-11** Not demo-optimized | EP-12, EP-06 | L10, G9; developer feedback D5 | Reliability over flash |
| **NG-12** Not everything | EP-14 | G10; competitor sprawl | Integrate mature solutions |
| **NG-13** Research before expansion | EP-06, EP-14, EP-15 | Entire Research archive; Open Questions | Gate for scope changes |

## Expansion checklist (use when tempted)

Copy into design reviews:

- [ ] Which non-goal(s) does this proposal touch?
- [ ] EP alignment? (especially EP-06, EP-12, EP-14)
- [ ] Evidence that this responsibility belongs *here*?
- [ ] Already solved well elsewhere? (prefer integration)
- [ ] If promoting NG → goal: version bump + evidence link required
