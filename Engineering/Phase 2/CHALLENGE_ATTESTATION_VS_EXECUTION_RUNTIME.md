# Challenge: Attestation-Only (A) vs Plan-Consuming Execution Runtime (F)

**Phase:** 2A challenge addendum  
**Date:** 2026-07-26  
**Status:** Challenge complete; amends Phase 2A recommendation  
**Rule:** Do not prefer Candidate A because it is narrower. Do not prefer
Candidate F because it sounds more useful. Prefer the stronger long-term
infrastructure boundary that still justifies existence.

---

## 1. The new candidate (F)

### One-sentence definition

**DingDongDitch is a model-neutral browser execution runtime for externally
planned tasks:** it performs browser observation and browser actions (via
existing automation backends), applies bounded verification and bounded
recovery, and returns structured evidence—without inventing goals, performing
autonomous planning, replacing Playwright, or becoming a goal-taking browser
agent.

### Ownership split (as stated)

| Owns | Does not own |
|------|----------------|
| Browser execution (dispatch through backends) | User goals / intent authorship |
| Browser observation (packaging for execution honesty) | Autonomous planning / replanning of goals |
| Bounded verification | Being an AI model |
| Bounded recovery | Replacing Playwright/Puppeteer/Selenium |
| Structured evidence return | Chatbot product; RPA platform; CAPTCHA solving |

### How F differs from rejected Candidate E (“full reliability suite”)

| | Candidate E (rejected) | Candidate F (this challenge) |
|--|------------------------|------------------------------|
| Input | Ambiguous (goals and/or everything) | **Externally planned tasks** only |
| Planning | Implicitly absorbed | **Explicitly forbidden** |
| Coherence claim | Bundle of gaps | Single runtime I/O: plan → attested receipt |
| Mediation (CR-7) | Yes | Only mechanical execution of supplied plans |

### How F differs from rejected Position D in Phase 2A

Phase 2A treated Position D as “host-controlled execution runtime” that owns
turn-taking and **possibly planning hooks**, and marked it incompatible with
non-goals.

**Challenge finding:** That rejection **over-collapsed** two different runtimes:

1. **Goal-taking agent runtime** — accepts goals, plans, acts (T1 / NG-08) — correctly rejected.  
2. **Plan-consuming execution runtime** — accepts plans/actions from an external reasoner, executes them honestly — not automatically an agent.

Candidate F is (2), not (1). Phase 2A’s blanket rejection of “execution runtime”
was therefore **too coarse** (**INTERPRETATION** correcting prior analysis).

---

## 2. Does F satisfy Engineering Principles?

| Principle | Verdict for F | Notes |
|-----------|---------------|-------|
| EP-01 Execution ≠ task success | **Satisfies if** verification is mandatory on consequential steps, not optional sidecar | Stronger than A: runtime can refuse to report “success” on action-OK alone |
| EP-02 Never assume browser state | **Satisfies** if observation is continuous duty of the runtime | Natural fit |
| EP-03 Observation ages quickly | **Satisfies** if runtime binds act to fresh observation epochs | Better enforced when runtime owns both observe and act |
| EP-04 Verification first-class | **Satisfies** when verification is part of the execution receipt, not a skippable tool | Fixes A’s structural skip risk |
| EP-05 Recovery part of execution | **Satisfies** for *bounded* recovery | Key fence: recovery ≠ autonomous replanning |
| EP-06 Evidence before assumptions | Neutral | Validation still required |
| EP-07 AI replaceable | **Satisfies** | Planner is external; any model/script can supply plans |
| EP-08 Engines replaceable | **Satisfies if** Playwright/CDP are backends, not identity | Harder than A; discipline required |
| EP-09 Security is architecture | **Partial** | F can host gates; must not become security product (T6) |
| EP-10 Determinism valuable | **Satisfies** | Deterministic plan replay is a natural runtime feature |
| EP-11 Observability mandatory | **Satisfies** | Evidence is an output of execution |
| EP-12 Infrastructure not demos | **Conditional** | Runtime demos tempt agent cosplay—governance required |
| EP-13 User owns the goal | **Satisfies** | Goals stay outside |
| EP-14 Complexity earns existence | **Tension** | Broader surface; justified only if faculties serve one I/O contract |
| EP-15 Research never ends | Neutral | This challenge is an instance |

**EP summary:** F can satisfy the principles **conditionally**. The load-bearing
conditions are: (1) verification non-optional in the receipt, (2) recovery
cannot invent plans, (3) automation libraries remain backends, (4) complexity
stays subordinated to one contract.

---

## 3. Does F satisfy Non-Goals?

