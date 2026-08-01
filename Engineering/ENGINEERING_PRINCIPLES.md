# Engineering Principles

**Version:** 0.1  
**Status:** Living Document  
**Adopted:** 2026-07-25

## Purpose

This document defines the engineering principles that guide every architectural
decision in this project.

These principles are intentionally independent of any specific browser,
protocol, AI model, vendor, or implementation.

Whenever a design decision conflicts with one of these principles, the design
must be questioned before the principle is changed.

The goal is long-term architectural consistency.

**Governance:** Principles outrank convenience. Evidence can change principles
(see EP-06, EP-15). Fashion, demos, and vendor lock-in cannot.

**Related:**
- Research grounding: [`PRINCIPLES_RESEARCH_CROSSWALK.md`](./PRINCIPLES_RESEARCH_CROSSWALK.md)
- Scope boundaries: [`NON_GOALS.md`](./NON_GOALS.md)
- Phase 2 definition: [`Phase 2/PHASE_2_INDEX.md`](./Phase%202/PHASE_2_INDEX.md)
- Research archive: [`../Research/`](../Research/README.md)

---

## EP-01 — Execution Success ≠ Task Success

A successful click, type, or navigation does not mean the user's objective
advanced.

Every meaningful operation should be capable of independent verification.

The browser may report success while the workflow has already failed.

---

## EP-02 — Never Assume Browser State

Browser state is temporary.

Pages mutate.

Sessions expire.

Elements disappear.

Frames reload.

Anything that can change eventually will.

Architectures should continuously validate assumptions instead of relying on
previous observations.

---

## EP-03 — Observation Ages Quickly

The moment an AI observes a page, that observation begins becoming stale.

Long reasoning loops increase the probability that execution is acting on an
outdated understanding of reality.

Freshness matters.

---

## EP-04 — Verification Is a First-Class Citizen

Verification is not an optional debugging feature.

Verification is part of execution.

Every consequential action should have a way to determine whether the intended
outcome actually occurred.

---

## EP-05 — Recovery Is Part of Execution

Failures are expected.

Recovery should never be treated as an afterthought.

Every execution strategy should define what happens after uncertainty,
unexpected page changes, interruptions, or partial completion.

---

## EP-06 — Evidence Before Assumptions

Engineering decisions should be supported by evidence whenever practical.

User reports, measurements, traces, reproducible failures, and research carry
more weight than intuition.

Unknowns should remain labeled as unknowns.

---

## EP-07 — AI Is Replaceable

This project is not built around a specific model.

Reasoning engines will improve.

Models will change.

The execution layer should remain useful regardless of which AI system is
driving it.

---

## EP-08 — Browser Engines Are Replaceable

Chromium is not the architecture.

Playwright is not the architecture.

CDP is not the architecture.

Every dependency should be treated as an implementation detail whenever
possible.

---

## EP-09 — Security Is Architecture

Security is not achieved by asking an AI to "be careful."

Permission boundaries, isolation, validation, and least privilege are
architectural responsibilities.

---

## EP-10 — Determinism Is Valuable

When deterministic execution is possible, prefer it.

Use AI reasoning where adaptability is required, not where deterministic logic
already provides reliable answers.

---

## EP-11 — Observability Is Mandatory

Every significant decision should be explainable after the fact.

Logs, traces, state transitions, evidence, and execution history should make
postmortem analysis possible.

Invisible systems become impossible to improve.

---

## EP-12 — Build Infrastructure, Not Demos

Temporary demonstrations optimize for appearances.

Infrastructure optimizes for reliability.

Whenever these goals conflict, reliability wins.

---

## EP-13 — The User Owns the Goal

The system executes.

The user defines success.

The architecture should avoid replacing user intent with assumptions about what
the user "probably meant."

---

## EP-14 — Complexity Must Earn Its Existence

Every new abstraction increases long-term maintenance cost.

Features should exist because they solve recurring engineering problems, not
because they are technically interesting.

---

## EP-15 — Research Never Ends

This document is not permanent.

Evidence may invalidate any principle.

When that happens, update the principle rather than forcing reality to match
previous beliefs.

Architecture should follow evidence.

Never the reverse.

---

## Change log

| Version | Date | Change |
|---------|------|--------|
| 0.1 | 2026-07-25 | Initial adoption of EP-01 through EP-15 |
