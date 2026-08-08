# Stateful Sessions

The stateful facade is the public boundary for hosts that need an interactive
`open -> observe -> execute -> verify -> observe -> close` lifecycle. It is a
thin owner around the existing Playwright backend, observer, executor,
verifier, evidence, and receipt pipeline; it does not expose Playwright
objects or introduce a second execution system.

## Public API

Create a `StatefulSessionRuntime` when the host wants its own registry, or use
the module-level singleton functions exported by `dingdongditch`:

```python
runtime = StatefulSessionRuntime(default_idle_timeout_ms=900_000)
session = runtime.open_session(BrowserConfig(headless=True))
try:
    observation = runtime.observe_page(session.session_id)
    result = runtime.execute_operation(session.session_id, operation)
    pages = runtime.inspect_pages(session.session_id)
    dialogs = runtime.inspect_dialogs(session.session_id)
finally:
    runtime.close_session(session.session_id)
```

The class surface is `open_session`, `get_session`, `observe_page`,
`execute_operation`, `execute_plan`, `inspect_pages`, `select_page`,
`inspect_dialogs`, `close_session`, and `cleanup_expired_sessions`. The
module-level observation/execution/inspection names include `session` to avoid
collisions with the existing stateless API.

`SessionObservation.reference(element_id)` creates an observation reference
that can be supplied to a later operation. Existing freshness validation
rejects references after document or target identity changes. Page selection
is always explicit and uses stable page IDs. Popup, navigation, dialog, and
download deltas are reported in operation results.

## Ownership and isolation

Each session owns one backend, browser, browser context, page registry,
profile lease, and artifact state until close or expiry. Backends may share
the process-local Playwright driver because the synchronous API permits only
one driver per thread; browser contexts and all web state remain separate.
The registry never returns backend, Browser, BrowserContext, or Page objects.

Opaque session IDs are resolved only inside their creating runtime. Unknown,
closed, expired, and terminal sessions fail closed. A non-blocking per-session
lock prevents overlapping commands while allowing separate sessions to make
independent progress. Named-profile locking remains enforced by the existing
authentication/profile subsystem.

Close is idempotent. Idle expiry is synchronous on access or explicit cleanup,
so no background thread is required. Tombstones retain only sanitized session
metadata. An ordinary failed receipt is recoverable while the backend remains
usable; loss of the page/context/browser marks the session terminal.

## Errors and safety

`StatefulSessionError.to_dict()` returns a stable `failure_kind` and sanitized
message. Kinds cover missing, closed, expired, busy, configuration-mismatched,
profile-locked, startup-failed, invalid-page, terminal-browser, rejected
operation, and cleanup-failed conditions. Operation validation failures remain
normal structured execution receipts from the existing pipeline.

All operations use existing contracts. In particular, `upload_file` still
requires exact absolute paths and explicit host authorization through
`allowed_files` or `allowed_roots`; receipts retain their path redaction.

## Choosing an execution mode

Use the stateful facade for a host that observes and decides incrementally or
must preserve browser state between calls. Use the existing batch CLI for a
complete deterministic plan that can run and close in one invocation.

Known limitations: the registry is process-local and synchronous; it is not a
network service, durable session store, MCP server, or Codex adapter. Calls for
one session must stay on the thread that opened its Playwright driver. Expiry
is cleanup-on-access rather than scheduled cleanup.

See `examples/stateful_session_example.py` for navigation, observation,
sequential execution, an explicitly authorized upload, receipt verification,
and guaranteed close against a deterministic local page.
