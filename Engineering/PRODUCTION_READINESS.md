# Production readiness checklist

Use this checklist before allowing an untrusted agent or planner to control a
live DingDongDitch browser session. It is a deployment guide, not a substitute
for the governance and MCP architecture documents.

## 1. Put the host at the trust boundary

- [ ] Expose `GovernedAgentSession` or authenticated `GovernedAgentService` to
  the planner. Do not expose `execute_plan()`, raw browser/session helpers, or
  `TrustedHostRuntime` to untrusted code.
- [ ] Keep policy installation, browser lifecycle, secret providers, trust
  registries, checkpoint retention, and handoff authority in trusted host code.
- [ ] Treat the machine contract as a proposal format, not as permission to
  execute. Do not load arbitrary Python plugins from a planner into the trusted
  host process.

## 2. Install narrow authority and credential controls

- [ ] Install an `AuthorityEnvelope` before governed execution. Scope origins,
  action types, budgets, provenance, and any host policy rules to the minimum
  needed for the task.
- [ ] Use host-owned `SecretProvider` implementations and opaque
  `SecretReference` values. Do not put plaintext credentials in plans,
  receipts, artifacts, logs, MCP arguments, or session exports.
- [ ] If signed plans are used, configure trusted signer keys, algorithm and
  policy/version expectations, nonce/replay retention, and session/identity
  scope in the host. A valid signature never expands the envelope.
- [ ] If user-owned identities are used, configure issuer/owner trust,
  rotation, revocation, and assertion freshness in the host. Identity is not
  authority and is not a control lease.

## 3. Retain defensible execution records

- [ ] Retain `ReceiptChainCheckpoint` values outside the runtime when later
  tamper evidence matters. A receipt chain is tamper-evident only relative to a
  separately retained trusted checkpoint; it is not signing or attestation.
- [ ] Configure attester trust only when attestation is needed. A same-process
  key is `host_attested`; `independent_attester` requires a separately trusted
  key holder/process/service. Neither level is hardware/TEE attestation or
  cryptographic proof of user-visible reality.
- [ ] Decide who can read receipts, bounded evidence, artifacts, checkpoints,
  and attestations. Apply retention, access-control, and redaction policies to
  screenshots, sanitized network traces, and exported browser state.

## 4. Secure MCP process ownership

- [ ] For the optional stdio MCP adapter, have a trusted launcher select and
  authenticate `--principal`. Never accept the MCP planner's claimed principal
  as authentication.
- [ ] Keep stdin/stdout pipes under the trusted host's ownership. Stdio process
  ownership is the authentication assumption; it is not a sandbox for arbitrary
  code in the same operating-system account.
- [ ] Do not expose control, prepared-operation, handoff, signing, secret, or
  attestation bearer material as planner configuration. The adapter's opaque
  handles are server-side and intentionally short-lived.
- [ ] Do not treat the current stdio adapter as a remote or HTTP deployment
  interface. Configure a separate authenticated transport and principal mapper
  before considering a multi-tenant or remote deployment.

## 5. Plan for live-browser change and irreversible effects

- [ ] Use Two-Phase Commit and quorum policies for consequential actions, and
  re-prepare after a stale, rejected, or externally changed browser state.
- [ ] Treat mutation attribution conservatively. The runtime can report
  `external_unknown` when it cannot defensibly distinguish human, page-script,
  or other external activity; it does not promise universal invisible
  page-JavaScript mutation detection.
- [ ] Do not describe a rejected or failed operation as rollback. DingDongDitch
  cannot reverse external server effects, arbitrary page state, authentication,
  or browser process state.
- [ ] Keep speculative continuations bounded and signer-authorized where signed
  plans are required. The runtime selects only one declared, evidence-eligible
  branch; it does not invent branches or use model reasoning to select one.

## 6. Manage browser state deliberately

- [ ] Use isolated profiles/contexts appropriate to the tenant and task.
  Profiles are engine-isolated; do not expect migration between engines.
- [ ] Treat portable cookies, sanitized localStorage, and opt-in IndexedDB as
  sensitive session material, not a credential vault. Review imports/exports
  before moving them between hosts or environments.
- [ ] Close sessions and revoke/expire host capabilities when a task ends. Use
  the host-brokered handoff path for controller changes; an old controller must
  not retain mutation authority.

## 7. Review limitations and upgrades before deployment

- [ ] Do not rely on DingDongDitch for semantic prompt-injection immunity,
  social-engineering resistance, or a Python-process sandbox. Keep authority
  narrow even when a model is trusted.
- [ ] Verify browser/platform support for the exact Playwright and browser
  revision you deploy. Playwright WebKit is not native Safari.
- [ ] Review release notes, machine-contract/schema compatibility, policy
  semantics, browser revisions, MCP's exact pinned dependency when used, and
  all host trust configuration before an upgrade. Re-run the relevant governed,
  browser, and MCP smoke tests in the target environment.

For detailed semantics, see [Execution governance](./EXECUTION_GOVERNANCE.md),
[MCP adapter](./MCP_ADAPTER.md), and
[remaining infrastructure boundaries](./REMAINING_INFRASTRUCTURE_BOUNDARIES.md).
