# Engineering

Governing documents for long-term architectural consistency.

| Document | Role |
|----------|------|
| [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md) | Canonical principles EP-01 … EP-15 (living) |
| [`NON_GOALS.md`](./NON_GOALS.md) | Canonical non-goals NG-01 … NG-13 (living) |
| [`PRINCIPLES_RESEARCH_CROSSWALK.md`](./PRINCIPLES_RESEARCH_CROSSWALK.md) | Evidence links: principles → Research archive |
| [`NON_GOALS_CROSSWALK.md`](./NON_GOALS_CROSSWALK.md) | Alignment: non-goals → principles + research |
| [`Phase 2/PHASE_2_INDEX.md`](./Phase%202/PHASE_2_INDEX.md) | Phase 2 definition documents (responsibility & boundaries) |
| [`Phase 2/PHASE_2A_RECOMMENDATION.md`](./Phase%202/PHASE_2A_RECOMMENDATION.md) | Current recommended single responsibility |
| [`Phase 3/PHASE_3_INDEX.md`](./Phase%203/PHASE_3_INDEX.md) | Implementation milestones |
| [`Phase 3/MILESTONE_1_IMPLEMENTATION_NOTES.md`](./Phase%203/MILESTONE_1_IMPLEMENTATION_NOTES.md) | Milestone 1 notes |
| [`Phase 3/MILESTONE_1_TARGET_RESOLUTION_HARDENING.md`](./Phase%203/MILESTONE_1_TARGET_RESOLUTION_HARDENING.md) | Constrained target resolution |
| [`Phase 3/BROWSER_BOUNDARY_HARDENING.md`](./Phase%203/BROWSER_BOUNDARY_HARDENING.md) | Browser config / launch boundary |
| [`Phase 3/MILESTONE_2_NATIVE_ORDERED_PLANS.md`](./Phase%203/MILESTONE_2_NATIVE_ORDERED_PLANS.md) | Native ordered plans |
| [`Phase 3/MILESTONE_2_CHROMIUM_STABILIZATION.md`](./Phase%203/MILESTONE_2_CHROMIUM_STABILIZATION.md) | Chromium plan lifecycle / receipt stabilization |
| [`Phase 3/FIREFOX_COMPATIBILITY_MILESTONE.md`](./Phase%203/FIREFOX_COMPATIBILITY_MILESTONE.md) | Bundled Firefox compatibility |
| [`Phase 3/BASIC_INTERACTION_EXPANSION.md`](./Phase%203/BASIC_INTERACTION_EXPANSION.md) | press_key / select / check / hover / scroll |
| [`Phase 3/WEBKIT_COMPATIBILITY_MILESTONE.md`](./Phase%203/WEBKIT_COMPATIBILITY_MILESTONE.md) | Bundled WebKit (not native Safari) |
| [`Phase 3/DECLARED_WAIT_CONDITIONS.md`](./Phase%203/DECLARED_WAIT_CONDITIONS.md) | Host-authored wait_for conditions |
| [`Phase 3/IFRAME_TARGETING.md`](./Phase%203/IFRAME_TARGETING.md) | Declared same-page iframe targeting |
| [`Phase 3/PLAN_RUNNER_CLI.md`](./Phase%203/PLAN_RUNNER_CLI.md) | Website-neutral JSON plan-runner CLI |
| [`Phase 3/STATEFUL_SESSIONS.md`](./Phase%203/STATEFUL_SESSIONS.md) | Host-owned incremental browser sessions |
| [`THREE_LAYER_RECEIPT_ARCHITECTURE.md`](./THREE_LAYER_RECEIPT_ARCHITECTURE.md) | Core receipt, bounded evidence, and artifact boundary |
| [`REMAINING_INFRASTRUCTURE_BOUNDARIES.md`](./REMAINING_INFRASTRUCTURE_BOUNDARIES.md) | Network, portable state, profiles, secrets, and WebAuthn boundaries |
| [`EXECUTION_GOVERNANCE.md`](./EXECUTION_GOVERNANCE.md) | The ten advanced execution-governance controls: authority, transactions, quorum, receipt chains/checkpoints, handoff, signed plans, identity, mutation arbitration, attestation, and bounded speculation |
| [`MCP_ADAPTER.md`](./MCP_ADAPTER.md) | Optional standards-compliant MCP stdio adapter, host/principal binding, canonical contract projection, and security boundary |

**How to use:** Principles say how to build. Non-goals say what not to become.
Phase 2 says what the project *is* responsible for. Research explains why.

**Before architecture or implementation code:** follow the review list in the
repository [`../README.md`](../README.md) and Phase 2 index.

Research archive: [`../Research/`](../Research/README.md).
