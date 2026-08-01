# Gap Dependency Map

**Phase:** 2A  
**Date:** 2026-07-25  
**Sources:** `Research/Architecture/RECURRING_GAPS.md`, `Failure Analysis/RECURRING_ISSUES.md`, Lessons L01–L15

This map separates **foundational** gaps from **downstream** symptoms and
shows interactions. It is an **INTERPRETATION** of Phase 1 evidence, not a
causal proof. Conflicts and independent branches are preserved.

Epistemic note: Without Q9 labeled failure frequencies, relative weight of
branches remains **UNKNOWN**. Structure below is qualitative.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| `[FOUND]` | Treated as foundational for browser-agent reliability failures |
| `[DOWN]` | Frequently caused or worsened by upstream gaps |
| `[EXT]` | Largely external to an execution-attestation layer |
| `[META]` | Evaluation / product-architecture meta-problem |
| `→` | Often contributes to |
| `<->` | Bidirectional interaction |

---

## Text diagram — primary reliability chain

```
[FOUND] G1  Observation/action desynchronization
            (stale or incomplete world model at act time)
                 |
                 |  also independently:
                 |  [FOUND] incomplete grounding (G5 frames/shadow)
                 |           and lossy channels (A1/L02)
                 v
        Incorrect or mistimed action targeting
                 |
                 v
[FOUND] G2  Verification underspecified
            (tool/action OK treated as progress)
                 |
                 +-----> False execution confidence  (F10, L15)
                 |
                 v
[DOWN]  G6  Ad hoc recovery
            (retry / replan without typed stop)
                 |
                 +-----> Harmful loops (F8 challenge escalation)
                 |
                 v
        Repeated failure / poisoned session / irreversible duplicate side effects


[FOUND] G2 also fires WITHOUT G1:
        Correct element clicked; server rejects; UI lies; wrong item still "successful click"
        → False progress with perfect sync
```

**INTERPRETATION:** G1 and G2 are **sibling foundations**. Sync-only fixes do
not eliminate G2. Verify-only without freshness produces confident wrong
verdicts (G1 corrupts G2). Honest attestation needs both.

---

## Evidence branch (supports foundations; not a separate root product)

```
[FOUND] G2 Verification needs evidence
[FOUND] G1 Sync honesty needs evidence of epoch change
                 |
                 v
[DOWN]  G7  Incomplete evidence packs
            (screenshots-only, missing dialogs/network/console)
                 |
                 +-----> Weak postmortems
                 +-----> Weak independent verification
                 +-----> “Recovery by eyeballing”
```

**INTERPRETATION:** G7 is **supporting infrastructure** for G1/G2/G6, not the
narrowest primary identity (observability-platform trap).

---

## External / policy branches (must not be absorbed casually)

```
[EXT] G3  Auth / step-up / bot challenges outside happy path
         |
         +-----> Appears inside agent loops as “obstacles”
         +-----> Without classification → feeds G6 harmful recovery
         |
         v
      Correct treatment for DingDongDitch scope:
      detect / classify / stop / handoff signals
      NOT solve (NG-07)


[EXT] G8  Security boundaries lag capability (prompt injection)
         |
         +-----> Orthogonal to “did the UI advance?”
         +-----> May gate irreversible actions
         |
         v
      Companion concern (EP-09); different product if primary


[EXT] G5  Frame/shadow/cross-origin grounding
         |
         +-----> Worsens G1 (incomplete observation)
         +-----> Largely automation-library territory (NG-04, NG-12)


[EXT] G4  Context/token explosion
         |
         +-----> Host/MCP/transport problem (L04)
         +-----> Side-effect of naive “always dump page into model”
         |
         v
      Not DingDongDitch primary ownership
```

---

## Meta branches

```
[META] G9  Benchmarks diverge from production hardness
          → False confidence in architecture choices (L10)
          → Does not define product responsibility


[META] G10 Who owns the control loop / missing universal semantics
          → Explains why many partial fixes don’t compose
          → Temptation to build CR-7 full mediator (rejected as primary)
          → A narrow attestation contract is one possible semantic island
             without owning the whole loop (INTERPRETATION)
```

---

## Failure-class mapping onto the map

| Failure | Role on map |
|---------|-------------|
| F2 Stale observation | Direct instance of G1 |
| F1 Timing / readiness | Mix of automation waits + G2 (actionability≠correctness) |
| F3 Selector invalidation | Downstream of mutation; related G1/G5 |
| F4 Frames/shadow | Instance of G5 → worsens G1 |
| F5 a11y insufficiency | Observation channel limit → incomplete evidence for G2 |
| F6 Token exhaustion | G4 |
| F7 Auth fragility | G3 |
| F8 Challenge loops | G3 × G6 |
| F10 False progress | Core G2 symptom |
| F11 Dialog/download blindness | G7 / evidence incompleteness |
| F12 Multi-tab loss | State tracking branch; worsens G1/G2 |
| F14 Prompt injection | G8 |
| F15 storageState poisoning | Session state branch under G3/EP-02 |

---

## Root vs symptom answers (required analyses)

### Is weak recovery a root problem?

**Mostly downstream (INTERPRETATION).**  
G6 worsens outcomes but typically fires because systems lack typed verification
outcomes and challenge classification. Recovery-without-verification repeats
blind actions (L13).  
**Exception:** Even with good verification, someone must own stop/handoff
policy—that ownership belongs to the **host/product**, not necessarily
DingDongDitch.

### Is context-window explosion this project’s responsibility?

**No as primary (EVIDENCE + NG-05).**  
G4/F6/D1 are transport and host-memory design issues. An attestation layer
should avoid requiring full page dumps into the model; it should not become an
MCP replacement to “fix tokens.”

### Is authentication failure an execution problem?

**Mixed.**  
Session expiry mid-task is browser/session reality (EP-02). Completing login /
solving CAPTCHA is **policy + human/workflow** (G3, NG-07, L05).  
DingDongDitch-relevant slice: recognize blocked/auth-challenge states and refuse
false “progress” verdicts—not complete auth.

### Is incomplete evidence a standalone product responsibility?

**No (INTERPRETATION).**  
It is a **supporting requirement** of verification, sync honesty, and
postmortems (EP-11). Standalone → generic observability platform trap
(`SCOPE_TRAPS.md`).

### Is stale observation the root of incorrect actions, failed verification, and recovery loops?

**Root of a major branch—not the only root (EVIDENCE).**  
Stale observation explains many incorrect actions and can poison verification
and recovery. Separately, **false progress with fresh, correct targeting** is
well documented (L01, A4, F10). Both foundations must appear in any serious
definition.

---

## Implications for Phase 2A definition (preview, not decision)

A definition that only fixes G1 leaves G2 intact.  
A definition that only fixes G2 without freshness is epistemically dishonest.  
A definition that absorbs G3/G4/G5/G8 as core identity violates non-goals or
reinvents mature tools.

**Narrow coherent target region:** G2 (+ freshness constraint from G1) (+ G7
as evidence obligation) (+ typed statuses usable by host-owned G6).
