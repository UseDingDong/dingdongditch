# DingDongDitch

DingDongDitch is a deterministic browser-execution runtime for browser
automation and AI applications. A host authors explicit `ExecutionPlan`
documents; DingDongDitch validates them, executes bounded browser operations,
verifies declared expectations, and returns structured receipts. It is not an
AI agent and never invents workflows.

## Quick start

Requires Python 3.11 or newer.

```bash
git clone <repository-url>
cd DINGDONGDITCH
python -m pip install -e ".[dev]"
python -m playwright install chromium firefox webkit
python -m dingdongditch run examples/plans/example_navigation_verified.json
```

The CLI consumes authored JSON from a file or standard input. It does not
author plans, heal locators, retry arbitrarily, or reinterpret intent.

## Core capabilities

- Ordered plans and standalone operations with bounded timeouts and fresh
  browser-observable verification.
- `VERIFIED`, `NOT_VERIFIED`, `INDETERMINATE`, and `EXECUTION_FAILED` verdicts.
- Chromium, Firefox, and WebKit through Playwright, with no engine fallback.
- Explicit guarded branches, declared waits, bounded nested frame paths,
  downloads, dialogs, and page operations.
- Deterministic file uploads and custom combobox/autocomplete selection.
- Network request/response metadata assertions and optional sanitized trace
  artifacts.
- Isolated persistent profiles, portable browser state, runtime-only secret
  injection, and bounded host WebAuthn participation.
- Model-neutral contracts, fail-closed target resolution, and no silent locator
  healing.

## Guarded branches and frame paths

Guards are finite declared UI-state branches, not general workflow control
flow. A matching branch may run a bounded preparation-action list before the
primary action; no branch match fails, and multiple matches are
`INDETERMINATE`. Legacy `when_target_absent` guards remain compatible.

Element-scoped actions, waits, expectations, page preconditions, and
inspection can use either legacy one-hop `frame` or explicit bounded
`frame_path`. Every hop is resolved in order. DingDongDitch never searches
frames or falls back to the main document. See
[iframe targeting](./Engineering/Phase%203/IFRAME_TARGETING.md).

## Stateful sessions and browser state

`StatefulSessionRuntime` provides a host-owned
`open -> observe -> execute -> verify -> observe -> close` lifecycle without
exposing raw Playwright objects. It preserves ordinary validation, evidence,
profile locking, and cleanup behavior. See the
[stateful-session guide](./Engineering/Phase%203/STATEFUL_SESSIONS.md) and
[`examples/stateful_session_example.py`](./examples/stateful_session_example.py).

Portable state uses a versioned schema. Explicit exports can contain cookies,
sanitized origin-localStorage, and opt-in IndexedDB. Treat exported state as
sensitive session material: DingDongDitch does not retain it or act as a
credential vault. IndexedDB is importable only when creating a new ephemeral
context; sessionStorage, password managers, browser profile internals,
extensions, caches, history, and passkeys are not portable. The full boundary
is documented in [remaining infrastructure boundaries](./Engineering/REMAINING_INFRASTRUCTURE_BOUNDARIES.md).

Isolated named/DingDong profiles are supported for Chromium, Firefox, and
WebKit where Playwright provides persistent contexts. There is no silent
engine fallback or existing-profile migration between engines. Chromium's
existing `default` profile is partially supported; existing Firefox and WebKit
user profiles are unsupported.

## Interactions

`upload_file` requires exact absolute file paths plus an explicit host
allowlist or allowed root. It operates direct HTML file inputs, redacts local
paths in receipts, and verifies fresh browser state even when a legitimate
upload replaces the original input. It does not automate native file dialogs,
directory uploads, file-chooser buttons, wildcard paths, or file discovery.

[`examples/plans/upload_file.json`](./examples/plans/upload_file.json) is a
portable template: replace its `/absolute/path/to/...` values with the exact
authorized paths for your host before running it.

`select_combobox_option` handles associated custom combobox/listbox controls
only when one explicit option matches and remains selected after interaction.
Typing or blindly pressing Enter is never treated as selection.

## Receipts, evidence, and network assertions

Receipt schema **1.8.0** separates truth from diagnostics:

1. **Core Receipt** — compact deterministic verdict, status, target summary,
   timing, and session/page identity.
2. **Bounded Evidence** — sanitized failure, freshness, action, and network
   evidence sufficient to justify the verdict.
3. **Artifacts** — optional external references such as redacted screenshots
   or a bounded sanitized network trace; never raw paths, image bytes, headers,
   or request/response bodies.

Network assertions can require a request or response, HTTP method, bounded
query-free URL/path match, status, and observable request-to-response timing.
Exactly one post-action match is required; ambiguity is `INDETERMINATE`.
Per-operation HAR is deliberately unsupported because it is context-wide and
can capture unrelated traffic.

See the [receipt architecture](./Engineering/THREE_LAYER_RECEIPT_ARCHITECTURE.md)
and [network/state/authentication boundaries](./Engineering/REMAINING_INFRASTRUCTURE_BOUNDARIES.md).

## Secrets and WebAuthn

Hosts may provide a `SecretProvider`; plans carry only opaque
`SecretReference` values and the runtime resolves them just in time into an
ephemeral buffer for one fill. Resolved values are not persisted, serialized,
or logged.

WebAuthn participation is explicit and host-controlled. DingDongDitch sends a
bounded metadata-only transport event and records completed, rejected,
unsupported, timeout, or indeterminate participation. It does not control a
native authenticator, create virtual credentials, extract private keys, supply
assertions, or bypass authentication. A host callback alone is not browser
verification.

## Project boundaries

- Hosts declare URLs, targets, actions, guards, waits, and expected outcomes.
- Malformed, ambiguous, stale, unsupported, or unverifiable input fails closed.
- Plans are ordered; there are no arbitrary loops, DAGs, autonomous retries,
  natural-language planning, or site-specific browser logic.
- Arbitrary JavaScript execution from plans is unsupported.

See [Engineering Principles](./Engineering/ENGINEERING_PRINCIPLES.md),
[Non-Goals](./Engineering/NON_GOALS.md), and the
[plan-runner documentation](./Engineering/Phase%203/PLAN_RUNNER_CLI.md).

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
