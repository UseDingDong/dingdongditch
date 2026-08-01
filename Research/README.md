# Research Archive — Browser Execution Layer Reconnaissance

**Mission:** Understand the ecosystem between AI reasoning and browser execution before designing anything.

**Date of initial reconnaissance:** 2026-07-25  
**Status:** Living institutional knowledge. Update in place; do not overwrite evidence.

**Governance:** Architectural decisions are constrained by
[`../Engineering/ENGINEERING_PRINCIPLES.md`](../Engineering/ENGINEERING_PRINCIPLES.md)
(EP-01 … EP-15) and
[`../Engineering/NON_GOALS.md`](../Engineering/NON_GOALS.md)
(NG-01 … NG-13). Project responsibility is defined in
[`../Engineering/Phase 2/`](../Engineering/Phase%202/PHASE_2_INDEX.md)
(see especially `PHASE_2A_RECOMMENDATION.md`). This Research archive supplies
evidence those documents rest on; see the Engineering crosswalk files.

**Before architecture or code:** see the review checklist in
[`../README.md`](../README.md).

## Epistemic rules for this archive

Every claim in this archive must be labeled as one of:

| Label | Meaning |
|-------|---------|
| **FACT** | Directly supported by primary docs, protocol specs, or reproducible observation |
| **EVIDENCE** | Supported by cited issues, discussions, blogs, release notes, or secondary surveys |
| **PATTERN** | Recurs across independent projects; synthesized from multiple EVIDENCE items |
| **SPECULATION** | Plausible inference; not yet strongly evidenced — do not treat as design input without further research |
| **UNKNOWN** | Explicitly unresolved; tracked under Open Questions |

Do **not** invent product features in this archive. Do **not** collapse weak evidence into conclusions.

## Directory map

| Path | Contents |
|------|----------|
| [`Competitors/`](./Competitors/) | Per-project ecosystem profiles |
| [`Architecture/`](./Architecture/) | Shared architectural assumptions, posture taxonomy, stack layers |
| [`Failure Analysis/`](./Failure Analysis/) | Recurring failure classes with causes and workarounds |
| [`Lessons Learned/`](./Lessons Learned/) | Permanent engineering lessons extracted from evidence |
| [`Evidence/`](./Evidence/) | Source index, citation ledger, benchmark caveats |
| [`Developer Feedback/`](./Developer Feedback/) | HN, Reddit, GitHub discussion synthesis |
| [`Open Questions/`](./Open Questions/) | Unresolved questions for later research |

## Entry points

1. **[RECONNAISSANCE_REPORT.md](./RECONNAISSANCE_REPORT.md)** — Full Parts 1–7 report (facts / evidence / patterns / speculation / unknowns separated)
2. **[COMPARISON_MATRIX.md](./Architecture/COMPARISON_MATRIX.md)** — Capability matrix across frameworks (qualitative, non-scored)
3. **[ECOSYSTEM_MAP.md](./Competitors/ECOSYSTEM_MAP.md)** — Categorized project index
4. **[SHARED_ASSUMPTIONS.md](./Architecture/SHARED_ASSUMPTIONS.md)** — Cross-project architectural assumptions
5. **[RECURRING_GAPS.md](./Architecture/RECURRING_GAPS.md)** — Ecosystem-wide gaps
6. **[LESSONS_INDEX.md](./Lessons Learned/LESSONS_INDEX.md)** — Index of permanent lessons

## Two shapes of the field (PATTERN)

Across independent surveys (May–June 2026), the market reduces to:

1. **Browser agents** — vendor owns the control loop; task in / result out
2. **Tooling for agents** — your agent owns the control loop; library/MCP/CLI drives the browser

Confusion in the space often comes from products advertising both shapes on the same homepage.

## How to use this archive later

When design begins:

1. Consult **Lessons Learned** before proposing architecture
2. Check **Shared Assumptions** for risks you might inherit
3. Check **Recurring Gaps** for problems that belong to the category, not one vendor
4. Trace every design decision back to **Evidence** citations
5. Prefer solving **execution / verification / recovery** problems over competing on agent UX