| Non-goal | Verdict for F | Load-bearing fence |
|----------|---------------|-------------------|
| NG-01 Not an AI model | **OK** | No embedded planner required for core path |
| NG-02 Not a chatbot | **OK** | UI not purpose |
| NG-03 Not a browser | **OK** | Uses engines |
| NG-04 Not an automation framework | **OK only if** public responsibility is plan→receipt, not a competing locator/auto-wait API | If primary API is `click`/`fill` clone → **fails NG-04** (T2) |
| NG-05 Not MCP replacement | **OK** | MCP may bind to F; F is not “the MCP” |
| NG-06 Not RPA | **OK if** no workflow-builder product scope | Plan format ≠ SOP platform |
| NG-07 Not CAPTCHA solver | **OK** | Classify/stop/handoff only |
| NG-08 Not AI reasoning | **OK iff** “bounded recovery” excludes goal-level replanning and open-ended “figure out another way” | Local retry of *declared* step recovery is OK; inventing new steps is not |
| NG-09 Not user intent | **OK** | External plans carry interpreted intent from AI/user |
| NG-10 Not vendor-specific | **OK with multi-backend ambition** | Chromium-only forever weakens this |
| NG-11 Not demo-optimized | **At risk** | Runtime demos easily become agent demos |
| NG-12 Not everything | **At risk** | Must refuse obs-platform, security-suite, token-optimizer identities |
| NG-13 Research before expansion | Neutral | Applies to any growth of “bounded” |

**NG summary:** F is **compatible with non-goals only under explicit fences**.
It is **not** automatically compliant merely by asserting “we don’t plan.”

---

## 4. Central question: one responsibility or a bundle?

### Thesis under test

Is “reliable browser execution” for externally planned tasks a **single coherent
responsibility**, or **several unrelated products** (observe + drive + verify +
recover + evidence) glued by marketing?

### Argument that it is one coherent responsibility

**INTERPRETATION (infrastructure analogy):**

Runtimes routinely own multiple *faculties* under one contract:

- A database runtime: execute statements, observe state, verify constraints,
  recover transactions, emit logs.  
- An OS process runtime: load, run, isolate, signal, wait.  
- A CI runner: execute steps, capture artifacts, retry policy, status.

The coherence test is not “one mechanism” but **one I/O boundary**:

```
external plan (actions + expectations + recovery bounds)
        ↓
   DingDongDitch runtime
        ↓
attested receipt (observations + verdicts + evidence + terminal status)
```

Under that contract:

- Observation exists so execution is not blind and verification is not stale.  
- Verification exists so receipts are not lies (EP-01).  
- Bounded recovery exists so transient execution faults do not require a full
  AI round-trip for every flake—without transferring planning.  
- Evidence exists so receipts are auditable (EP-11).

These are **not independent product bets**; they are **necessary faculties of
honest plan execution**. Removing any one breaks the contract:

| Remove | Contract failure |
|--------|------------------|
| Execution | Nothing to run; becomes Candidate A again |
| Observation | Acts and verifies on fiction (G1) |
| Verification | Returns action-OK theater (G2, L15) |
| Bounded recovery | Every flake escalates to planner; or silent infinite retry (G6/L13) |
| Evidence | Unexplainable runtime (EP-11) |

**PATTERN from Phase 1:** Reliability failures sit in policy gaps *between*
observe/act/verify/recover—not in missing click APIs. A runtime whose job is
to close those gaps *for a plan* is addressing one job, not five markets.

### Argument that it is a bundle

| Faculty | Can be a separate product | Drift signal |
|---------|---------------------------|--------------|
| Observation packaging | LLM-context / snapshot product (G4) | Token optimization roadmap |
| Execution dispatch | Playwright wrapper (NG-04) | Click/fill as flagship API |
| Verification | Attestation SaaS (Candidate A) | Verify without execute |
| Recovery | Policy engine / agent harness | Autonomous replan |
| Evidence | Observability platform (T8) | Traces without verdicts |

If org structure, APIs, or docs split along these lines as **peer products**,
F has decomposed into a bundle.

### Verdict on coherence

**Candidate F is a single coherent responsibility *if and only if* all owned
capabilities are subordinated to one contract: execute externally supplied
browser plans and return attested receipts.**

It is **several unrelated products** as soon as any faculty is pursued as an
independent destination (obs platform, verify API without execution, recovery
brain, driver replacement).

This is a **governance property**, not an automatic gift of the broader wording.

Compare Candidate A: A is also “one” responsibility, but a **weaker
infrastructure boundary**—optional correctness checking beside someone else’s
execution path.

---

## 5. Head-to-head: A vs F (not favoring narrowness)

