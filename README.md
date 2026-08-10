# DingDongDitch

DingDongDitch is a model-neutral, fail-closed browser execution runtime. Your
AI agent, developer code, CI job, or test remains the planner: it declares the
browser operations and expected outcomes. DingDongDitch executes only those
operations, verifies the resulting browser state, and returns structured
receipts instead of guessing, healing ambiguous locators, or inventing work.

```text
External Agent / Planner
        ↓
DingDongDitch Machine Contract
        ↓
ExecutionPlan
        ↓
DingDongDitch Runtime
        ↓
Browser
        ↓
Structured Receipt
```

It is execution infrastructure, not an AI agent or a workflow engine.

## Execution governance

Stateful hosts can opt into ten composable controls: **Authority Firewall**,
browser **Two-Phase Commit**, **Quorum Verification**, SHA-256 receipt chains
and checkpoints, **Cross-Agent Hot Handoff**, **Signed Plan Authority**,
user-owned **Agent Identity**, human/agent **Mutation Arbitration**,
host/external **Execution Attestation**, and bounded **Transactional
Speculative Execution**. These controls enforce host-declared authority
boundaries; they do not make prompt injection impossible or provide external
server-side rollback. See [Execution governance](./Engineering/EXECUTION_GOVERNANCE.md)
and run `python examples/complete_governance_demo.py` for a local deterministic
all-ten demonstration without an AI API.

For a new agent product, expose `GovernedAgentSession` (or authenticated
`GovernedAgentService`) rather than raw execution helpers. `TrustedHostRuntime`
retains policy installation, secrets, browser lifecycle, and handoff-token
delivery; the machine contract is a proposal format. The exact trust boundary
and limitations are in [Execution governance](./Engineering/EXECUTION_GOVERNANCE.md).

## MCP quick start

DingDongDitch provides an optional, stdio-only MCP adapter for the stable MCP
protocol revision **2026-07-28**. It is transport glue over a host-created
`GovernedAgentService` lease, not a second browser executor.

```text
MCP-capable agent
        ↓
DingDongDitch MCP
        ↓
governed browser execution
        ↓
structured receipt
```

```bash
python -m pip install "dingdongditch[mcp]"
dingdongditch mcp-stdio --bootstrap my_host:build --principal local-agent
```

`my_host.build(principal)` is trusted host code that installs the authority
envelope and opens a `GovernedAgentSession` for exactly that principal. An MCP
client then discovers only governed observation, execution, two-phase-commit,
and bounded-speculation tools. It never receives browser objects, control or
handoff tokens, secrets, private keys, trust registries, or policy-installation
capabilities. See [MCP adapter](./Engineering/MCP_ADAPTER.md), the minimal
[bootstrap example](./examples/mcp_host_bootstrap.py), and the no-key local
[MCP demo](./examples/mcp_stdio_demo.py).

The adapter remains model-neutral: any MCP-capable host or agent can use this
same governed interface, regardless of its model or vendor.

## Connect Any Agent

DingDongDitch publishes a versioned, Draft 2020-12 machine contract for
external planners. The generic JSON Schema path is the primary integration
mechanism; vendor envelopes are optional conveniences.

Your model is not part of the DingDongDitch architecture. It does not matter
whether the plan comes from GPT, Claude, Gemini, Grok, DeepSeek, Llama, Qwen,
another hosted model, a local model, an experimental model, or an agent you
are building yourself. If the host can produce a valid DingDongDitch plan that
satisfies the published machine contract, DingDongDitch can execute it.

That includes future models, private/internal company models, fine-tuned
models, locally hosted and open-source models, experimental research agents,
personal agent projects, and deterministic non-LLM planners. This is an
execution-interface compatibility claim, not a claim that every planner can
reliably produce valid plans. DingDongDitch does not integrate with a model's
reasoning; it defines the execution boundary beneath it. If a system can emit
the contract, it can target the runtime.

```text
planner/model
      ↓
canonical DingDongDitch JSON Schema
      ↓
PlanDocument → parse/validate → execute
      ↓
structured receipt
```

```python
import dingdongditch as dingdong

# Give this vendor-neutral declaration to any system that can emit JSON.
tool = dingdong.execution_plan_tool()
schema = dingdong.execution_schema()

# The model call is deliberately outside DingDongDitch.
raw_document = {
    "schema_version": "1.0.0",
    "browser": {"engine": "chromium", "channel": "bundled", "headless": True},
    "plan": {
        "plan_id": "example",
        "operations": [{
            "operation_id": "open-example",
            "url": "https://example.com",
            "action": {"type": "navigate"},
            "expectations": [],
        }],
    },
}

# `raw_document` could instead come from a local program, a private model,
# a hosted model, or a deterministic planner.
document = dingdong.parse_plan_document(raw_document)
policy = dingdong.AuthorityEnvelope(
    policy_id="host-policy",
    granted_authorities=(dingdong.ProvenanceClass.HOST_POLICY,),
    allowed_origins=("https://example.com",),
    allowed_action_types=("navigate",),
)
host = dingdong.TrustedHostRuntime()  # trusted host owns policy/secrets/lifecycle
agent = host.open_governed_agent_session(authority_envelope=policy, agent_id="planner-a")
result = agent.execute(document.plan.operations[0])
assert result.receipt.authority_decision["outcome"] == "AUTHORIZED"
```

