# Phase 2A Recommendation

**Status:** Amended after challenge (2026-07-26)—definition for validation, not architecture  
**Date:** 2026-07-25 (initial) · **Amended:** 2026-07-26  
**Challenge record:** [`CHALLENGE_ATTESTATION_VS_EXECUTION_RUNTIME.md`](./CHALLENGE_ATTESTATION_VS_EXECUTION_RUNTIME.md)

---

## Recommended single responsibility (one sentence)

**DingDongDitch is a model-neutral browser execution runtime for externally
planned tasks:** it observes and acts through existing automation backends,
applies bounded verification and bounded recovery, and returns structured
attested evidence—without inventing goals, performing autonomous planning,
replacing Playwright, or becoming a goal-taking browser agent.

Shorthand: **plan-consuming browser execution runtime** (attested receipts mandatory).

### Relationship to the prior (attestation-only) recommendation

The 2026-07-25 attestation-only definition (Candidate A) is **not discarded**.
It remains the **correctness core**: every consequential execution receipt must
attest host-declared browser-observable expectations under freshness
constraints (EP-01, EP-04).

What changed: attestation-only is judged **insufficient as the sole product
boundary** because it is off the critical path and structurally skippable
(challenge §5; V-A2; optional `verify_*` evidence).

Narrowness alone is not a valid selection criterion when it produces
infrastructure nobody must invoke.

---

## Exact stack position

| Primary | Delivery | Forbidden as identity |
|---------|----------|------------------------|
| **Plan-consuming execution runtime** between AI host (planner) and automation backends | Backends: Playwright/Puppeteer/Selenium/CDP as **replaceable implementations** (EP-08) | Goal-taking **agent** runtime; Playwright **replacement** API; MCP **replacement** product |
| Semantic export: attested receipts (Candidate A vocabulary) | Optional bindings (MCP/CLI) that submit plans / return receipts | Observability-only product; recovery-as-planner |

**Correction to prior analysis:** Phase 2A previously rejected “Position D”
wholesale. The challenge distinguishes **goal-taking agent runtimes** (reject)
from **plan-consuming execution runtimes** (this recommendation). See challenge §1.

---

## What the project owns

- Accepting **externally supplied** browser plans (actions + declared expectations + recovery bounds)  
- Browser **observation** sufficient for honest execution and verification  
- Browser **action dispatch** through automation backends  
- **Bounded verification** as part of execution receipts (not optional sidecar)  
- **Bounded recovery** within declared limits (retry/stop/handoff—not autonomous replanning)  
- **Structured evidence** justifying verdicts (EP-11)  
- Freshness / epoch honesty for observe→act→verify (EP-02, EP-03)

## What the project refuses to own

| Refusal | Non-goal / principle |
|---------|----------------------|
| Being an AI model or autonomous planner | NG-01, NG-08, EP-07 |
| Accepting raw goals and “just getting it done” | NG-08, NG-09, T1 |
| Chatbot UX as purpose | NG-02 |
| Browser engine | NG-03 |
| Playwright/Puppeteer/Selenium replacement | NG-04 |
| MCP replacement | NG-05 |
| RPA / workflow platform | NG-06 |
| CAPTCHA / security bypass | NG-07 |
| User intent authorship | NG-09, EP-13 |
| Vendor lock-in as architecture | NG-10, EP-08 |
| Demo-first / agent-cosplay roadmap | NG-11, EP-12 |
| Off-browser fulfillment truth | Success semantics L8 |
| LLM context/token optimization as product | G4 wrong owner |
| Frame-piercing engine as identity | NG-04, NG-12 |
| Peer product lines for obs / verify / recover / drive | Bundle failure mode (challenge §4) |

---

## Coherence ruling (single responsibility vs bundle)

**Ruling:** This is **one coherent responsibility**—*reliably execute externally
planned browser work and return attested receipts*—**if and only if**
observation, action, verification, recovery, and evidence remain faculties of
that single contract.

It is **several unrelated products** if those faculties become independent
destinations.

Full argument: challenge §4.

---

## Why this boundary is supported by research

### Established facts / strong evidence

- Actionability ≠ correctness (**FACT**; L01).  
- Agents treat tool success as progress (**PATTERN**; A4, L15, F10).  
- Optional verification is underspecified and skippable (**EVIDENCE**; G2; MCP `verify_*`).  
- Stale observation races deliberating models (**EVIDENCE/PATTERN**; G1, L03).  
- Ad hoc recovery causes harm (**EVIDENCE**; G6, L13, F8).  
- Reliability gaps sit between layers, not in missing click APIs (**PATTERN**; stack layers).  
- Field demand is infrastructure-shaped (**PATTERN**; developer feedback).

### Interpretation (labeled)

- Closing G1+G2+G6+G7 **for a plan** is one runtime job, not four markets—when
  subordinated to plan→receipt.  
