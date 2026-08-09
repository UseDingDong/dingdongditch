# Execution governance

## Advanced execution trust boundary

```text
UNTRUSTED PLANNER
        | canonical PlanDocument (including bounded speculative topology)
        v
GOVERNED AGENT INTERFACE
        | signed-plan constraint + portable identity + control lease
        v
AUTHORITY FIREWALL -> MUTATION ARBITRATION -> PREPARE / COMMIT
        |                                      |
        +-----------------------> quorum -> receipt chain -> checkpoint
                                                     |
TRUSTED HOST --------------------------------------> attester boundary
```

The trusted host alone installs policy, signer and identity trust, secret
providers, mutation policy, browser lifecycle, handoff authority, retained
checkpoints, and attester trust. A planner receives only
`GovernedAgentSession` or `GovernedAgentService`; it never receives private
keys, browser handles, a raw runtime record, or host configuration APIs.

Signed-plan authorization is an Ed25519 authorization of an exact canonical
PlanDocument. It does not grant authority: execution remains the intersection
of the signed constraint, host envelope, valid identity, current lease, and
current browser/mutation state. `AgentIdentity` is vendor-neutral attribution;
it is not authority or a control lease. Browser-detected changes are
`external_unknown` unless a trusted host explicitly reports a human event.

Receipt chains are hash chains, not signatures. They are tamper-evident only
relative to a separately retained `ReceiptChainCheckpoint`. Execution
attestation is a separate Ed25519 statement about bounded checkpointed
material. A same-process signer is `host_attested`; the stronger
`independent_attester` label is reserved for an external transport/key holder.

Speculation is bounded preparation and deterministic branch selection, not
rollback, browser cloning, or server-state reversal. A signed plan can use it
only when `ExecutionPlan.speculative_plans` contains the exact topology:
ordered branch IDs, preconditions, exact parent operation, continuations, and
the one-level/count bounds. The runtime rejects ID-only legacy sidecars and
any supplied graph whose canonical form differs from the signed document. A
prepared graph is detached from caller-owned objects and can run only after a
chained, verified receipt for its exact signed parent; it is re-evaluated
immediately before dispatch. The parent operation's own verified state change
is carried forward as the expected epoch transition; unrelated external
mutations still stale the graph.

Ed25519 signature inputs use distinct protocol labels for signed-plan
authority, identity assertions, and execution attestations. Public key IDs
are registry-local labels, not authority by themselves. Trusted host
registries control signer revocation/rotation, identity revocation/rotation,
and attester trust; none is writable through the planner contract. Signed
plan expiry is rechecked for every governed dispatch, not only when installed.

Execution attestations sign a bounded statement including the speculative
outcome reference when present. Offline verification can bind expected plan,
session, identity, policy, quorum, browser metadata, contract version, and
challenge. It remains a statement by the configured attester: a host-process
key provides `host_attested`; `independent_attester` additionally requires a
separate trusted key/process/service and authenticated attester input. It is
not hardware/TEE attestation or browser proof of user-visible reality.

## Scope

This document describes the ten opt-in governance capabilities introduced on
top of DingDongDitch's retained browser sessions. They preserve the project
boundary: an external planner proposes operations; the runtime executes only
declared operations and applies host-installed rules. None of these features
contains model reasoning, a browser fallback, locator healing, autonomous
planning, or a general workflow engine.

## Trust boundary and public API

```text
UNTRUSTED PLANNER
        |
        v
machine contract (proposal only)
        |
        v
GovernedAgentSession / GovernedAgentService
        |
        v
authority firewall -> transaction -> control lease -> runtime -> browser

TRUSTED HOST
        |
        +-- TrustedHostRuntime: policy installation, secrets, lifecycle,
            authenticated transport identity, and handoff-token delivery
```

New agent products should expose only `GovernedAgentSession` to an in-process
planner, or `GovernedAgentService` behind authenticated IPC/HTTP/queue
transport. `TrustedHostRuntime` is host-only: it installs policy, owns secrets
and lifecycle, makes checkpoints, and claims handoff after authentication.
Those interfaces never serialize Playwright/browser/context/page objects.

