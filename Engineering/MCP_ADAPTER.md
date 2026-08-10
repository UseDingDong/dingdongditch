# Governed MCP adapter

## Scope and protocol pin

The optional DingDongDitch MCP server is a thin transport adapter, not an MCP
replacement or second execution engine. It implements MCP protocol revision
**2026-07-28** with the official Python SDK **2.0.0** API, constrained as
`mcp==2.0.0` for a reproducible protocol/SDK pairing. The adapter is validated
against that exact dependency; updating it is an explicit compatibility and
security review, not an automatic SDK upgrade.

Only the MCP stdio transport is supported in this first release. It provides
the smallest interoperable authenticated boundary: the trusted process launcher
chooses `--principal`, starts the server, and owns its stdin/stdout pipes.
The principal is never accepted from an MCP tool argument. The official SDK
owns JSON-RPC framing, protocol discovery, and stdout isolation; DingDongDitch
does not write diagnostics to stdout. Bootstrap stdout is redirected to stderr
before the protocol opens, so stdout is reserved for MCP from process start.

```text
MCP client / untrusted planner
        |
        | MCP stdio + host-selected authenticated principal
        v
GovernedMCPServer
        |
        v
GovernedAgentService
        |
        v
StatefulSessionRuntime -> browser -> structured receipt
```

The trusted bootstrap and every governed call run on one dedicated server-side
execution thread. This preserves the synchronous Playwright backend's thread
affinity while keeping browser handles out of MCP's async protocol loop.

The adapter intentionally does not offer Streamable HTTP yet. A future HTTP
binding must add transport authentication, Origin validation, local-default
binding, DNS-rebinding defenses, request limits, and explicit host deployment
configuration; it must not reuse the stdio principal model blindly.

## Host startup

Install the optional dependency and provide a trusted Python factory:

```bash
python -m pip install "dingdongditch[mcp]"
dingdongditch mcp-stdio --bootstrap my_host:build --principal local-agent
```

`my_host:build` is evaluated by the trusted process launcher, before MCP
traffic exists. Its one argument is the launcher-selected principal; it must
return a `GovernedAgentSession` whose `agent_id` exactly matches that value.
This is where a host installs an `AuthorityEnvelope`, browser configuration,
identity assertion/registry, signed-plan verifier, secret provider, mutation
policy, and any other host-owned runtime state. A minimal example is
[`../examples/mcp_host_bootstrap.py`](../examples/mcp_host_bootstrap.py).

The transport principal is the current **control-lease owner** and is passed as
the service's server-derived `authenticated_agent_id`; it is not a
planner-claimed User-Owned Agent Identity, signer, attester, or authority
owner. A portable identity assertion remains a host-installed runtime input and
is independently checked by the existing governance layer.

The default is to close the governed browser session when stdio disconnects.
`--retain-on-disconnect` is a host-only lifecycle choice. It does not make the
next client a controller; the host must bind any successor through the normal
lease/handoff boundary.

## Planner tool surface

MCP tool discovery exposes only these tools:

| Tool | Effect |
| --- | --- |
| `dingdong.get_contract` | Read canonical PlanDocument, Operation, and speculative-plan schemas. |
| `dingdong.observe` | Capture bounded observation evidence and return an opaque observation handle. |
| `dingdong.execute` | Submit one canonical `Operation` through the existing governed runtime. |
| `dingdong.prepare` / `dingdong.commit` | Use existing Browser Two-Phase Commit for consequential work. |
| `dingdong.prepare_speculation` | Validate one bounded canonical speculative graph without branch dispatch. |
| `dingdong.select_speculative_branch` / `dingdong.execute_selected_speculative_branch` | Apply existing deterministic selection and governed execution. |

The `Operation` and `SpeculativePlan` portions of the MCP input schemas are
embedded directly from DingDongDitch's generated canonical schemas. The full
`PlanDocument` source remains available from `dingdong.get_contract`. The
adapter does not execute a whole document itself, because that would duplicate
the retained runtime's execution semantics.

Every operation still passes the existing Authority Firewall, signed-plan
matching, identity verification, control lease, mutation/freshness checks,
Two-Phase Commit where required, quorum verification, receipt-chain update,
and speculative-branch checks. MCP annotations are descriptive only and never
grant permission.

## Handles and isolation

MCP never returns real service capabilities. It mints unguessable adapter
handles for observations, prepared operations, and speculative preparations.
They are retained server-side with their real token, session, principal,
control epoch, and expiry. They are limited to 128 active records, expire no
later than their underlying runtime record, are rejected for another principal
or session, and commits/selected branch execution consume their adapter handle
before dispatch. All adapter handles are unconditionally cleared when a stdio
connection ends, including under the host-only retain-on-disconnect setting.
Consumed values leave the live table immediately; at most 128 expiry-bounded
replay tombstones remain solely to report a consumed handle as already used.
The governed runtime independently rechecks the real lease,
epoch, expiry, material state, mutation epoch, and single-use token.

The tool surface intentionally excludes policy/trust installation, browser
lifecycle, raw session inspection, checkpoints, human-mutation attribution,
identity transitions, signing, attestation, secret configuration, and all
handoff bearer-token/checkpoint delivery. Hot handoff remains host-brokered:
an MCP planner cannot receive or forward its bearer token.

## API trust classification

| Surface | Classification | Who may use it |
| --- | --- | --- |
| The eight `dingdong.*` tools above | Governed-agent safe | An MCP client/planner, through the stdio connection only. |
| `dingdong.get_contract`, `dingdong.observe` | Read-only governed tools | An MCP client/planner. Observation is still lease-checked. |
| `GovernedMCPServer.from_host_factory`, `MCPHostBinding`, `run_stdio`, `close`, `mcp.bootstrap.load_governed_session` | Trusted-host-only transport setup | The process launcher/application host. Never pass these objects to a model. |
| `tool_definitions()` | Transport adapter/read-only | MCP hosting code and tests; it only projects canonical schemas. |
| `call_tool()` | Transport adapter | A trusted embedding or test harness; it has no caller-supplied principal and is not an API for a model to invoke in-process. |
| Existing signed-plan, identity, attestation, and receipt verifiers | Cryptographic verifier / host API | Kept out of the planner tool surface. Trust registration and all private-key work remain host-only. |

`execute_plan()`, raw browser/session compatibility APIs, and `GovernedAgentService`
handoff-bearer methods are deliberately not reachable through MCP. Giving an
untrusted in-process plugin a Python reference to a trusted-host object is out
of scope for stdio authentication and is not equivalent to exposing an MCP
tool; hosts must retain those objects privately.

## Limits and non-guarantees

Tool arguments are capped at 1 MiB, 64 nested containers, and 10,000 JSON
nodes before parser/browser work; adapter handles are bounded and results are
capped at 2.5 MiB. Errors are structured, bounded,
and omit request values, paths, secret values, real control tokens, prepared
tokens, handoff tokens, and internal exception text.

Stdio process ownership is the authentication assumption. It is not a sandbox
for arbitrary code running in the same operating-system account. Remote or
multi-tenant deployments need an authenticated transport and a host principal
mapper before they can be considered; this release makes no HTTP, OAuth,
localhost, DNS-rebinding, TEE, prompt-injection, rollback, or browser-reality
attestation claim.
