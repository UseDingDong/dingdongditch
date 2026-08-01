# Developer Feedback Synthesis

**Sources:** Hacker News threads, GitHub issues, Reddit consensus as reported by field surveys, engineering blogs.  
**Method:** Cluster recurring sentiments; exclude one-off rants.

---

## Cluster D1 — “Playwright MCP is powerful but burns the context window”

**Signal strength:** Strong (multiple independent HN comments + technical analyses + Microsoft CLI response)

**Representative claims:**
- Nearly every call blows context
- Need large context models to compensate
- Prefer writing Playwright directly or using CLI/code-execution

**Implication for archive:** Supports L04, F6.

---

## Cluster D2 — “These tools were designed for testing, not agents”

**Signal strength:** Medium–strong

**Representative claims:**
- Low-level APIs force LLMs to micromanage
- Frame/edge-case handling insufficient for messy web
- Accessibility tree inadequate for many sites

**Implication:** Supports G5, L02, L06.

---

## Cluster D3 — “Autonomy is great until login/CAPTCHA/2FA”

**Signal strength:** Strong in “real work” discussions

**Representative claims:**
- Hard portal automation needs Skyvern-class features
- Human handoff for auth is the only reliable path on major social platforms
- Challenge loops make agents worse

**Implication:** Supports L05, F7, F8.

---

## Cluster D4 — “Install Playwright MCP + Chrome DevTools MCP”

**Signal strength:** Strong in 2026 how-to guides

**Representative claims:**
- One drives, one debugs
- Coding agents verifying frontend benefit most

**Implication:** Supports L09; driving≠debugging gap.

---

## Cluster D5 — “Leaderboards don’t match production pain”

**Signal strength:** Medium–strong among practitioners/analysts

**Representative claims:**
- WebVoyager saturated
- Live write tasks ~30%
- Vendor scores are theater

**Implication:** Supports L10, G9.

---

## Cluster D6 — “Prompt injection is the actual ceiling”

**Signal strength:** Rising / strategically emphasized in 2026 analyses

**Representative claims:**
- Reliability is not the interesting unsolved problem anymore — security is
- Programmatic boundaries > LLM judgment

**Implication:** Supports L11, G8.

---

## Cluster D7 — “Hybrid control > pure autonomy for maintained systems”

**Signal strength:** Medium (engineering blogs comparing Stagehand vs Browser Use)

**Representative claims:**
- Use AI at brittle joints
- Cache to deterministic replay
- Python autonomy vs TS control split by team shape

**Implication:** Supports L07, L08.

---

## What developers are *not* asking for (observation)

Few practitioners ask for “another chat UI for browsing.” Many ask for:
- lower token cost
- better auth/challenge handling
- less flaky grounding across frames
- better debug evidence
- clearer stop/handoff behavior

This aligns with infrastructure-shaped demand rather than assistant-shaped demand. **PATTERN** (interpret cautiously — selection bias toward HN/GitHub audiences).