`execute_operation`, `execute_plan`, `StatefulSessionRuntime`, and old
module-level session helpers remain trusted-host/legacy compatibility APIs.
They are not an LLM capability boundary. A Python object in one mutually
trusted process is not a sandbox; isolate hostile planners behind the governed
service and an authenticated transport.

## Authority Firewall

`AuthorityEnvelope` is an immutable, host-installed policy object. It can
allow or deny origins and action types; bound files, secret reference IDs,
upload size, irreversible actions, preparation requirements, expiration, and
action/side-effect budgets. `AuthorityFirewall` produces a structured,
bounded `FirewallDecision` before dispatch. The receipt records a policy ID
and digest, the required and granted authority classes, matched rule, origin,
action type, and rejection reason; it never contains secret values.

Operation provenance is retained as informational metadata. It is not an
authority grant. In particular, web or third-party provenance cannot upgrade
itself to user or host authority. The firewall can enforce declared authority
boundaries independently of a model's safety judgment. It does **not** detect
or guarantee immunity from prompt injection, social engineering, compromised
host policy, or browser/site vulnerabilities.

Browser observations and `ObservationReference` carry `web_untrusted` by
default. When a reference is used in a governed session, its label is
monotonically merged into firewall input; supplied primitives cannot remove or
upgrade provenance. This is deterministic metadata propagation, not whole
program semantic taint tracking: if a planner extracts page text and submits a
new unlabelled value, the runtime cannot prove that influence. Hosts must keep
labels at application boundaries and use explicit host-authorized values for
privileged decisions.

An `authority_envelope` can be represented in a canonical plan document for
transport and review. Parsing it does not grant it: a host must install the
same envelope at the stateful-session boundary. Governed ordered plans are
currently rejected rather than bypassing per-operation enforcement; execute
their declared operations through the retained session boundary.

## Browser Two-Phase Commit

Host policy declares which action types require preparation. `prepare_operation`
captures the current page ID, origin, bounded target state, material DOM
fingerprint, exact operation hash, policy hash, and firewall decision, then
returns a short-lived opaque `PreparedOperation` token. Values used in payload
comparison are stored only in the retained session; public records contain
only hashes.

`commit_operation` rechecks expiry, token consumption, payload substitution,
page/origin/target/material state, and authority policy before dispatching the
original stored operation. Tokens are consumed at most once. A successful
commit means DingDongDitch dispatched the prepared browser action and ran its
normal post-state verification. It never claims to roll back an external HTTP
request, deletion, purchase, or message if that verification fails.

The public prepared fingerprint is a per-session HMAC, not an offline oracle
for transient form, CSRF, or secret values. Material state includes scoped
document identity/mutation epoch, history state, control values, target
identity, and compact page-registry facts. This catches ordinary DOM/form/
history/popup changes, including a mutation that reverts. It cannot prove that
hostile page JavaScript has not tampered with its own realm instrumentation,
observe remote session expiry, or roll back an already-dispatched request.

For a prepared secret `fill`, a provider must implement `SecretProvider.bind`,
`assert_bound`, and `resolve_bound`. It binds an opaque immutable provider/
scope/generation identifier at prepare and rejects rotation, scope/provider
replacement, or generation loss at commit. That identifier remains only in the
live prepared record and never appears in a receipt. Generic legacy providers
fail closed for prepared-secret actions; DingDongDitch never hashes or stores
plaintext secret values.

## Quorum Verification

An operation can declare `VerificationQuorum` with `all` or `n_of_m` policy.
Every check references a declared expectation and an evidence-source class.
Duplicate source classes and duplicate expectation references are rejected, so
multiple interpretations of one DOM or network signal cannot satisfy quorum.

`VERIFIED` requires the declared quorum. `NOT_VERIFIED` means the known
failures make quorum impossible; `INDETERMINATE` means available evidence
cannot justify either conclusion. Current runtime-backed source classes are
DOM/state, browser/page state, and network through ordinary expectations;
unsupported host callback checks are rejected unless a bounded adapter is
added in a future release.

## Cryptographic Receipt Chain

