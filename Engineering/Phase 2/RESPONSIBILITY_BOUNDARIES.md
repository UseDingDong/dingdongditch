# Responsibility Boundaries

**Phase:** 2A  
**Date:** 2026-07-25  
**Governed by:** `ENGINEERING_PRINCIPLES.md`, `NON_GOALS.md`  
**Research anchors:** L07, L01, L11, L13, G2, G3, G8, G10

This document assigns ownership of concerns across actors.  
Where ownership is disputed or evidence-thin, it is marked **UNRESOLVED**.

**INTERPRETATION note:** Boundaries below were initially drafted around an
attestation-centric working boundary. After the 2026-07-26 challenge, the
recommended identity is a **plan-consuming execution runtime** with mandatory
attested receipts. See `PHASE_2A_RECOMMENDATION.md` and
`CHALLENGE_ATTESTATION_VS_EXECUTION_RUNTIME.md`. Actor splits below remain valid;
DingDongDitch ownership expands to include plan execution faculties under the
fences in those docs.

---

## Actor map

| Actor | Role in one sentence |
|-------|----------------------|
| **User** | Defines the objective and acceptable risk |
| **AI reasoning host** | Interprets intent, plans, selects candidate actions |
| **DingDongDitch** | Plan-consuming browser execution runtime: observe/act via backends, bounded verify/recover, attested receipts *(amended 2026-07-26)* |
| **Tool adapter** | Exposes browser capabilities to the host (MCP/CLI/SDK) |
| **Automation framework** | Drives the browser (clicks, waits, routes, contexts) |
| **Browser** | Renders, executes page JS, enforces web platform security |
| **Website / application** | Owns server truth, auth policy, anti-abuse, business rules |
| **Human approval layer** | Resolves challenges, irreversible actions, ambiguous goals |

---

## Detailed ownership

### User owns

- The goal and constraints (EP-13, NG-09)  
- Which accounts/sessions may be used  
- Risk tolerance for irreversible actions  
- Final acceptance of outcomes when automation stops at uncertainty  

**Does not own:** Low-level click sequencing (may defer to AI).

### AI reasoning host owns

- Natural language understanding and planning (NG-08)  
- Choosing *what* to attempt next  
- Declaring **expected observables** when asking for attestation (if using DingDongDitch)  
- Whether to continue, replan, or stop after a verdict  
- Model selection and prompt policy  

**Does not own:** Ground-truth browser physics; must not be the sole verifier of its own safety-critical claims (EP-09 tension if self-judging).

### DingDongDitch owns (attestation-centric working boundary)

- Evaluating **declared** browser-observable expectations against fresh evidence  
- Returning typed verdicts (e.g., progressed / not progressed / blocked / uncertain / evidence-insufficient)  
- Bundling goal-linked evidence for those verdicts  
- Refusing to treat automation exceptions alone as task progress (EP-01)  
- Signaling states that require human handling when detected as such  

**Does not own:**

- Inventing the user’s goal or success criteria (NG-09)  
- Planning or natural-language reasoning (NG-08)  
- Replacing Playwright/Puppeteer/Selenium (NG-04)  
- Replacing MCP (NG-05)  
- Solving CAPTCHAs or bypassing security (NG-07)  
- Rendering pages (NG-03)  
- Being a chatbot (NG-02)  
- Business workflow authoring (NG-06)  

### Tool adapter owns

- Tool schema exposure to hosts  
- Transport of commands and snapshots  
- Session wiring to an automation backend  

**Does not own:** Semantic meaning of “task success” (today often wrongly implied by tool OK—this is the gap G2).

### Automation framework owns

- Actionability waits, selectors/locators, contexts, tracing primitives  
- Cross-frame APIs, network interception, storageState mechanisms  
- Browser protocol differences behind a library API  

**Does not own:** Agent goal oracles (unless the engineer wrote `expect` in a test).

### Browser owns

- DOM, rendering, JS execution, cookies, process isolation, permission prompts  
- Platform security (same-origin, etc.)  

**Does not own:** Whether an automation caller’s *business* goal succeeded.

### Website / application owns

- Server-side state and fulfillment  
- Auth, MFA, bot scoring, rate limits  
- What UI text means operationally (“Order confirmed” copy)  

**Does not own:** Client automation correctness.

### Human approval layer owns

- Completing CAPTCHA/2FA when required (L05, NG-07)  
- Approving irreversible actions (payments, deletes, sends)  
- Clarifying ambiguous user goals  

---

## Authority begin / end (DingDongDitch)

| Begins | Ends |
|--------|------|
| After a host (or script) declares an expectation or requests attestation | Before choosing the next plan step |
| When browser observables and action receipts are available | Before claiming off-browser reality (fulfillment, legal truth) |
| When freshness of evidence can be assessed | Before silently continuing past `blocked` / `needs-human` |
| When packaging evidence for a verdict | Before becoming the system of record for user intent |

---

## Mandatory role separation (do not merge)

```
User defines goal
    → AI interprets & plans
        → Automation acts
            → Attestation evaluates declared browser-observable claims
                → Host decides next plan / stop / human
```

Merging “plans” with “attests” recreates agent products (NG-08, G10).  
Merging “acts” with “attests” without independence recreates tool-OK false confidence (L15).

---

## What requires human approval / intervention

**EVIDENCE-backed categories:**

- Auth handoff on hostile platforms (L05)  
- CAPTCHA / managed challenges (F8, NG-07)  
- High-impact irreversible actions (production guidance across surveys)  
- Ambiguous goals the user did not specify (EP-13)  

**UNRESOLVED:** Exact irreversible-action taxonomy for v1 (payment? form submit? email send?) — defer to later phase with evidence; do not invent a full policy engine now (EP-14).

---

## Unresolved boundaries

| ID | Question | Why unresolved |
|----|----------|----------------|
| UB-1 | Who authors expectation declarations when the host is a weak coder agent? | Adoption UX; risk of DingDongDitch inventing oracles (NG-09) |
| UB-2 | May DingDongDitch use a *separate* model as a verifier aid? | Independence vs EP-07; contamination risk; UNKNOWN best practice |
| UB-3 | How much session state may DingDongDitch retain across turns? | EP-02 vs usefulness; NG-06 creep |
| UB-4 | Are domain allowlists in-scope for v1 or host-owned? | EP-09 vs security-product trap |
| UB-5 | Does “progressed” require stability over time (quiescence)? | SUCCESS_SEMANTICS; needs experiments |
| UB-6 | Multi-tab attestation scope | F12; complexity (EP-14) |

---

## Boundary anti-patterns

| Anti-pattern | Violation |
|--------------|-----------|
| “We’ll just have the same LLM confirm success from a screenshot” | Weak independence; EP-09 for safety-critical; L15 |
| “We’ll infer what the user meant and mark complete” | NG-09, EP-13 |
| “We’ll retry until the page looks right” | G6/L13; may own recovery loop |
| “We’ll solve login inside the layer” | NG-07, NG-06 risk |
| “We’ll expose click/type as our main API” | NG-04 |
