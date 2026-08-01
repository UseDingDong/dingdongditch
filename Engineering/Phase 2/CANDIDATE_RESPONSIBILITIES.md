# Candidate Responsibilities

**Phase:** 2A  
**Status:** Analysis complete for Phase 2A  
**Date:** 2026-07-25  
**Epistemic rule:** FACT / EVIDENCE / PATTERN / INTERPRETATION / SPECULATION / UNKNOWN

This document extracts candidate responsibilities from Phase 1 research and
evaluates each for independence, principle/non-goal fit, and scope pull.

It does **not** select the project definition. Selection lives in
`PHASE_2A_RECOMMENDATION.md` after comparison of full definition candidates.

---

## Decision criteria (qualitative)

Each candidate is judged against:

| Criterion | Source |
|-----------|--------|
| Evidence strength & recurrence | Research gaps, failures, lessons, feedback |
| Architectural independence | Can it be a separate layer without owning adjacent products? |
| Compatibility with existing tools | NG-04, NG-05, NG-12 |
| Model neutrality | EP-07, NG-01, NG-08 |
| Browser-tool neutrality | EP-08, NG-03, NG-04 |
| Clarity & testability | EP-01, EP-04, EP-11 |
| Scope containment | EP-14, NG-12, NG-13 |
| Agent-product risk | NG-01, NG-02, NG-06, NG-08, NG-09 |
| Principle / non-goal conflicts | Engineering docs |

---

## CR-1 — Observation ↔ action synchronization

### Statement

Ensure that browser actions are executed against a declared, still-valid
observation epoch—or report that the epoch is no longer valid—so that AI hosts
do not act on silently stale page understanding.

### Gap addressed

- **G1** Observation/action desynchronization  
- Related: **A9**, **F2**, **L03**

### Evidence

- **PATTERN:** Live pages mutate during model deliberation; agents slower than scripts, so races worsen (L03).  
- **EVIDENCE:** ABP motivations (modal after screenshot, autocomplete overlay, reflow); computer-use multi-second cycles; Playwright flake literature on overlays.  
- **FACT:** Playwright actionability is evaluated near action time, but agent *decision* often used an earlier snapshot (Playwright MCP snapshot-then-act pattern).

### Who addresses it today

| System | Treatment | Incomplete because |
|--------|-----------|-------------------|
| Playwright | Auto-wait at action time | Does not bind AI decision epoch to action epoch |
| Playwright MCP | Fresh snapshot tools | Still race between snapshot return, LLM think, next tool call |
| ABP / freeze proposals | Freeze JS/render between turns | Experimental; site-compat UNKNOWN (Q5); not mainstream |
| Computer use | Re-screenshot loop | Latency enlarges stale window |

### Independence

**Medium.** Can be stated as a contract over “epoch validity,” but enforcing
freshness often requires browser-side cooperation (pause, barrier, or
re-validate). Risk of pulling engine modifications (NG-03 tension).

### Principles / non-goals

- Aligns: EP-02, EP-03  
- Tension: NG-03 if implementation requires a forked browser; NG-04 if it becomes a new automation API for clicks  
- Does not inherently violate NG-08 if it only validates epochs, not plans

### Scope it pulls in

- Some notion of observation packaging  
- Possibly page-lifecycle / freeze policy  
- Re-validation immediately before act  
- Evidence that epoch changed (G7 support)

### Standalone without becoming an agent?

**Yes**, if limited to epoch bind/invalidate semantics.  
**No**, if it starts deciding *when* to replan (that is reasoning / loop ownership).

### Inclusion judgment

**Strong candidate component; weak as sole project identity.**  
Solves wrong-target class of failures; does not solve correct-target / wrong-outcome class (G2).

---

## CR-2 — Independent outcome / progress verification

### Statement

Given a **declared** expected browser-observable outcome (or progress claim),
evaluate multi-signal browser evidence and return a structured verdict that is
independent of whether the preceding click/type/navigation threw an exception.

