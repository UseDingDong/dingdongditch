# Success Semantics

**Phase:** 2A  
**Date:** 2026-07-25  
**Purpose:** Shared vocabulary for execution and success **before** architecture.  
**Rule:** Definitions are implementation-agnostic. No APIs, classes, or schemas here.

Epistemic boundary (FACT of the world, not a browser quirk):  
Browser-visible state is not identical to external reality.

---

## Core terms

### Intent

What the **user** wants accomplished, including constraints.  
Owned by the user (EP-13). Not invented by DingDongDitch (NG-09).

### Plan

A host-side sequence or strategy for pursuing intent.  
Owned by the AI reasoning host (NG-08). May be implicit.

### Command

A requested operation issued toward the browser stack (navigate, click, type,
assert, attest, …). May originate from AI, script, or human.

### Action

A concrete browser-side effect attempt (input event, navigation, script eval,
etc.) carried out by the automation framework / browser.

### Observation

A packaged projection of browser state at a time (a11y tree, DOM slice,
screenshot, network summary, console, dialog events, …).  
Observations are **lossy** (L02) and **age** (EP-03, L03).

### Observation epoch

The time interval / generation identifier associated with an observation.  
Actions and verifications may be bound to an epoch. If the world moves beyond
the epoch, dependent conclusions are suspect (G1).

### Evidence

Retained signals used to justify a verdict or postmortem (ordered artifacts
tied to commands/actions/expectations). Stronger than a lone screenshot (L09).

### State

Facts believed about the browser session or page at a moment (URL, auth class,
open tabs, pending download, …). Always provisional (EP-02).

### Expectation (declared outcome)

A **host-declared** claim about browser-observable conditions that would count
as progress or completion for a step.  
Examples of *kinds* (not an API): “URL matches X”, “text Y visible”, “request Z
returned 2xx”, “download completed”, “no challenge interstitial”.

DingDongDitch may evaluate expectations; it must not silently author the user’s
intent as expectations (NG-09). **UNRESOLVED (UB-1):** ergonomics of declaration.

### Progress

A verdict that a declared expectation for *advancement* holds, without
necessarily meaning the full intent is done.

### Verification / attestation

The process of evaluating expectations against evidence under freshness rules,
producing a verdict independent of “action threw / did not throw” (EP-01, EP-04).

### Recovery

Host-owned decisions after uncertainty or failure (retry, replan, reset, human).  
DingDongDitch may supply typed statuses that make recovery safer; it should not
silently own the recovery loop (see CR-4 judgment).

### Completion

The host’s (or user’s) determination that intent is satisfied.  
May incorporate attestation of final expectations plus human judgment.

### Confidence

A qualitative or quantitative expression of how strongly evidence supports a
verdict. Must not be confused with model self-confidence. **UNRESOLVED:** whether
numeric confidence is needed in v1 (EP-14).

### Uncertainty

A first-class outcome: evidence insufficient, conflicting, or epoch-invalid—
not a forced binary success/fail (L15 implication).

### Irreversible action

An action whose side effects are costly or hard to undo (submit payment, send
message, delete). Detection/gating may involve privilege policy (EP-09).  
Exact catalog **UNRESOLVED (UB-5/UB related)**.

### Blocked

A verdict that progress cannot continue for a classified reason (e.g., auth
challenge, permission prompt, hard error)—distinct from “failed click.”

### Needs-human

A verdict or signal that continuation requires human approval or challenge
completion (NG-07, L05).

---

## Ladder of success claims

From weakest to strongest claims about “what happened”:

| Level | Claim | Who can typically attest | Epistemic limit |
|-------|-------|--------------------------|-----------------|
| L0 | Command accepted | Adapter / runtime | Not browser truth |
| L1 | Command dispatched to automation | Adapter / framework | Not effect |
| L2 | Action performed without automation exception | Automation framework | Actionability ≠ correctness (L01) |
| L3 | Observable state changed | Attestation via evidence | Change ≠ intended change |
| L4 | Declared expectation holds now | Attestation | May be transient |
| L5 | Expectation remained stable over a quiescence window | Attestation (optional) | Still browser-local |
| L6 | Workflow stage advanced per declared stage map | Attestation + host stage defs | Host may be wrong about stages |
| L7 | User intent completed | User / host + final expectations | Social/business truth outside browser |
| L8 | External world fulfilled (e.g., merchant ships) | Outside this system | **Not attest-able from browser alone** |

### What DingDongDitch could responsibly attest (INTERPRETATION for Phase 2A)

**In-scope candidates:** L3–L5 primarily; L6 only if stage expectations are
explicitly declared by the host.  

**Out of scope:** L8 always. L7 only as “final declared expectations hold,”
never as mind-reading the user.

### Example epistemic boundary

| Browser evidence | Responsible claim | Irresponsible claim |
|------------------|-------------------|---------------------|
| Page shows “Order confirmed” | Text matching declared expectation was present in epoch E | “The order will ship” |
| `POST /checkout` returned 200 | Network expectation held | “Payment captured and settled” |
| Click threw no error | L2 action completed | “Item added to cart” without L3/L4 checks |

---

## Relationships (conceptual)

```
Intent → Plan → Command → Action
                      ↓
              Observation(s) + Evidence
                      ↓
              Expectation evaluation (attestation)
                      ↓
         Verdict: progress | no-progress | blocked |
                  uncertain | needs-human | epoch-invalid
                      ↓
              Host: complete | recover | replan | ask user
```

---

## Anti-definitions (forbidden collapses)

| Collapse | Why forbidden |
|----------|---------------|
| Action success = progress | EP-01, A4, F10 |
| Observation = complete page truth | L02, A1 |
| Screenshot = sufficient evidence | L09, A11 |
| Model says done = completion | NG-09, EP-13, EP-09 |
| No exception = verified | L01 |

---

## Open semantic questions

| ID | Question |
|----|----------|
| SS-1 | Is quiescence (L5) mandatory for consequential actions or optional? |
| SS-2 | How are conflicting signals represented (DOM yes, network no)? |
| SS-3 | Is “epoch-invalid” distinct from “uncertain”? (likely yes) |
| SS-4 | Multi-expectancy: all-of vs any-of progress rules—host-declared only? |
