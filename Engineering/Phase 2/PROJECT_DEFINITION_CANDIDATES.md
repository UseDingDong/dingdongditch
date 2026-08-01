# Project Definition Candidates

**Phase:** 2A  
**Date:** 2026-07-25  
**Rule:** Three to five *meaningfully different* boundaries—not cosmetic renames.  
**Method:** Qualitative evaluation against criteria in `CANDIDATE_RESPONSIBILITIES.md`.  
**No numeric scores.**

Epistemic labels used in evidence basis fields.

---

## Evaluation lens (apply to each)

Evidence strength · recurrence · independence · tool compatibility · model neutrality · clarity · testability · adoption friction · scope containment · duplication risk · agent-product risk · EP fit · NG fit

---

## Candidate A — Browser execution attestation layer

### One-sentence definition

DingDongDitch attests whether **host-declared, browser-observable expectations**
hold, using freshness-bounded multi-signal evidence, without planning actions or
replacing automation frameworks.

### Responsibility owned

CR-2 primary; CR-5 required; CR-1 as freshness constraint; CR-4 as typed
status vocabulary only.

### Responsibilities excluded

Planning; click-driving as product identity; MCP replacement; CAPTCHA solving;
RPA; inventing user goals; off-browser fulfillment claims.

### Stack position

**E (contract/semantics)** with reference capability delivered via **C/F**;
optional **A** binding. Not **D**.

### Input

Declared expectations; observation/evidence handles or permission to gather
them; optional action receipts; epoch metadata.

### Output

Typed verdicts (progress / no-progress / blocked / uncertain / needs-human /
epoch-invalid); evidence bundle references; confidence/uncertainty notes.

### Authority

May affirm or deny declared browser-local claims; may refuse dishonest
attestation when epoch invalid; may not authorize goals or plans.

### Evidence basis

**PATTERN/EVIDENCE:** G2, A3, A4, F10, L01, L15, EP-01, EP-04; G1/L03 for
freshness; G7/L09 for evidence; recon mission-alignment note on gaps 1,2,6,7,10.

### Strengths

- Narrow, testable, principle-central  
- Model-neutral and compatible with scripts and agents  
- Hardest to confuse with “another agent” if discipline holds  
- Explains false progress without requiring freeze-browser research first  

### Weaknesses

- Host must declare expectations (adoption friction; UB-1)  
- Does not by itself fix targeting/grounding (G5)  
- Opportunity/adoption unproven (**SPECULATION** that a market wants this separable)

### Unresolved risks

- Verifier independence if models assist (UB-2)  
- Expectation language expressiveness vs EP-14  
- Quiescence requirements (SS-1)

### Likely adopters

Coding agents; teams wrapping Browser Use/Stagehand; engineers adding agent
oracles beyond Playwright Test; evaluators needing honest progress labels.

### Why existing tools don’t already fill the role

Playwright `expect` is engineer-centric and test-runner-centric; MCP `verify_*`
is optional and thin; agents self-check with the same fallible model; traces
observe but do not define progress attestation semantics for AI hosts (EVIDENCE).

### Narrow enough to build?

**Yes**, as a responsibility boundary (architecture still deferred).

---

## Candidate B — Observation–action synchronization layer

### One-sentence definition

DingDongDitch binds actions to validated observation epochs so hosts cannot
silently act on stale page understanding.

### Responsibility owned

CR-1 primary; minimal CR-3; partial CR-5.

### Responsibilities excluded

Goal oracles; planning; full verification of business progress; CAPTCHA; MCP
replacement.

### Stack position

Near browser control (**C**), possibly experimental engine cooperation; **E**
for epoch semantics.

### Input

Observation epoch; proposed action; optional freeze/barrier signals.

### Output

Epoch-valid / epoch-invalid; pre-action revalidation results; change notifications.

### Authority

Block or warn on stale epochs; not choose alternate actions.

### Evidence basis

**EVIDENCE/PATTERN:** G1, F2, L03, A9; ABP claims (replication UNKNOWN Q5/Q10).

### Strengths

- Addresses a clearly physical race  
- Complements automation without replacing it  

### Weaknesses

- Leaves G2 intact (correct click, wrong outcome)  
- Freeze approaches risk NG-03 / site breakage (Q5)  
- Weaker direct alignment to EP-01 than Candidate A  

