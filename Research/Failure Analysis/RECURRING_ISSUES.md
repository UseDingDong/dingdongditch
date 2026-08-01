# Failure Analysis — Recurring Issue Catalog

**Scope:** Recurring patterns only — ignore one-off bugs.  
**Evidence bases:** GitHub issues/discussions, official docs, release/engineering blogs, Reddit consensus via secondary reports, Hacker News, technical blogs.  
**Date:** 2026-07-25

Each issue includes: frequency signal, technical cause, workaround, why unsatisfying, taxonomy bucket(s).

---

## F1. Flaky timing / raced readiness

| Field | Detail |
|-------|--------|
| **Issue** | Action runs before application is truly ready; or waits forever on idle conditions that never settle |
| **Frequency** | **Very high** across Selenium history and still common in Playwright/agents despite auto-wait |
| **Underlying cause** | Actionability ≠ app readiness; network/websocket/service workers keep “idle” from firing; overlays; animations |
| **Workaround** | Explicit `waitForResponse`/`expect`; avoid `waitForTimeout`; mock networks; increase timeouts |
| **Why unsatisfying** | Requires per-flow knowledge agents don’t have; timeouts mask root races; mocks diverge from prod |
| **Buckets** | browser automation; browser verification; browser execution |

---

## F2. Stale observation (act on outdated UI)

| Field | Detail |
|-------|--------|
| **Issue** | Model decides action from snapshot/screenshot; UI changes before execution (modal, reflow, dropdown) |
| **Frequency** | **High** in AI browser agents; explicitly listed in ABP motivations; classic in slow computer-use loops |
| **Underlying cause** | Live page continues mutating while model thinks; no atomic observe→act transaction |
| **Workaround** | Re-snapshot immediately before act; shorter actions; hope; experimental freeze protocols |
| **Why unsatisfying** | Extra tokens/latency; still a race; freeze approaches are not mainstream compatible yet |
| **Buckets** | browser execution; state tracking; AI reasoning |

---

## F3. Selector / ref invalidation & brittle locators

| Field | Detail |
|-------|--------|
| **Issue** | CSS/XPath/ref/cached locator no longer points at intended element |
| **Frequency** | **Very high** historically; still high for AI-generated selectors; MCP refs after navigation |
| **Underlying cause** | DOM churn; virtualization; dynamic IDs; cross-frame ID collisions (CDP backendNodeId not global) |
| **Workaround** | Role/text locators; regenerate; Stagehand-style cache refresh; deepLocator |
| **Why unsatisfying** | Regeneration costs LLM calls; caches lie when UI drifts subtly; a11y names collide |
| **Buckets** | browser automation; dynamic DOM handling |

---

## F4. Iframe / shadow DOM / OOPIF blindness

| Field | Detail |
|-------|--------|
| **Issue** | Critical controls live in nested frames or shadow roots; agent can’t see or click them |
| **Frequency** | **High** on enterprise/payment/embedded widgets; repeated Stagehand issues; HN MCP critiques |
| **Underlying cause** | Browser security + composition boundaries; tools default to root document; a11y trees incomplete across boundaries |
| **Workaround** | frameLocator; deep XPath; pierce flags; `--disable-web-security` (unsafe); vision fallback |
| **Why unsatisfying** | Complex APIs; security-disabling is unacceptable; vision expensive and imprecise |
| **Buckets** | browser architecture; dynamic DOM handling; browser automation |

---

## F5. Accessibility tree insufficiency

| Field | Detail |
|-------|--------|
| **Issue** | Snapshot-based agents can’t operate canvas, unlabeled icons, custom widgets without roles/names |
| **Frequency** | **High** on design-heavy and legacy apps; called out as “not viable for huge number of sites” on HN |
| **Underlying cause** | a11y tree is an accessibility artifact, not a complete UI semantics API |
| **Workaround** | Screenshots/vision; DOM dump (token heavy); custom attributes for agent-ready sites |
| **Why unsatisfying** | Vision brings ambiguity/cost; DOM dumps blow context; most sites won’t add agent metadata |
| **Buckets** | browser verification; AI reasoning |

---

## F6. MCP / tool-context token exhaustion

| Field | Detail |
|-------|--------|
| **Issue** | Browser tool schemas + per-step snapshots fill the context window; tasks become slow, expensive, dumb |
| **Frequency** | **High** among coding-agent users of Playwright MCP (Ask HN; multiple blogs; Microsoft CLI response) |
| **Underlying cause** | MCP pattern streams large intermediate state through the model; browsers produce huge state |
| **Workaround** | Playwright CLI; code execution pattern; summarize tool outputs; fewer tools enabled; sub-agents |
| **Why unsatisfying** | Trade observability for cost; summarizers drop critical details; splits ecosystem practices |
| **Buckets** | integration glue; AI memory |

---

## F7. Authentication & session fragility

| Field | Detail |
|-------|--------|
| **Issue** | Login fails; session expires mid-task; restored storageState rejected; step-up 2FA appears |
| **Frequency** | **Very high** for any valuable automation (the point of browser use is authenticated work) |
| **Underlying cause** | Auth systems detect automation; tokens bind to device/IP; MFA; cookie partitioning |
| **Workaround** | Human headed handoff; persistent profiles; storageState; Skyvern-class 2FA helpers; never automate password entry on hostile sites |
| **Why unsatisfying** | Human-in-the-loop breaks autonomy; stored sessions are sensitive secrets; still fails on step-up |
| **Buckets** | authentication; session persistence; browser permissions |

---

