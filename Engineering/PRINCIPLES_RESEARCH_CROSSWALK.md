# Principles ↔ Research Crosswalk

**Purpose:** Tie each Engineering Principle to reconnaissance evidence without
turning principles into implementation specs.

**Sources:** `../Research/Lessons Learned/`, `../Research/Architecture/`,
`../Research/Failure Analysis/`

**Rule:** This file cites evidence. It does not invent features. If evidence
later conflicts with a principle, update the principle (EP-15) via a dated
change in `ENGINEERING_PRINCIPLES.md`.

| Principle | Supporting lessons | Supporting gaps / failures | Notes |
|-----------|--------------------|----------------------------|-------|
| **EP-01** Execution ≠ task success | L01, L15 | G2, F10 | Actionability and tool OK are not goal oracles |
| **EP-02** Never assume browser state | L05, L06 | A2–A6 (shared assumptions), F3, F7, F15 | Sessions, frames, selectors all decay |
| **EP-03** Observation ages quickly | L03 | G1, F2 | Live pages race model deliberation |
| **EP-04** Verification first-class | L01, L15 | G2, F10 | Verification underspecified across the ecosystem |
| **EP-05** Recovery is execution | L13 | G6, F8 | Blind retries dig deeper holes |
| **EP-06** Evidence before assumptions | L10; Research epistemic rules | G9 | Benchmarks and intuition mislead |
| **EP-07** AI is replaceable | L07 | G10 | Control-loop ownership ≠ model choice; mission is execution layer |
| **EP-08** Engines are replaceable | L12, L14; CDP/Playwright as substrate pattern | Stack layers doc | CDP/Playwright are ubiquitous implementation details, not identity |
| **EP-09** Security is architecture | L11 | G8, F14 | Untrusted HTML + privileged session |
| **EP-10** Determinism is valuable | L08 | Cost/reliability spectrum in competitor postures | Prefer deterministic where possible; AI at joints |
| **EP-11** Observability mandatory | L09 | G7, F11 | Screenshots alone are insufficient evidence |
| **EP-12** Infrastructure, not demos | L10, L14; developer feedback clusters | G9 | Leaderboards and demos hide auth/challenge reality |
| **EP-13** User owns the goal | L07 (tooling vs agent product) | — | Avoid agent products that silently redefine success |
| **EP-14** Complexity must earn existence | L08, recurring “another wrapper” pattern | EP aligns with mission: not another assistant | New abstractions need recurring problem evidence |
| **EP-15** Research never ends | Entire Research archive status | Open Questions Q1–Q17 | Living documents; unknowns stay labeled |

## Conflict resolution order

When a future design proposal conflicts:

1. Check whether the conflict is with a **principle** or with an **implementation preference**
2. If with a principle: gather evidence (EP-06) before changing the principle (EP-15)
3. Consult the Research archive leaves — do not rely on chat memory alone
4. Record the decision and evidence pointer when a principle version bumps