### Unresolved risks

- Enforcement without browser fork  
- Whether re-snapshot-before-act is “enough” (still races)

### Likely adopters

Agent runtime authors hit by stale UI; computer-use integrators.

### Why existing tools don’t fill the role

Automation auto-waits at action time but does not bind *LLM decision epochs*;
MCP snapshot-then-think-then-act remains racy (PATTERN).

### Narrow enough?

**Yes**, but **incomplete** relative to principle-central false-progress gap.

---

## Candidate C — Typed execution outcome + bounded recovery coordinator

### One-sentence definition

DingDongDitch classifies browser execution outcomes and coordinates bounded
recovery policies (stop, handoff, limited retry) for AI-driven browser sessions.

### Responsibility owned

CR-4 primary; CR-2 partial; challenge classification; handoff signals.

### Responsibilities excluded

Full RPA; CAPTCHA solving (classify only); long-horizon planning (tension).

### Stack position

**A/D-leaning** policy runtime around sessions.

### Input

Actions, observations, policy configs, retry budgets.

### Output

Outcome classes; recovery directives; human-handoff events.

### Authority

May halt further actions per policy; risk of owning the loop.

### Evidence basis

**EVIDENCE:** G6, F8, L13, EP-05; D3 auth/challenge pain.

### Strengths

- Directly addresses harmful loops  
- Matches practitioner ask for stop/handoff clarity (feedback synthesis)

### Weaknesses

- Easy slide into agent runtime (T1)  
- Recovery without strong attestation repeats L13 failure mode  
- Broader than “one responsibility”  

### Unresolved risks

- Policy engine complexity (EP-14)  
- Product competition with agent frameworks  

### Likely adopters

Production agent operators.

### Why existing tools don’t fill the role

Retries exist but are ad hoc; few shared outcome taxonomies across agents (G6).

### Narrow enough?

**Borderline / leaning no**—coordination tends to absorb the control loop.

---

## Candidate D — Privilege-separation layer for browser agents

### One-sentence definition

DingDongDitch enforces programmatic permission boundaries on browser-capable
agents (allowlists, irreversible-action gates, isolation), independent of model
persuasion.

### Responsibility owned

CR-6 primary.

### Responsibilities excluded

Attestation of progress; planning; automation driving; CAPTCHA defeat.

### Stack position

**A/C** gateway; sandbox integration.

### Input

Proposed actions; policy; session identity.

### Output

Allow / deny / require-human; audit log.

### Authority

Hard deny regardless of model text.

### Evidence basis

**EVIDENCE:** G8, L11, D6, EP-09; OWASP/IDPI reports (secondary-cited).

### Strengths

- Principle-aligned security architecture  
- Clear non-overlap with Playwright  

### Weaknesses

- Different primary mission than Phase 1 “execution reliability” center  
- Security-product trap (T6)  
- Does not fix false progress (G2) or stale acts (G1)  

### Unresolved risks

- Q13 which controls actually work  
- Enterprise scope creep  

### Likely adopters

Security-sensitive enterprises; agent platforms needing lockdown.

### Why existing tools don’t fill the role

HITL and sandboxes exist unevenly; no shared cross-host browser-agent
permission semantics (PATTERN)—but several vendors ship pieces.

### Narrow enough?

**Yes as a different project.** **Poor fit** as *this* project’s sole identity
given Phase 1 framing and NG security-product risk.

---

## Candidate E — “Full reliability suite” between AI and automation

### One-sentence definition

DingDongDitch is the universal reliability layer providing sync, verification,
state, recovery, evidence, and privilege mediation between any AI and any
browser automation tool.

### Responsibility owned

CR-1+2+3+4+5+6 (+ mediation CR-7 tendencies).

### Responsibilities excluded

Claims to exclude agents/MCP/Playwright—but scope contradicts exclusions in practice.

### Stack position

Ambiguous **A+C+D+E** simultaneously.

### Input / output

Everything.

### Authority

De facto control plane.

### Evidence basis

**SPECULATION** in recon that differentiation lies in verification/sync/recovery/trust; **PATTERN** that all are painful—**not** evidence they form one shippable responsibility (EP-14).

### Strengths

- Matches early working hypothesis rhetoric  
- Covers mission-aligned gaps list  