`parse_execution_plan(raw_document)` is also public when a host wants the
typed `ExecutionPlan` directly. Use `dingdong.execution_schema()` for the
canonical `PlanDocument` JSON Schema, or `dingdongditch schema plan-document`
from the CLI. No integration needs to import `plan_json` or recreate
DingDongDitch enums.

## Agent Integration Guides

The [agent integration guide](./Engineering/AGENT_INTEGRATION_GUIDE.md) covers
the vendor-neutral path first, then optional dependency-free envelopes for
OpenAI / GPT / Codex, Anthropic Claude / Claude Code, and Google Gemini. It
also documents the canonical-schema path for xAI Grok, DeepSeek, Meta Llama,
Qwen, Mistral, Ollama/local models, OpenAI-compatible API servers, generic
tool-calling and structured-output agents, custom/private models,
experimental/local agents without a vendor SDK, and non-LLM planners.

The guide also covers public schema-export APIs, `execution_plan_tool()`,
`parse_plan_document()` / `parse_execution_plan()`, structured
`ContractValidationError` / `ValidationIssue` handling, CLI export, and
validated `ExecutionReceipt`, `PlanReceipt`, and `PageObservation` consumption.
The generic schema remains authoritative; optional
`dingdongditch.adapters.openai`, `.anthropic`, and `.gemini` modules only
reshape that same contract.

## Quick start

Requires Python 3.11 or newer. This runs a repository-local deterministic
fixture, verifies declared browser state, and writes an inspectable receipt.

```bash
git clone <repository-url>
cd DINGDONGDITCH
python -m pip install -e ".[dev]"
python -m playwright install chromium
python -m dingdongditch run-plan examples/plans/basic_navigation.json --output artifacts/quickstart-receipt.json
python -m json.tool artifacts/quickstart-receipt.json
```

The terminal reports the plan verdict; the JSON file contains step receipts,
verification results, timing, and bounded evidence. `artifacts/` is ignored by
Git so local receipt output does not pollute a working tree.

For trusted-host compatibility code (not an LLM capability), a host may still
construct an `ExecutionPlan` using the typed API or JSON, then consume the
result:

```python
from dingdongditch import execute_plan

# `plan` was authored by your host, agent, CI job, or test -- not by DingDongDitch.
receipt = execute_plan(plan)
result = receipt.to_dict()
if result["plan_verdict"] != "VERIFIED":
    print(result)  # The host decides what to do next; the runtime does not.
```

See the runnable [host API example](./examples/host_execution_plan.py) and the
[JSON plan guide](./examples/plans/README.md). The CLI and runtime never
author plans, reinterpret intent, or choose recovery steps.

## What DingDongDitch provides

- A governed host/planner boundary with Authority Firewall, Two-Phase Commit,
  Quorum Verification, receipt-chain checkpoints, and Cross-Agent Hot Handoff.
- Exact Ed25519 Signed Plan Authority; portable user-owned Agent Identity;
  bounded mutation arbitration; host or independently keyed execution
  attestation; and signed, deterministic speculative continuations.

- Deterministic browser actions, declared waits, page operations, and strict
  target cardinality across Playwright Chromium, Firefox, and WebKit.
- Verification-backed structured receipts, bounded failed-verification
  evidence, and standardized per-operation timing.
- Bounded guarded branches, including explicit `otherwise`, and declared nested
  same-page `frame_path` targeting with no frame search or document fallback.
- Explicitly authorized `upload_file` actions and deterministic
  `select_combobox_option` selection for custom combobox/autocomplete controls.
- Deterministic network request/response metadata assertions and optional
  sanitized network trace artifacts.
- `StatefulSessionRuntime` for host-owned incremental browser sessions.
- Portable browser-state schema v2, including opt-in IndexedDB only within its
  new-context import boundary.
- Isolated persistent profiles for supported Chromium, Firefox, and WebKit
  configurations, without browser-engine fallback.
- Host-owned `SecretProvider` / opaque `SecretReference` injection and bounded,
  host-controlled WebAuthn participation.

## Receipts verify state, not just dispatch

An action being dispatched does not prove that the intended state resulted. An
operation is `VERIFIED` only when every declared expectation passes with fresh
browser evidence. A click or upload may therefore dispatch successfully and
still be `NOT_VERIFIED` or `INDETERMINATE` if the declared result is absent or
cannot be justified.

| Verdict | Meaning |
| --- | --- |
| `VERIFIED` | The action completed and all declared expectations passed with fresh evidence. |
| `NOT_VERIFIED` | Execution completed, but a declared expectation was false. |
| `INDETERMINATE` | Evidence was ambiguous, stale, unavailable, or otherwise insufficient for a justified claim. |
| `EXECUTION_FAILED` | Validation, setup, target resolution, or browser dispatch failed. |

Receipt schema **1.8.0** separates control-flow truth from diagnostics:

1. **Core Receipt** — compact verdict, status, target summary, timing, and
   browser/session identity.