### Gap addressed

- **G2** Verification underspecified  
- Related: **A3**, **A4**, **F10**, **L01**, **L15**, **EP-01**, **EP-04**

### Evidence

- **FACT:** Playwright actionability ≠ application correctness (official docs; L01).  
- **PATTERN:** Agents treat tool OK as progress (A4, L15, F10).  
- **EVIDENCE:** Production guidance “verify after consequential actions”; MCP `verify_*` tools exist but are optional and thin relative to the problem; computer-use ACK ≠ goal.  
- **PATTERN:** False progress is a cross-stack failure class.

### Who addresses it today

| System | Treatment | Incomplete because |
|--------|-----------|-------------------|
| Playwright `expect` | Strong for tests | Engineer writes oracles; agents rarely compose equivalent goal oracles |
| Playwright MCP verify_* | Element/text visible checks | Optional; not a first-class progress attestation model; easy to skip |
| Stagehand `extract` | Schema-validated extraction | Focused on data pull, not general progress attestation; AI still in loop |
| Agent self-check prompts | Model judges screenshots | Not independent; same model that may be wrong; EP-09 conflict if used for safety |
| DevTools MCP | Rich signals | Observability ≠ attestation contract |

### Independence

**High.** Verification can consume observations/actions produced elsewhere and
emit verdicts without choosing the next action. This is the cleanest
“infrastructure not agent” shape among candidates.

### Principles / non-goals

- Aligns: EP-01, EP-04, EP-06, EP-11, EP-13 (if expectations are declared, not invented)  
- Aligns: NG-01, NG-08, NG-09 *if* DingDongDitch does not invent success criteria  
- Risk: silently inventing oracles → violates NG-09 / EP-13  
- Risk: LLM-as-verifier as sole mechanism → weakens independence (INTERPRETATION)

### Scope it pulls in

- Evidence collection (CR-5) almost inevitably  
- Freshness constraints (CR-1) for honest verdicts  
- Typed uncertainty / blocked / needs-human outcomes (interfaces to CR-4)  
- Does **not** require owning planning

### Standalone without becoming an agent?

**Yes**—this is the strongest “separate layer” case.  
Adopters: coding agents, Browser Use-like products, Stagehand pipelines, test+agent hybrids.

### Inclusion judgment

**Strongest primary responsibility candidate.**  
Central to principles and to the most structural false-confidence failure mode.

---

## CR-3 — Explicit browser / workflow state tracking

### Statement

Maintain an explicit model of browser/session/workflow state so that callers
do not rely on implicit memory of prior observations.

### Gap addressed

- Partial: **G1**, **G6**, multi-tab **F12**, session **F7**  
- Related: **EP-02**

### Evidence

- **PATTERN:** Shared assumptions A2–A7 about reconstructability fail in practice.  
- **EVIDENCE:** Multi-tab OAuth/payment confusion; storageState poisoning (F15).

### Who addresses it today

Playwright BrowserContext; agent memory/scratchpads; Skyvern workflow state;
session products in hosted browsers.

### Independence

**Low–medium as a product.** Full workflow state → RPA (NG-06). Narrow
“execution epoch + session facts” is supporting infrastructure.

### Principles / non-goals

- Aligns EP-02  
- Violates NG-06 if expanded to business workflow platform  
- EP-14: complexity earns existence only if scoped tightly

### Scope pull

Tabs, cookies, auth phase, challenge phase, downloads, dialogs — grows fast.

### Standalone?

**Poor as sole identity.** Necessary supporting concern, not the narrowest coherent product.

### Inclusion judgment

**Supporting, not primary.** Include only as much state as attestation/sync require.

---

## CR-4 — Bounded recovery coordination

### Statement

Define typed failure classes and stop/handoff/retry bounds so recovery does not
blindly replan into deeper damage.

### Gap addressed

- **G6**, **F8**, **L13**, **EP-05**

### Evidence