### Weaknesses

- Fails “smallest clearest responsibility” brief  
- Maximum trap exposure (T1–T10)  
- Violates EP-14 / NG-12 spirit  
- Unbuildable without becoming a platform  

### Unresolved risks

- Boils the ocean  

### Likely adopters

Nobody sustainably; or becomes a company-sized RPA/agent firm (NG-06).

### Why existing tools don’t fill the role

N/A—this candidate *recreates the entire upper stack*.

### Narrow enough?

**No.**

---

## Candidate F — Plan-consuming browser execution runtime

**Added:** 2026-07-26 via challenge (not in original 2A set).  
**Full challenge:** [`CHALLENGE_ATTESTATION_VS_EXECUTION_RUNTIME.md`](./CHALLENGE_ATTESTATION_VS_EXECUTION_RUNTIME.md)

### One-sentence definition

DingDongDitch is a model-neutral browser execution runtime for externally
planned tasks: observe and act via automation backends, apply bounded
verification and bounded recovery, return structured attested evidence—without
autonomous planning, goal invention, Playwright replacement, or agent identity.

### Responsibility owned

Execution dispatch; observation; bounded verification; bounded recovery;
evidence receipts. Attestation semantics from Candidate A are **mandatory
inside receipts**.

### Responsibilities excluded

Autonomous planning; goal-taking; CAPTCHA solving; MCP/Playwright replacement;
RPA; chatbot; off-browser truth.

### Stack position

Plan-consuming runtime between planner host and automation backends (not
goal-taking Position D).

### Input

External plans: actions + expectations + recovery bounds.

### Output

Attested receipts: observations, verdicts, evidence, terminal status.

### Authority

Execute and honestly report; stop/handoff within bounds; no new plan invention.

### Evidence basis

Challenge argument; G1/G2/G6/G7 as faculties of one contract; adoption failure
mode of optional attestation (V-A2).

### Strengths

On-path usefulness; enforces EP-01/03/04/05; coherent I/O boundary.

### Weaknesses

Higher T1/T2 risk; EP-14 complexity; recovery fence must hold.

### Narrow enough?

**Yes as a contract** (plan→receipt). **No** if faculties become peer products.

### Advancement

**Current primary recommendation** (amended Phase 2A)—pending validation fences.

---

## Qualitative comparison matrix

| Criterion | A Attestation | B Sync | C Recovery coord | D Privilege | E Full suite | F Plan runtime |
|-----------|---------------|--------|------------------|-------------|--------------|----------------|
| Evidence for problem | Strong | Strong | Strong | Strong | Mixed | Strong (composite) |
| Independence as layer | Strong | Medium | Weak–medium | Strong | Weak | Strong *as contract* |
| Agent-product risk | Low | Low–medium | High | Low–medium | Very high | Medium–high (fence) |
| Playwright-replace risk | Low | Medium | Medium | Low | High | High without discipline |
| EP-01/04 centrality | Highest | Indirect | Medium | Low | Diluted | High (mandatory in receipt) |
| On-path usefulness | Weak | Medium | Medium | Medium | High chaotic | **Strong** |
| NG fit | Best default | Good | Fragile | OK off-mission | Poor | Conditional on fences |
| Adoption friction | High skip risk | Medium–high | Medium | High | Extreme | Medium |
| Coherent single job | Yes | Yes | Borderline | Yes | No | **Yes iff contract-subordinated** |
| Unproven opportunity | Yes | Yes | Yes | Yes | Yes | Yes |

---

## Candidates intentionally not developed

- Token-optimizer for MCP (G4)—wrong owner  
- Frame-piercing engine (G5)—NG-04  
- CAPTCHA solver—NG-07  
- Chat UI—NG-02  

---

## Advancement (amended 2026-07-26)

- Candidate **F** advances as Phase 2A primary identity after challenge.  
- Candidate **A** remains mandatory **receipt semantics**, not sole boundary.  
- Candidate **B** remains freshness constraint inside F.  
- Candidate **C** folded as **bounded recovery faculty** inside F (not autonomous coordinator product).  
- Candidate **D** (privilege) remains companion / later—not v1 identity.  
- Candidate **E** remains rejected (unfenced suite / goal mediation).  

Prior “only A advances” line is superseded by the challenge record.