- Candidate A alone optimizes principle purity at the expense of on-path
  usefulness—the strongest prior objection to A is structural.  
- Candidate E (unfenced full suite) remains rejected; F is E with planning and
  goal-taking removed and a single I/O contract imposed.

---

## Strongest arguments against this recommendation

1. **NG-04 / T2 drift:** Owning “execution” slides into a Playwright wrapper.  
2. **NG-08 / T1 drift:** “Bounded recovery” slides into autonomous replanning.  
3. **EP-14:** Broader surface may not earn its complexity vs a thinner attest library—if adopters would have used A.  
4. **NG-12:** May duplicate “Browser Use with the planner ripped out.”  
5. **Empirical UNKNOWN:** Q9 may show planning/auth dominate; runtime semantics may not be the bottleneck.

These are load-bearing risks, not dismissals. Invalidation conditions below.

---

## Assumptions that must be validated

| ID | Assumption | If false |
|----|------------|----------|
| V-F1 | A plan→receipt runtime is adoptable by AI hosts without DingDongDitch planning | F is unwanted; consider A or integrate into existing agents |
| V-F2 | Bounded recovery can be specified without model calls that invent steps | F violates NG-08; narrow recovery or revert |
| V-F3 | Public API can stay plan/receipt-centric while using Playwright as backend | NG-04 failure; stop |
| V-F4 | Mandatory attestation in receipts improves honesty vs action-OK baselines | Core EP-01 value missing |
| V-F5 | False-progress and sync/recovery gaps are material on labeled failures (Q9) | Wrong problem emphasis |
| V-A2 (retained) | Hosts will not reliably call optional attestation | Supports F over A; if false, A may suffice |

---

## Minimum experiments before architecture (Phase 2B gate)

Retain prior probes where relevant; add F-specific fences:

1. **Failure labeling pilot (Q9)** — same as before.  
2. **Signal sufficiency / attestation value probe** — same as before (V-F4).  
3. **Plan→receipt paper protocol:** Without writing production code, specify on
   paper a minimal plan schema + receipt schema + recovery bounds that contain
   **zero** autonomous planning. Red-team for NG-08 leaks.  
4. **NG-04 API red team:** List intended public verbs; fail if click/fill/goto
   dominate over submit-plan / await-receipt.  
5. **Recovery bound tabletop:** Enumerate allowed recovery behaviors; any that
   require “choose a new action to achieve the goal” → reject.  
6. **Adopter interviews** using *both* one-sentence definitions (A vs F); ask
   which they would adopt and why.  
7. **Differentiate from Browser Use:** One-page comparison: external planner +
   attested receipts vs autonomous agent loop—what shared code would be wrong
   to duplicate (NG-12)?

**Do not** start language choice, package layout, or implementation until
V-F2/V-F3 paper fences pass and Q9-related labeling is underway (EP-06, NG-13).

---

## Confidence level

**Medium (≈ 55–70%).**

| Supports | Limits |
|----------|--------|
| Stronger on-path infrastructure logic than A | Higher trap surface than A |
| EP-01/04/05 enforceable inside runtime | Recovery/API fences unproven |
| Coherence argument via single I/O contract | Opportunity still SPECULATION |
| Corrects over-broad Position D rejection | May still collapse into agent/wrapper in practice |

Confidence is in **definitional coherence under fences**, not shipping success.

---

## Conditions that invalidate this recommendation

- Bounded recovery cannot be defined without autonomous planning → amend or revert toward A.  
- Inevitable public surface is a Playwright competitor → NG-04; stop.  
- Adopter evidence prefers skippable attestation library → A may win.  
- Indistinguishable from existing agent frameworks minus LLM → NG-12; integrate.  
- Failure labeling shows other gaps dominate and F would not address them.  
- Project demos become goal-taking agents despite fences → governance failure; halt.

---

## Browser-only vs universal GUI

Unchanged: **browser-only** for the first life of the definition (Trap T11, EP-14).

---

## Explicit non-claims

This recommendation does **not** architect the system, select languages,
define wire schemas as final, or claim market proof.

---

## Change log

| Date | Change |
|------|--------|
| 2026-07-25 | Initial recommendation: attestation-only (Candidate A) |
| 2026-07-26 | Challenge amends identity to plan-consuming execution runtime (Candidate F); A retained as mandatory receipt semantics |

---

## Traceability

| Claim | Points to |
|-------|-----------|
| Challenge argument | `CHALLENGE_ATTESTATION_VS_EXECUTION_RUNTIME.md` |
| Prior A definition | `PROJECT_DEFINITION_CANDIDATES.md` Candidate A |
| Coherence / bundle test | Challenge §4 |
| Success vocabulary | `SUCCESS_SEMANTICS.md` |
| Traps T1/T2 | `SCOPE_TRAPS.md` |
| Gaps | G1, G2, G6, G7 |