## F8. CAPTCHA / Turnstile / WAF challenge loops

| Field | Detail |
|-------|--------|
| **Issue** | Agent enters observe–act loop on challenge pages, retrying clicks/reloads, worsening trust score |
| **Frequency** | **High** on real consumer/SaaS sites; dedicated articles for browser-use + Turnstile |
| **Underlying cause** | Challenges expect human/stable browser signals; agent planners lack stop/classify vocabulary |
| **Workaround** | Detect early + human solve; solver services; stealth browsers; session reuse to avoid triggers |
| **Why unsatisfying** | Solvers raise legal/ToS/ethics issues; stealth is arms race; humans break unattended ops |
| **Buckets** | browser permissions; AI reasoning; error recovery |

---

## F9. Anti-bot detection of automation transports

| Field | Detail |
|-------|--------|
| **Issue** | Sites detect WebDriver/CDP/headless signals and block or degrade sessions |
| **Frequency** | **High** for scraping/automation; structural (not just missing stealth plugin) |
| **Underlying cause** | `navigator.webdriver`, CDP domain enables, fingerprint inconsistencies, datacenter IPs |
| **Workaround** | Stealth patches; residential proxies; headed mode; specialized hosts; automation-native browsers (early) |
| **Why unsatisfying** | Patches detectable; proxies costly; headed doesn’t scale; ethics/ToS gray zones |
| **Buckets** | browser architecture; browser permissions |

---

## F10. False progress (tool success, goal failure)

| Field | Detail |
|-------|--------|
| **Issue** | Agent believes it succeeded because click/type returned OK, but wrong item selected or server rejected |
| **Frequency** | **High** conceptually across all agents; under-instrumented in logs |
| **Underlying cause** | Lack of goal-level verification; models optimistic; UI confirms misleadingly |
| **Workaround** | Assert URL/text/API; human review; screenshots for audit |
| **Why unsatisfying** | Assertions need expected outcomes agents invent poorly; humans don’t scale |
| **Buckets** | browser verification; AI reasoning |

---

## F11. Download / dialog / permission event blindness

| Field | Detail |
|-------|--------|
| **Issue** | Native dialogs, file pickers, downloads, permission prompts interrupt flow without structured agent notification |
| **Frequency** | **Medium–high**; emphasized by ABP authors as common browser-use failures |
| **Underlying cause** | These are browser chrome / OS events, not DOM nodes; many tool adapters under-expose them |
| **Workaround** | Playwright dialog handlers; CDP events; custom hooks; freeze+event bundle experiments |
| **Why unsatisfying** | Easy to forget; inconsistent across adapters; OS file dialogs especially painful in headless |
| **Buckets** | browser execution; evidence collection; permission handling |

---

## F12. Multi-tab / multi-window state loss

| Field | Detail |
|-------|--------|
| **Issue** | Flows spanning tabs (OAuth popups, payments) confuse agents; focus/context lost |
| **Frequency** | **Medium–high** on real business flows (Reddit consensus via surveys) |
| **Underlying cause** | Agents optimize for single-page tools; popup lifecycle racing; cookie jar partitioning |
| **Workaround** | Explicit tab tools; wait for popup events; Skyvern-class workflow engines |
| **Why unsatisfying** | Still fragile; OAuth provider variance; hard to test |
| **Buckets** | state tracking; authentication; multiple tabs |

---

## F13. Computer-use coordinate / gesture fragility

| Field | Detail |
|-------|--------|
| **Issue** | Mis-clicks from scaling, scrolling, drag/zoom difficulty, visual ambiguity |
| **Frequency** | **High** for pure vision computer use (vendor-acknowledged) |
| **Underlying cause** | Screenshots are lossy; coordinates depend on resolution/scale; some gestures hard to infer |
| **Workaround** | Reduce resolution carefully per docs; prefer DOM tools when available; limit task scope |
| **Why unsatisfying** | Gives up universality; still error-prone on dense UIs |
| **Buckets** | AI reasoning; browser execution; vision dependence |

---

## F14. Prompt injection via page content

| Field | Detail |
|-------|--------|
| **Issue** | Page text instructs agent to exfiltrate data or perform unintended actions |
| **Frequency** | **Rising / strategically critical** (2026 threat reports; OWASP #1) — not just theoretical |
| **Underlying cause** | Untrusted content enters model context with privileges of user session |
| **Workaround** | Domain allowlists; human gates; sandbox; action constraints; lockdown modes |
| **Why unsatisfying** | Incomplete mitigations; utility vs lockdown tradeoff; no architectural silver bullet yet |
| **Buckets** | browser permissions; AI reasoning; integration glue |

---

## F15. Shared storageState / profile poisoning

| Field | Detail |
|-------|--------|
| **Issue** | One flow logs out or corrupts saved auth used by others; parallel tests contaminate |
| **Frequency** | **Medium** but severe when it hits (CI and agent fleets) |
| **Underlying cause** | Mutable shared artifacts; storageState only updates when explicitly written |
| **Workaround** | Immutable auth files; unique paths; isolate profiles per run |
| **Why unsatisfying** | Operational complexity; agents still need shared “user’s real profile” for personal errands |
| **Buckets** | session persistence; authentication |

---

## Cross-cutting note

**PATTERN:** Failures labeled “AI is dumb” often reduce to **F2 + F5 + F10** (stale/partial observation + weak verification). Failures labeled “automation is flaky” often reduce to **F1 + F3 + F4**. Failures labeled “can’t do real work” often reduce to **F7 + F8 + F14**.
