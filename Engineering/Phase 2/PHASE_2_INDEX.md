# Phase 2 Index

**Phase:** 2 — Project definition (responsibility and boundaries)  
**Current subphase:** 2A complete (pending validation experiments)  
**Date:** 2026-07-25

## Purpose of Phase 2

Define **what DingDongDitch is responsible for** before architecture or
implementation. Phase 2 does not produce code, APIs, or MVP backlogs.

## Document map

| Document | Purpose | Status |
|----------|---------|--------|
| [`CANDIDATE_RESPONSIBILITIES.md`](./CANDIDATE_RESPONSIBILITIES.md) | CR-1…CR-10 evaluated against research, EP, NG | Complete |
| [`GAP_DEPENDENCY_MAP.md`](./GAP_DEPENDENCY_MAP.md) | Foundational vs downstream gaps; dependency diagram | Complete |
| [`STACK_POSITION_ANALYSIS.md`](./STACK_POSITION_ANALYSIS.md) | Positions A–F compared | Complete |
| [`RESPONSIBILITY_BOUNDARIES.md`](./RESPONSIBILITY_BOUNDARIES.md) | Who owns what across user/AI/Ditch/tools/browser/site/human | Complete |
| [`SUCCESS_SEMANTICS.md`](./SUCCESS_SEMANTICS.md) | Vocabulary and success ladder; epistemic limits | Complete |
| [`SCOPE_TRAPS.md`](./SCOPE_TRAPS.md) | Expansion failure modes and early warnings | Complete |
| [`PROJECT_DEFINITION_CANDIDATES.md`](./PROJECT_DEFINITION_CANDIDATES.md) | Definition candidates A–F | Complete (F added 2026-07-26) |
| [`CHALLENGE_ATTESTATION_VS_EXECUTION_RUNTIME.md`](./CHALLENGE_ATTESTATION_VS_EXECUTION_RUNTIME.md) | Challenge: A vs plan-consuming runtime F | Complete |
| [`PHASE_2A_RECOMMENDATION.md`](./PHASE_2A_RECOMMENDATION.md) | Recommended responsibility (amended post-challenge) | Amended 2026-07-26 |
| [`PHASE_2_INDEX.md`](./PHASE_2_INDEX.md) | This index | Complete |

## Recommended definition (pointer only)

See [`PHASE_2A_RECOMMENDATION.md`](./PHASE_2A_RECOMMENDATION.md):

> Model-neutral browser execution runtime for externally planned tasks
> (observe/act via backends; bounded verify/recover; attested receipts)—without
> autonomous planning or Playwright replacement.

Attestation (former primary) remains the mandatory correctness core of receipts.
Challenge record explains why sole attestation was judged insufficient as the
product boundary.

## Next

**Phase 2B** (not started): only after validation experiments in the
recommendation doc. Phase 2B may refine semantics and boundaries; it still
should not jump to full system architecture without evidence.

## Governance prerequisites for any later coding

Before proposing architecture or writing implementation code, review:

1. [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md)  
2. [`../NON_GOALS.md`](../NON_GOALS.md)  
3. [`PHASE_2A_RECOMMENDATION.md`](./PHASE_2A_RECOMMENDATION.md)  
4. [`RESPONSIBILITY_BOUNDARIES.md`](./RESPONSIBILITY_BOUNDARIES.md)  
5. [`SUCCESS_SEMANTICS.md`](./SUCCESS_SEMANTICS.md)  
6. [`../../Research/RECONNAISSANCE_REPORT.md`](../../Research/RECONNAISSANCE_REPORT.md)  
7. [`../../Research/Lessons Learned/`](../../Research/Lessons%20Learned/)  

## Relationship to Phase 1

Phase 1 = evidence archive under `Research/`.  
Phase 2 = definition constrained by that evidence plus Engineering Principles
and Non-Goals.  
Do not modify Phase 1 evidence to fit Phase 2 conclusions; if conflict arises,
label it and reopen recommendation (EP-15).