2. **Bounded Evidence** — sanitized verification, failure, freshness, action,
   and network evidence that explains the verdict.
3. **Optional Artifacts** — safe external references to heavyweight material,
   such as redacted screenshots or a bounded sanitized network trace.

Artifacts never become proof by themselves. Core receipts never contain DOM
dumps, network bodies, headers, screenshot bytes, or absolute paths. New API
consumers can use `ExecutionReceipt.to_layered_dict()`; `to_dict()` remains
available for compatibility. See the
[three-layer receipt guide](./Engineering/THREE_LAYER_RECEIPT_ARCHITECTURE.md).

## Stateful sessions, profiles, and portable state

`StatefulSessionRuntime` provides a host-owned
`open -> observe -> execute -> verify -> observe -> close` lifecycle without
exposing raw Playwright objects. It retains normal validation, evidence,
profile-locking, and cleanup semantics. See the
[stateful-session guide](./Engineering/Phase%203/STATEFUL_SESSIONS.md) and its
[runnable example](./examples/stateful_session_example.py).

Portable state v2 can explicitly export cookies, sanitized origin-localStorage,
and opt-in IndexedDB. Exported state is sensitive session material, not a
credential vault. IndexedDB is importable only while creating a new ephemeral
context; sessionStorage, password managers, browser-profile internals,
extensions, caches, history, and passkeys are not portable.

Isolated named/DingDong profiles are supported for Chromium, Firefox, and
WebKit where Playwright provides persistent contexts. Chromium's existing
`default` profile is partially supported; existing Firefox and WebKit user
profiles are unsupported. Profiles are engine-isolated and never migrated
between engines.

## Interactions, network, and host authentication

`upload_file` requires exact absolute paths plus an explicit host allowlist or
allowed root. It supports direct HTML file inputs, redacts local paths in
receipts, and can verify legitimate input replacement or attachment UI changes.
[`examples/plans/upload_file.json`](./examples/plans/upload_file.json) is a
portable template: replace its `/absolute/path/to/...` values before running.

`select_combobox_option` requires one explicitly matching associated option and
verifies that the selection persisted. Typing or blindly pressing Enter is not
treated as selection.

Network expectations can require observed request/response metadata, method,
query-free URL/path matching, status, and observable timing. Exactly one
post-action match is required; ambiguity is `INDETERMINATE`. An explicit
`NetworkArtifactRequest` can write a bounded sanitized trace reference.

Hosts provide secrets through `SecretProvider`; plans carry opaque
`SecretReference` values and resolved values are used ephemerally, never
persisted or logged. WebAuthn participation is similarly explicit and
host-controlled: the runtime exchanges bounded metadata/status only, and a
host callback alone is not browser verification.

For the exact network, portable-state, profile, secret, and WebAuthn boundaries,
see [remaining infrastructure boundaries](./Engineering/REMAINING_INFRASTRUCTURE_BOUNDARIES.md).

## Boundaries and limitations

- No autonomous planning, goal invention, silent locator healing, arbitrary
  retries, arbitrary predicates, loops, or general workflow/DAG engine.
- No site-specific browser or authentication logic, arbitrary JavaScript from
  plans, or browser-engine fallback. Native Safari is unsupported.
- No credential-vault behavior, plaintext secret persistence, native WebAuthn
  authenticator control, virtual authenticators, private-key extraction, or
  authentication bypass.
- No per-operation HAR; only explicit bounded sanitized network traces are
  supported. Request/response bodies and headers are not captured as evidence.
- No native file-dialog automation, directory uploads, file-chooser trigger
  buttons, wildcard paths, or implicit file discovery.
- No active-context IndexedDB import or portable sessionStorage, password
  managers, browser-profile internals, extensions, caches, history, or passkeys.
- No existing-profile migration between engines. Firefox/WebKit existing user
  profiles are unsupported.

See [Engineering Principles](./Engineering/ENGINEERING_PRINCIPLES.md),
[Non-Goals](./Engineering/NON_GOALS.md), and the
[plan-runner documentation](./Engineering/Phase%203/PLAN_RUNNER_CLI.md).

## Further reading

- [JSON execution plans](./examples/plans/README.md)
- [Stateful session API and ownership](./Engineering/Phase%203/STATEFUL_SESSIONS.md)
- [Nested iframe targeting](./Engineering/Phase%203/IFRAME_TARGETING.md)
- [Receipt/evidence/artifact architecture](./Engineering/THREE_LAYER_RECEIPT_ARCHITECTURE.md)
- [Network, state, profile, secret, and WebAuthn boundaries](./Engineering/REMAINING_INFRASTRUCTURE_BOUNDARIES.md)

## Roadmap

Future work remains separate from the public runtime contract:

- Additional installed browser channels only where they can remain
  deterministic and explicitly supported.
- New bounded evidence/artifact types only with equally strict capture,
  redaction, and verification boundaries.

## Contributing and license

See [CONTRIBUTING.md](./CONTRIBUTING.md), [SECURITY.md](./SECURITY.md), and
[GOVERNANCE.md](./GOVERNANCE.md). DingDongDitch is available under the
[MIT License](./LICENSE).
