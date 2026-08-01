# Stack Position Analysis

**Phase:** 2A  
**Date:** 2026-07-25  
**Stack reference:** `Research/Architecture/STACK_LAYERS.md`

Positions A–F are compared **without recommending** until the end of this file’s
comparison tables. The Phase 2A choice is recorded only in
`PHASE_2A_RECOMMENDATION.md`.

Epistemic labels: FACT / EVIDENCE / PATTERN / INTERPRETATION / SPECULATION / UNKNOWN

---

## Reference stack

```
AI reasoning host
    → Agent product / coding agent harness
        → Tool adapter (MCP / CLI / SDK)
            → Automation library (Playwright / Puppeteer / …)
                → Wire protocol (CDP / WebDriver / BiDi)
                    → Browser engine + OS session
```

**PATTERN (Phase 1):** Reliability failures often sit in **policy gaps between
layers**, not missing click APIs.

---

## Position A — Between AI reasoning host and AI-facing tool adapter

| Dimension | Analysis |
|-----------|----------|
| **Inputs** | Host intents/plans; proposed tool calls; declared expectations; prior attestation results |
| **Outputs** | Allowed/rewritten tool calls; attestation verdicts; evidence refs; blocked/uncertain statuses |
| **Authority** | May gate or annotate calls before/after adapter; should not invent goals (NG-09) |
| **Can verify** | Whatever expectations the host declares + observables returned via tools |
| **Cannot verify** | Merchant back-office truth; user mental intent; model-internal plans |
| **Dependencies** | Stable tool schemas; host cooperation to declare expectations |
| **Vendor neutrality** | High for models; medium for adapters (must understand many MCP/CLI shapes) |
| **Duplication risk** | Medium — looks like “smart MCP proxy” |
| **AI reasoning ownership risk** | High if it starts planning; low if attestation-only |
| **Scripts + agents** | Yes if both emit declared expectations |

**Trap:** Becomes another agent harness or MCP replacement (NG-05).

---

## Position B — Between tool adapter and automation library

| Dimension | Analysis |
|-----------|----------|
| **Inputs** | Adapter commands already chosen; library handles |
| **Outputs** | Instrumented library calls; post-action evidence; verdicts |
| **Authority** | Strong over how library APIs are invoked |
| **Can verify** | Browser-observable conditions via library |
| **Cannot verify** | Host goal quality; whether the adapter chose the right command |
| **Dependencies** | Deep binding to Playwright/Puppeteer APIs |
| **Vendor neutrality** | **Low** for automation tools — fights EP-08 / NG-04 |
| **Duplication risk** | High — “Playwright middleware” |
| **AI reasoning ownership risk** | Low |
| **Scripts + agents** | Strong for scripts; agents only if adapters route through it |

**Trap:** Becomes Playwright wrapper (NG-04).

---

## Position C — Policy layer around Playwright / Puppeteer / CDP / WebDriver

| Dimension | Analysis |
|-----------|----------|
| **Inputs** | Automation calls + optional expectation objects |
| **Outputs** | Same automation results + attestation/evidence sidecar |
| **Authority** | Policy on waits, checks, stop conditions, irreversible gates |
| **Can verify** | Rich browser signals (network, DOM, console) if allowed |
| **Cannot verify** | Cross-tool portability if policy is engine-specific |
| **Dependencies** | At least one automation backend |
| **Vendor neutrality** | Medium if multiple backends behind one policy API; low if Chromium-only |
| **Duplication risk** | Medium–high (test frameworks already have expects) |
| **AI reasoning ownership risk** | Low |
| **Scripts + agents** | Excellent for scripts; agents need a bridge |

**Trap:** Replacing Playwright semantics instead of wrapping policy (NG-04).  
**Note:** Playwright `expect` already covers engineer-written oracles—gap is
**agent-usable, progress-oriented attestation** (EVIDENCE), not absence of asserts.

---

## Position D — Host-controlled execution runtime (verification + recovery inside)

| Dimension | Analysis |
|-----------|----------|
| **Inputs** | Goals or plans from host |
| **Outputs** | Task results; managed browser session |
| **Authority** | Owns turn-taking, retries, possibly planning hooks |
| **Can verify** | Internal whatever it defines |
| **Cannot verify** | Neutrality—becomes the product loop |
| **Dependencies** | Browser runtime, storage, often cloud |
| **Vendor neutrality** | Low in practice |
| **Duplication risk** | **Very high** vs Browser Use / Skyvern / ChatGPT Agent |
| **AI reasoning ownership risk** | **Very high** |
| **Scripts + agents** | Becomes an agent |

