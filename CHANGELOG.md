# Changelog

All notable changes to DingDongDitch are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Pre-1.0 releases may include
breaking changes.

## [Unreleased]

## [0.5.1] - 2026-08-09

### Added

- Optional, standards-compliant, stdio-only **MCP adapter** for MCP protocol
  revision **2026-07-28**, using the exactly pinned optional dependency
  `mcp==2.0.0`. It is a thin transport adapter over a host-created
  `GovernedAgentService`, not a second execution engine.
- Discoverable governed MCP tools for canonical contract discovery,
  observation, execution, Two-Phase Commit preparation/commit, and bounded
  speculative execution. The MCP tool inputs derive from DingDongDitch's
  canonical machine-contract schemas.
- Trusted-host bootstrap and deterministic local MCP demonstration, including
  an installed-wheel client/server smoke path with no external AI API.

### Security hardening

- MCP transport principals are host-authenticated and bound to governed
  sessions. Planner-provided identity fields are rejected rather than trusted.
- Opaque, server-side prepare/speculation handles are principal, session,
  control-epoch, type, and expiry bound; they are single-use, bounded, cleared
  on disconnect, and cannot be replayed across a principal or control change.
- The adapter rejects malformed, oversized, deeply nested, unknown-tool, and
  schema-widening requests before browser work. Results and errors are bounded
  and redact host-only tokens, browser objects, paths, secrets, keys, and
  privileged exception details.
- All MCP browser work is delegated through `GovernedAgentService`, preserving
  Authority Firewall, signed-plan, identity, mutation, transaction, quorum,
  receipt-chain, handoff, attestation, and speculative-execution checks.

### Limitations

- MCP support is stdio only. The trusted host owns process launch and principal
  authentication; no HTTP listener or remote authentication scheme is exposed.
- The adapter deliberately does not expose host policy/trust configuration,
  secret providers, browser/runtime objects, raw execution APIs, checkpoint
  trust decisions, private keys, or bearer handoff/control capabilities.

## [0.5.0] - 2026-08-09

### Added

- Ten composable, host-governed execution controls: **Authority Firewall**,
  browser **Two-Phase Commit**, **Quorum Verification**, cryptographic
  **Receipt Chains** with externally retained checkpoints, and **Cross-Agent
  Hot Handoff** for one retained live browser session.
- **Signed Plan Authority**: trusted Ed25519 signing identities can authorize
  one exact canonical `PlanDocument`, bounded by host policy, session scope,
  identity scope, expiration, nonce replay limits, and ordered execution.
- Vendor-neutral, user/host-owned **Agent Identity** assertions with trusted
  registration, rotation, revocation, controller scope, handoff attribution,
  signed-plan binding, and receipt attribution.
- **Human/Agent Mutation Arbitration** with bounded mutation epochs and
  conservative `external_unknown` attribution for observable browser changes.
- Separate **Execution Attestation** statements, supporting host-attested and
  externally keyed/process-backed attesters, offline verification, bounded
  claims, challenges, and receipt-chain checkpoint binding.
- Bounded **Transactional Speculative Execution**: declared one-level branch
  preparation, deterministic exactly-one selection, revalidation, normal
  authority/lease/mutation checks, and Two-Phase Commit for consequential
  continuations.
- Public schemas, parser/serializer support, governed agent APIs, adversarial
  regression tests, and a deterministic local all-ten demonstration without
  an external AI API.

### Security hardening

- Both adversarial review rounds hardened policy/origin canonicalization,
  budgets, provenance propagation, secret-generation bindings, stale
  preparation detection, quorum evidence independence, receipt-chain
  checkpoints, handoff leases/epochs, and machine-contract parsing.
- Signed speculative topology is now inside the canonical signed
  `PlanDocument`: branch order, exact parent operation, preconditions,
  continuations, verification, and transaction-relevant operation material
  cannot be supplied as an unsigned sidecar.
- Signature domains are separated for plan authority, identity assertions,
  and attestations. Signed-plan validity is rechecked at dispatch; replay and
  registry state are bounded. Attestation claims bind speculation outcomes and
  expected offline verification context.

### Trust model and limitations

- Untrusted planners submit canonical proposals only through
  `GovernedAgentSession` or authenticated `GovernedAgentService`. Trusted
  hosts alone install policy, signer/identity/attester trust, secrets,
  lifecycle, checkpoints, and handoff authority.
- Receipt chaining is SHA-256 tamper evidence relative to an externally
  retained checkpoint; it is not signing. Signed plans authorize exact plans.
  Host attestation signs a host-produced claim. Independent attestation
  additionally relies on a separately trusted key/process/service; it is not
  hardware/TEE attestation or browser proof of user-visible reality.