| Criterion | Candidate A (attestation) | Candidate F (plan-consuming runtime) |
|-----------|---------------------------|--------------------------------------|
| **Long-term boundary clarity** | Very clear: attest only | Clear *if* plan→receipt held; blurrier under pressure |
| **Usefulness / reason to exist** | Weak structural adoption (skippable) — **EVIDENCE** from optional verify_* | Stronger: hosts must go through it to act in-browser |
| **Closes G2 false progress** | Yes, when used | Yes, when receipts mandatory |
| **Closes G1 stale act** | Constraint only | Can enforce observe/act coupling |
| **Closes G6 harmful recovery** | Status vocabulary only | Can enforce budgets/stop — **or** become agent |
| **NG-04 risk** | Low | **High** without API discipline |
| **T1 agent risk** | Low | **Medium–high**; fence = no autonomous planning |
| **EP-14 complexity** | Lower | Higher; needs stronger EP-14 justification |
| **Duplication of Playwright** | Low | Medium (must use, not replace) |
| **Duplication of Browser Use** | Low | Medium—difference is external planning + attested receipts |
| **Fits “infrastructure between AI and tools”** | Side-car | **On-path** execution layer |
| **Justifies existence if hosts are lazy** | Poor (V-A2) | Better |
| **Justifies existence if hosts are disciplined** | Weaker (they can self-assert) | Still stronger shared semantics for plans/receipts |

### The mistake in preferring A for narrowness alone

Phase 2A used “smallest responsibility” as a proxy for “best infrastructure.”
That proxy fails when the smallest unit is **off the critical path**.

Infrastructure that can be bypassed often is (**EVIDENCE**: optional
verification tools; agents optimizing for tool-OK).  

Narrowness is valuable when it prevents trap absorption (EP-14). It is harmful
when it defines a component nobody must invoke.

### The mistake in preferring F for usefulness alone

Usefulness without fences recreates Position D / Browser Use with different
branding. “Bounded recovery” is the primary leak toward NG-08.

---

## 6. What “bounded recovery” must mean (or F fails)

To keep F as one responsibility and NG-compliant, bounded recovery **may**:

- Retry a **declared** action under declared limits  
- Re-observe and re-check a **declared** expectation  
- Stop and return `blocked` / `needs-human` / `uncertain`  
- Apply host-supplied recovery directives embedded in the plan  

Bounded recovery **must not**:

- Invent new actions to achieve the goal another way  
- Call an LLM to replan  
- Expand scope to “just get it done”  
- Solve CAPTCHAs (NG-07)

If recovery requires a model call to decide *what else to try*, planning has
leaked into DingDongDitch—F collapses into an agent (T1).

**UNRESOLVED:** Exact recovery primitive set—validation topic, not architecture
yet.

---

## 7. What “owns browser execution” must mean (or F fails NG-04)

Allowed reading:

- DingDongDitch **orchestrates** automation backends to realize plan steps.  
- Playwright/Puppeteer/Selenium/CDP remain the **libraries/protocols**.  
- Public identity: plan execution + attested receipts.

Forbidden reading:

- DingDongDitch is the new locator/auto-wait framework.  
- “Compatible with Playwright” meaning “reimplements Playwright.”  

Detection question (from T2): *Are we known for attested plan receipts, or for
a better click API?*

---

## 8. Challenge conclusion

### On EP/NG

**Candidate F can satisfy Engineering Principles and Non-Goals**, but only as a
**fenced plan-consuming runtime**, not as an unbounded “reliability platform.”

### On single vs many products

**It is still a single coherent responsibility** (“reliably execute externally
planned browser work and return honest receipts”) **when faculties are
contract-subordinated**.

**It becomes a bundle** when observation, driving, verification, recovery, and
evidence are peer product lines.

### On A vs F for long-term infrastructure

| Winner | Dimension |
|--------|-----------|
| **F** | On-path usefulness; ability to enforce EP-01/03/04/05; justification for existence |
| **A** | Lower trap surface; easier NG-04 compliance by default |
| **A’s semantics** | Remain the *heart* of F’s receipts—not discarded |

**INTERPRETATION — amended recommendation:**  
Prefer **Candidate F** as the project identity, with **Candidate A’s attestation
semantics mandatory inside every execution receipt**.  

Phase 2A’s attestation-only definition remains valuable as the **correctness
core**, but is **insufficient as the sole product boundary** because it is
structurally skippable.

Confidence in this amendment: **medium** — stronger on logic of infrastructure
on-pathness; still weak on empirical Q9 and on whether adopters want a
plan-consuming runtime vs baking it into Browser Use-class agents.

---

## 9. Invalidation conditions for preferring F

- “Bounded recovery” cannot be specified without a planner → revert toward A or reject F.  
- Reference designs inevitably expose a Playwright-replacement API as the main surface → NG-04 failure; stop.  
- Adopters only want verify middleware, not plan execution → A may win after all.  
- Indistinguishable in practice from Browser Use with `llm=` removed → NG-12 integrate rather than reinvent.  

---

## 10. Traceability

- Prior recommendation: `PHASE_2A_RECOMMENDATION.md` (amended by this challenge)  
- Prior Position D rejection: `STACK_POSITION_ANALYSIS.md` (over-collapsed; corrected here)  
- Traps: `SCOPE_TRAPS.md` T1, T2  
- Principles/Non-goals: `../ENGINEERING_PRINCIPLES.md`, `../NON_GOALS.md`  
- Gaps: G1, G2, G6, G7  
