# Scope Traps

**Phase:** 2A  
**Date:** 2026-07-25  
**Purpose:** Name the ways DingDongDitch accidentally becomes something it is
not, and how to detect drift early.

Aligned with `NON_GOALS.md` and `ENGINEERING_PRINCIPLES.md`.

---

## Trap catalog

### T1 — Another browser agent

| | |
|--|--|
| **Cause** | Own the observe→plan→act loop; add `agent()` as the flagship API; accept raw goals and return finished tasks |
| **Why wrong** | NG-01, NG-02, NG-08; competes with Browser Use / ChatGPT Agent; abandons infrastructure identity |
| **Early signs** | README demos “give us a goal”; planning prompts in core; retries that replan internally by default |
| **Detection question** | “If we delete the planner, does the product still have a clear job?” If no → trap |

### T2 — Another Playwright wrapper

| | |
|--|--|
| **Cause** | Primary API is `click`/`fill`/`goto` with slight helpers; deep one-library binding without semantic contract |
| **Why wrong** | NG-04, NG-12, EP-08; Playwright already excellent |
| **Early signs** | “Drop-in Playwright replacement”; reimplementing locators/auto-wait |
| **Detection question** | “Are we attesting outcomes or re-driving the browser?” |

### T3 — Another MCP server (as identity)

| | |
|--|--|
| **Cause** | Project defined as “the MCP for browsers”; replaces Playwright MCP |
| **Why wrong** | NG-05; MCP is transport/integration, different problem |
| **Early signs** | Success metrics = MCP client logos; core = tool list of click/type |
| **Detection question** | “Is MCP a binding or the product?” Binding OK; product not |

### T4 — RPA / workflow platform

| | |
|--|--|
| **Cause** | Visual builders, SOP importers, org workflow catalogs, SLA dashboards |
| **Why wrong** | NG-06; Skyvern-class competitors; EP-14 |
| **Early signs** | “Departments,” “approvals routing,” “process templates” as core nouns |
| **Detection question** | “Are we verifying browser claims or managing business processes?” |

### T5 — CAPTCHA / anti-bot product

| | |
|--|--|
| **Cause** | Ship solvers, stealth fingerprint packs, bypass guides as features |
| **Why wrong** | NG-07, EP-09 ethics/architecture; arms race; legal risk (Q14) |
| **Early signs** | Marketing “bypass Cloudflare”; solver vendor SDKs in core |
| **Detection question** | “Do we classify/stop or defeat?” Defeat → trap |

### T6 — Browser / security product

| | |
|--|--|
| **Cause** | Full isolation suite, enterprise DLP, threat intel platform |
| **Why wrong** | Dilutes attestation mission; EP-14; different buyers |
| **Early signs** | Security compliance frameworks dominate roadmap vs verdict semantics |
| **Detection question** | “Is privilege a gate around attestation or the whole company?” |

### T7 — AI planner / reasoner

| | |
|--|--|
| **Cause** | Embed default models for “what to do next”; fine-tune planners |
| **Why wrong** | NG-01, NG-08, EP-07 |
| **Early signs** | Required API keys for core path; prompts as primary source |
| **Detection question** | “Does core work with a dumb scripted host?” If no → trap |

### T8 — Generic observability platform

| | |
|--|--|
| **Cause** | Traces/logs/metrics product without attestation semantics |
| **Why wrong** | NG-12; Playwright traces / DevTools / APM exist; EP-14 |
| **Early signs** | “Our Jaeger for browsers” without expectation verdicts |
| **Detection question** | “Can we answer ‘did declared progress occur?’” If no → trap |

### T9 — Test framework redux

| | |
|--|--|
| **Cause** | Only serve CI `expect` use cases; ignore agent hosts |
| **Why wrong** | Not wrong morally—but duplicates Playwright Test; misses G2 agent gap |
| **Early signs** | Docs only for engineers writing static asserts; no host-declared expectations |
| **Detection question** | “Does this help AI hosts that didn’t write the test?” |

### T10 — Over-engineered protocol with no adopter

| | |
|--|--|
| **Cause** | Huge normative spec before reference use; universality cosplay |
| **Why wrong** | EP-12, EP-14; Phase 1 opportunity unproven (recon SPECULATION) |
| **Early signs** | Spec pages >> working attestation examples; no embedder |
| **Detection question** | “Who implements this besides us, and why?” |

### T11 — Desktop-universal execution layer too early

| | |
|--|--|
| **Cause** | Abstract “all GUIs” before browser semantics solved |
| **Why wrong** | Premature universality; EP-14; browser-specific evidence base |
| **Early signs** | OS UI automation as v1 milestone |
| **Detection question** | “Is browser semantics essential to current value?” (see recommendation: yes for v1) |

---

## Drift review checklist (for future PRs)

- [ ] Touches which Non-Goals?  
- [ ] Still one-sentence responsibility?  
- [ ] Adds planning, click-driving, or CAPTCHA defeat?  
- [ ] Evidence for expansion (NG-13)?  
- [ ] Integrates existing tool instead of reinventing (NG-12)?  

---

## Healthy adjacent work (not traps if bounded)

| Activity | Healthy framing |
|----------|-----------------|
| MCP binding | Optional adapter exposing attestation tools |
| Playwright backend | Implementation detail under EP-08 |
| Challenge classification | `blocked` / `needs-human`—not solving |
| Evidence bundles | In service of verdicts—not a standalone APM |
| Irreversible action gates | Least privilege around attestation consumers |