**Trap:** This **is** the browser-agent product shape (NG-01/02/06/08).  
**INTERPRETATION:** Incompatible with Phase 1 non-goals as primary position.

---

## Position E — Protocol / contract that other runtimes implement

| Dimension | Analysis |
|-----------|----------|
| **Inputs** | Abstract: declared expectation, observation handles, action receipts |
| **Outputs** | Verdict vocabulary; evidence artifact schema; freshness/epoch rules |
| **Authority** | Normative semantics only; no browser by itself |
| **Can verify** | Only what implementers can observe |
| **Cannot verify** | Compliance without implementations |
| **Dependencies** | Adopters; versioning; possible transport bindings (incl. MCP *as* one binding—not a replacement) |
| **Vendor neutrality** | **Highest** (EP-07, EP-08, NG-10) |
| **Duplication risk** | Low on automation; risk of “yet another unused protocol” |
| **AI reasoning ownership risk** | Lowest |
| **Scripts + agents** | Both can implement the contract |

**Trap:** Over-engineered protocol with no adopter (`SCOPE_TRAPS.md`).  
**UNKNOWN:** Whether semantics can be specified tightly enough to be useful (Q16).

---

## Position F — Library embedded in browser-agent products

| Dimension | Analysis |
|-----------|----------|
| **Inputs** | In-process calls from Browser Use / Stagehand / custom agents |
| **Outputs** | Verdicts + evidence |
| **Authority** | Only within embedding product |
| **Can verify** | Whatever embedder exposes |
| **Cannot verify** | Cross-product universality unless API converges on E |
| **Dependencies** | Language ecosystems |
| **Vendor neutrality** | Medium (multi-language ports) |
| **Duplication risk** | Low if thin; high if each embedder forks semantics |
| **AI reasoning ownership risk** | Low if library stays dumb |
| **Scripts + agents** | Agents first; scripts secondary |

**Trap:** Becomes an SDK feature of one agent vendor, not infrastructure.  
**INTERPRETATION:** Viable **delivery vehicle**, weak as sole *definition*
unless paired with shared semantics (E).

---

## Cross-position comparison

| Question | Best fit | Worst fit |
|----------|----------|-----------|
| Model neutrality | E, A (attestation-only), F | D |
| Tool neutrality | E | B, single-backend C |
| Avoid agent product | E, C (narrow), F | D, A-if-planning |
| Avoid Playwright replacement | E, A | B, fat C |
| Adoption path short-term | C, F | E alone |
| Supports scripts and agents | E, C | D |
| Matches “universal layer” language | E (+ bindings) | D |
| EP-14 complexity control | Narrow C/F implementing E | D, fat A |

---

## Hybrid reality (INTERPRETATION)

In practice, infrastructure often ships as:

1. **E** — semantic contract (what “verified / blocked / uncertain” means)  
2. **C or F** — reference implementation beside existing automation  
3. **A** — optional adapter binding (e.g., MCP tool that calls attestation)—without replacing MCP

This is a packaging observation for later phases, **not** an implementation plan.

---

## Position vs candidate responsibilities

| Responsibility | Natural positions | Avoid |
|----------------|-------------------|-------|
| CR-2 Verification | E, C, F, A (post-tool) | D as owner of goals |
| CR-1 Sync / freshness | C/E near browser; experimental engine coop | Owning freeze browser (NG-03) |
| CR-5 Evidence | C (reuse traces), E schemas | New observability mega-product |
| CR-4 Recovery statuses | Emit at E/C; loop at host | D owning loop |
| CR-6 Privilege | A/C gates | Security mega-product |
| CR-7 Mediation | A/D | Entire Phase 2A direction |

---

## Comparison conclusion (still not the project recommendation)

- **D is incompatible** with non-goals as the primary seat of the project.  
- **B is structurally biased** toward becoming a Playwright wrapper.  
- **E best matches** universality and neutrality **and** carries adoption risk.  
- **C and F** are the practical seats for a reference capability **if** semantics stay narrow.  
- **A** is useful as a binding surface, dangerous as a planning intermediary.

Final stack-position recommendation is deferred to `PHASE_2A_RECOMMENDATION.md`
in light of the chosen responsibility.