- **EVIDENCE:** Turnstile/CAPTCHA loops worsen sessions; retries without traces mask flakes; production advice for human gates.  
- **PATTERN:** Re-observe ≠ recovery (A7 counter-signals).

### Who addresses it today

Ad hoc per agent; Skyvern exception handling (relative); product HITL gates
(OpenAI lineage); Playwright retries (test-oriented).

### Independence

**Medium–low.** Recovery policy without classification/verification is empty or harmful. Owning the recovery *loop* approaches agent-product ownership (NG-08, G10).

### Principles / non-goals

- Aligns EP-05, EP-09 (stop on challenge)  
- NG-07: must classify challenges, not solve CAPTCHAs  
- Risk: becoming the control loop (agent trap)

### Scope pull

Challenge detection, human handoff UX, idempotency, session reset — large.

### Standalone?

**Dangerous as sole identity.** Better as **consumer of attestation outcomes** (blocked / uncertain / needs-human) owned by the AI host or product.

### Inclusion judgment

**Interface responsibility, not loop ownership.** DingDongDitch may *emit* recovery-relevant statuses; the host owns whether/how to recover.

---

## CR-5 — Goal-linked evidence collection

### Statement

Produce bundled, time-ordered evidence artifacts linked to declared intents and
actions sufficient for postmortem and for verification.

### Gap addressed

- **G7**, **F11**, **L09**, **EP-11**, **A11** counter-signals

### Evidence

- **FACT:** Playwright trace viewer is excellent for scripts.  
- **PATTERN:** Agents underuse equivalent packs; screenshots alone insufficient; DevTools MCP rise = observability hole.  
- **EVIDENCE:** ABP bundles dialogs/downloads/permissions with state.

### Who addresses it today

Playwright traces/video; DevTools; session recordings (Browserbase et al.);
partial agent logs.

### Independence

**Medium.** As standalone = generic observability platform trap. As required
output of verification = justified (EP-11, EP-14).

### Principles / non-goals

- Aligns EP-11, EP-06  
- NG-12: do not reinvent Playwright Trace Viewer wholesale—integrate/extend conceptually

### Standalone?

**No** as primary product identity.

### Inclusion judgment

**Mandatory supporting responsibility** of any attestation/verification definition.

---

## CR-6 — Privilege separation / permission boundaries

### Statement

Enforce programmatic limits on what browser actions may occur (domains, action
classes, irreversible ops) regardless of model persuasion.

### Gap addressed

- **G8**, **F14**, **L11**, **EP-09**, developer cluster **D6**

### Evidence

- **EVIDENCE:** 2026 IDPI reports; OWASP AI #1; vendor lockdown modes; shared “tax” across postures (AgentsCamp).  
- **PATTERN:** LLM self-policing insufficient.

### Who addresses it today

Product HITL; sandbox recommendations (Anthropic); allowlists in some agents;
OS/container isolation.

### Independence

**High technically, high product-risk.** Could be a security product of its own
(scope trap). Orthogonal to “did the workflow advance?”

### Principles / non-goals

- Aligns EP-09 strongly  
- Must not become CAPTCHA/anti-bot product (NG-07) or full browser security suite  
- Complements verification but does not replace it

### Standalone?

Possible as a *different* project; as DingDongDitch sole identity, misaligned with “execution reliability / attestation” center of Phase 1 mission language.

### Inclusion judgment

**Important companion capability; not the narrowest Phase 2A primary.**  
May appear later as a hard gate around irreversible actions once attestation exists—only with evidence (NG-13).

---

## CR-7 — Control-loop mediation between AI host and automation driver

### Statement

Sit between reasoner and driver as the universal execution coordinator
(dispatch actions, manage turns, own semantics).

### Gap addressed

- **G10**, **L07**, recon speculation about “universal execution layer”

### Evidence

- **PATTERN:** Two shapes + four postures; missing stable semantics across hosts (G10).  
- **SPECULATION:** Opportunity for universal layer (recon); not proven.

### Who addresses it today