- DingDongDitch does not provide arbitrary browser/server rollback, semantic
  prompt-injection immunity, universal detection of invisible page-JS state,
  or a Python-process sandbox for raw trusted-host APIs.

## [0.4.1] - 2026-08-08

### Added

- A versioned, public `PlanDocument` machine contract (1.0.0) for external
  planners, with canonical Draft 2020-12 JSON Schema resources for plans,
  operations, observations, execution receipts, and plan receipts.
- Public schema export, parsing, serialization, receipt-decoding, generic tool
  declaration, and structured `ContractValidationError` APIs. The `schema`
  CLI command emits each installed schema as JSON.
- Dependency-free OpenAI-style, Anthropic-style, and Gemini-style schema
  envelopes that project the canonical contract without model clients, keys,
  prompts, planning loops, or vendor-owned execution.
- Public machine-contract documentation, a no-key external-planner example,
  schema drift/packaging tests, and an installed-wheel smoke path.

### Changed

- README onboarding now treats model-neutral agent integration as a first-class
  capability and links to guides for hosted, private, local, open-source,
  experimental, generic, and deterministic non-LLM planners.
- The plan JSON loader accepts the canonical versioned document while retaining
  legacy bare-plan and legacy wrapper compatibility.
- The documented PlanReceipt version is corrected to **2.2.0**, matching the
  implementation.

## [0.4.0] - 2026-08-08

### Added

- `StatefulSessionRuntime`, a host-owned incremental
  `open -> observe -> execute -> verify -> close` session facade that keeps the
  existing deterministic executor and does not expose Playwright objects.
- Fail-closed `upload_file` actions with explicit file/root authorization,
  path-redacted receipts, and fresh post-upload verification that can recognize
  legitimate input replacement or attachment UI changes.
- Deterministic `select_combobox_option` support for explicitly associated
  custom combobox/autocomplete options; typing or pressing Enter alone is not
  accepted as a selection.
- Rich bounded guarded branches, including an explicit `otherwise` branch;
  ambiguous branch matches are indeterminate rather than chosen arbitrarily.
- Explicit bounded nested iframe `frame_path` targeting for actions, waits,
  expectations, preconditions, inspection, and JSON plans.
- Bounded failed-verification evidence, standard per-operation timing, and the
  formal three-layer Core Receipt / Bounded Evidence / Artifact architecture.
- Expanded deterministic network assertions for request/response observation,
  method, query-free URL/path matching, response status, and observable timing.
  Optional sanitized network traces are external artifacts rather than receipt
  payloads.
- Portable browser-state schema v2 with validation, safe origin association,
  sensitive localStorage exclusion, and opt-in IndexedDB export/import for the
  documented new-context boundary.
- Isolated persistent profiles for Chromium, Firefox, and WebKit where
  Playwright supports them, with engine-specific data directories and profile
  capability information in receipts.
- Generic `SecretProvider` / `SecretReference` execution-time secret injection
  and bounded, host-controlled WebAuthn participation transports.

### Changed

- Execution receipt schema is now **1.8.0**. `to_core_dict()`,
  `to_bounded_evidence_dict()`, and `to_layered_dict()` expose the layered
  receipt representation; legacy `to_dict()` remains available with additive
  fields.
- Public contracts add `GuardBranch`, `UploadAuthorization`,
  `ComboboxSelection`, network artifact/match types, portable-state types,
  secret-resolution types, WebAuthn transport types, and stateful-session APIs.
- `execute_operation()` and `execute_plan()` accept optional host authentication
  capability injection. Existing text-based fills and legacy secret providers
  remain supported.

### Limitations and security boundaries

- Per-operation HAR capture is not supported; only explicitly requested,
  bounded sanitized network traces are available.
- DingDongDitch has no native WebAuthn authenticator control, virtual
  authenticator, private-key extraction, or authentication-bypass behavior.
- Secret providers are host-owned; the runtime is not a credential vault and
  does not persist or log resolved values.
- There is no browser-engine fallback and no migration of an existing user
  profile between Chromium, Firefox, or WebKit. Chromium's existing `default`
  profile is only partially supported; Firefox/WebKit existing-user profiles
  are unsupported.
- IndexedDB can be imported only while creating a new ephemeral context; it is
  not injected into an active context. Session storage, password managers,
  passkeys, browser-profile internals, extensions, caches, and history are not
  portable state.
- Uploads support explicitly authorized HTML file inputs only. Directory
  uploads, native file dialogs, programmatic file-chooser trigger buttons, and
  wildcard/discovery paths are unsupported.

## [0.3.0] - 2026-08-05

### Added

- Production authentication callbacks, named persistent profiles and sessions,
  and deterministic guarded optional target actions.

## [0.1.0] - 2026-08-03

### Added

- Initial public release.
