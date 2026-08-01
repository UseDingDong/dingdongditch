# Non-Goals

**Version:** 0.1  
**Status:** Living Document  
**Adopted:** 2026-07-25

## Purpose

This document defines what this project is intentionally **not** trying to become.

Every engineering project experiences pressure to expand its scope over time.
This document exists to protect the architecture from unnecessary complexity.

These are deliberate decisions, not limitations.

If one day strong evidence suggests a non-goal should become a goal, that
decision should be made consciously and supported by evidence—not by gradual
feature creep.

**Governance:** Non-goals are enforced together with
[`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md). Scope expansion
must satisfy NG-13 and EP-06 / EP-14 / EP-15.

**Related:** Alignment to principles and research is recorded in
[`NON_GOALS_CROSSWALK.md`](./NON_GOALS_CROSSWALK.md).
Phase 2 responsibility definition:
[`Phase 2/PHASE_2_INDEX.md`](./Phase%202/PHASE_2_INDEX.md).

---

## NG-01 — Not an AI Model

This project does not compete with language models.

It is designed to work with them.

Reasoning belongs to the AI.

Execution belongs elsewhere.

---

## NG-02 — Not a Chatbot

This project does not exist to provide another conversational interface.

User interfaces may exist around it, but conversation is not its purpose.

---

## NG-03 — Not a Browser

This project does not replace Chromium, Firefox, WebKit, or any browser engine.

Browsers remain responsible for rendering web content.

---

## NG-04 — Not a Browser Automation Framework

This project does not attempt to replace Playwright, Puppeteer, Selenium, or
similar libraries.

Those projects already solve browser automation extremely well.

This project should build alongside existing ecosystems whenever practical.

---

## NG-05 — Not an MCP Replacement

Model Context Protocol solves a different problem.

This project should not attempt to replace MCP.

It may integrate with MCP where appropriate.

---

## NG-06 — Not an RPA Platform

This project is not attempting to become a business workflow platform,
low-code automation builder, or enterprise RPA competitor.

---

## NG-07 — Not a CAPTCHA Solver

This project does not exist to bypass security mechanisms.

Authentication challenges, human verification, and security controls should be
treated as architectural realities—not obstacles to defeat.

---

## NG-08 — Not Responsible for AI Reasoning

Planning, decision making, and natural language understanding belong outside
DingDongDitch — in developer tooling, Cursor, an AI host, or other application
code that authors the typed plan.

This project should avoid embedding assumptions about how reasoning should
work. It is not a built-in planner and does not interpret natural-language
tasks into workflows.

---

## NG-09 — Not Responsible for User Intent

The user (or their host application) defines the objective.

DingDongDitch should not silently redefine success, invent goals, choose which
products/forms/links/pages were intended, or explore sites to invent workflows.

---

## NG-10 — Not Vendor-Specific

The architecture should avoid becoming dependent on one browser, one AI model,
one cloud provider, one operating system, or one protocol whenever practical.

Replaceable dependencies are healthier than permanent dependencies.

---

## NG-11 — Not Optimized for Demos

The project should avoid prioritizing impressive demonstrations over
engineering quality.

Reliable systems are more valuable than flashy examples.

---

## NG-12 — Not Everything to Everyone

Not every browser problem belongs inside this project.

If another mature tool already solves a problem well, prefer integration over
reinvention.

---

## NG-13 — Research Before Expansion

New capabilities should not be added simply because they are technically
possible.

Every expansion of scope should answer three questions:

1. Does this align with the Engineering Principles?
2. Does evidence show this belongs here?
3. Is this responsibility already solved elsewhere?

If any answer is "no," expansion should be questioned.

---

## Closing Statement

A focused project is easier to understand, maintain, and trust.

These non-goals protect the project's identity.

The objective is not to build the largest browser ecosystem.

The objective is to build one component that performs its responsibility
exceptionally well.

---

## Change log

| Version | Date | Change |
|---------|------|--------|
| 0.1 | 2026-07-25 | Initial adoption of NG-01 through NG-13 |