`hash_receipt`, `verify_receipt_hash`, and `verify_receipt_chain` use standard
library SHA-256 over canonical JSON. Each stateful execution receipt receives
a compact `receipt_chain` entry containing its predecessor hash, relevant
payload hash, policy hash, operation hash, bounded-evidence hash, artifact
checksums, runtime version, and schema version. Timing and telemetry noise are
intentionally outside the payload; outcome, governance, verification, bounded
evidence, and artifact checksums are covered.

Chain v3 canonicalization is NFC-normalized JSON with finite numbers only;
booleans remain distinct from integers, mappings are key-sorted, sequences are
ordered, and bytes-like values are rejected. Field presence is explicit for
optional receipt fields. Runtime receipt schemas reject unknown additions; for
direct mapping callers, otherwise-unknown additive fields are bound as an
`extensions` object. Timing/telemetry/cleanup are the intentionally excluded
non-truth operational fields.

This is tamper-evident chaining, not cryptographic signing. It proves neither
who produced a receipt nor that an independent party witnessed it. Signed Plan
Authority and Execution Attestation are separate, explicitly scoped layers;
neither changes the limitations of the hash chain itself.

`make_receipt_chain_checkpoint` exports `{session_id, chain_length,
chain_head_hash, timestamp_ms, runtime_version}` for independent host
retention. `verify_receipt_chain_against_checkpoint` requires the exact
checkpointed prefix/head and permits later extension. This is tamper-evidence
relative to the trusted retained checkpoint: it detects truncation, reorder,
cross-session splice, and rewrites that do not preserve that head. It is not
signing, producer identity, independent attestation, or protection if both
chain and checkpoint are rewritten.

## Cross-agent hot handoff

Opening a session with an `agent_id` issues a control lease token. A handoff
is prepared with `prepare_agent_handoff` and claimed by a new neutral planner
identity through `claim_agent_handoff`. Claiming is single-use and increments
the control epoch. Future mutation requires the new exact agent ID and control
token; stale callers are rejected. Observation references retain their control
epoch, so an old reference cannot be used to mutate after handoff.

The browser process, context, authenticated state, open tabs, page IDs,
authority envelope, remaining budgets, and receipt-chain head remain in the
same retained DingDongDitch session. Handoff objects expose only safe page
metadata, a fresh compact checkpoint, governance summaries, and pending
preparation status. They never expose raw Playwright objects, cookies,
credentials, secret values, local paths, or private authentication material.

Prepared transactions are invalidated by default during handoff. A host may
set `transfer_prepared_operations=True` explicitly in its authority envelope;
the new controller still needs the prepared token and passes the normal commit
rechecks. The new planner never obtains broader authority merely by taking
control.

Recommended handoff supplies `recipient_agent_id`; a checkpoint then rejects
another claimant, stale epoch, expiry, replay, and superseded offers.
`GovernedAgentService` additionally requires a transport-authenticated
principal matching the recipient. Hosts may use authenticated local IPC, mTLS,
or an authenticated queue, but must deliver bearer tokens only over that
protected channel. A bare process-local token is legacy compatibility, not
remote process authentication.

## Public APIs and schemas

The agent-facing APIs are `TrustedHostRuntime`, `GovernedAgentSession`, and
`GovernedAgentService`. Legacy stateful APIs are host-only compatibility paths.
The canonical machine contract includes operation provenance, verification
quorum, optional plan authority envelope, bounded `speculative_plans`, and
governance receipt fields. CLI schema output additionally exposes
`prepared-operation`, `agent-handoff-checkpoint`, `agent-handoff`,
`signed-plan-authority`, `agent-identity`, `identity-assertion`,
`mutation-evidence`, `execution-attestation`, and `speculative-plan` schemas.

Run `python examples/governed_hot_handoff_demo.py` for a deterministic local
fixture covering governance controls without any external AI API.
`python examples/complete_governance_demo.py` exercises the all-ten path:
same user-owned identity across two different planner IDs, a signed embedded
speculative graph, mutation-staled commit/reprepare, checkpoint retention,
and an offline verification of a separately processed attestation.