MCP servers; agent frameworks; CLI/code-mode; each with incompatible semantics.

### Independence

**Looks high; actually absorbs everything.** Mediation without narrow duty
becomes agent runtime, MCP replacement, or Playwright wrapper.

### Principles / non-goals

- Conflicts with NG-05 if it replaces MCP  
- Conflicts with NG-04 if it reimplements automation  
- Conflicts with NG-08 if it owns planning cadence  
- EP-14: enormous complexity

### Standalone?

**This is how projects become agents.** Reject as *primary* identity.

### Inclusion judgment

**Rejected as primary responsibility.** A narrow attestation contract may *be used by* mediators without *being* the mediator.

---

## CR-8 — Page grounding / composed DOM across frames (rejected as primary)

### Why considered

G5, L06, F4 — real pain.

### Why rejected as DingDongDitch primary

- Mature automation libraries actively invest here (Stagehand piercers, Playwright frameLocator).  
- NG-04 / NG-12: prefer not reinventing browser automation internals.  
- Grounding improves *targeting*; still leaves G2 false progress intact.

**Status:** Out of primary scope; may consume better grounding from underlying tools.

---

## CR-9 — Context-window / token optimization (rejected as primary)

### Why considered

G4, F6, D1 — strong practitioner pain.

### Why rejected as DingDongDitch primary

- Belongs primarily to AI host memory strategy and MCP/CLI transport design (L04).  
- Microsoft Playwright CLI already responds in-ecosystem.  
- A verification layer may *reduce* needless re-snapshotting as a side effect, but owning token economics is the wrong identity (NG-05 risk, EP-14).

**Status:** Not owned. May cooperate with hosts that keep state outside model context.

---

## CR-10 — Authentication / CAPTCHA completion (rejected as primary)

### Why considered

G3, F7, F8, D3 — blocks “real work.”

### Why rejected

- NG-07 explicit.  
- L05: treat as architectural reality + handoff, not defeat.  
- Skyvern-class products already compete here.

**Status:** Classify/stop/handoff signals only—never solve.

---

## Dependency summary (candidates)

```
CR-1 Sync (epoch freshness)
        \ 
         +--> strengthens --> CR-2 Verification / attestation  <-- requires -- CR-5 Evidence
        /                              |
CR-3 Minimal state (supporting)        v
                              enables typed inputs to
                              CR-4 Recovery *coordination* (host-owned loop)
                                      
CR-6 Privilege gates (companion, optional later)
CR-7 Full mediation (rejected as primary)
CR-8 Grounding (leave to automation libs)
CR-9 Tokens (leave to hosts/MCP)
CR-10 Auth solve (forbidden)
```

**INTERPRETATION:** The coherent narrow cluster is **CR-2 primary**, with
**CR-5 required support**, **CR-1 as necessary honesty constraint**, and
**CR-4 as outcome vocabulary only**.

---

## Competing interpretations preserved

| Interpretation | Claim | Status |
|----------------|-------|--------|
| Sync-first | Stale state is the root; fix sync and verification follows | **Contested** — G2 occurs even with correct targeting (L01) |
| Verify-first | False progress is the root reliability lie; sync is a freshness constraint on evidence | **Preferred for Phase 2A** — aligns EP-01/EP-04; see recommendation |
| Security-first | Injection is the ceiling; start with privilege separation | **Important but different product**; D6 vs reliability mission |
| Full reliability suite | Sync+verify+recover+privilege+state together | **Fails EP-14 / NG-12**; not “one responsibility” |

---

## Unresolved (do not silently close)

- **UNKNOWN (Q9):** Relative frequency of stale-state vs false-progress vs auth vs planning failures on a fixed corpus.  
- **UNKNOWN (Q17):** Whether market adopters want attestation as a separable library vs baked into agents.  
- **UNKNOWN:** Whether “declared expectations” can be supplied by AI hosts with low enough friction to be used (adoption risk—not a research gap about the problem’s existence).
