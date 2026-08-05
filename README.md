# DingDongDitch

DingDongDitch is a deterministic browser execution runtime for browser
automation and AI applications. Developers author explicit `ExecutionPlan`
documents; DingDongDitch validates them, executes bounded browser operations,
checks declared expectations, and returns structured receipts. It is not an AI
agent and does not invent workflows.

## Why DingDongDitch?

- Deterministic, ordered browser execution
- Explicit verification instead of inferred success
- Structured, immutable execution receipts
- Named persistent browser profiles and session transfer
- Model-neutral contracts for developer tools and AI applications
- Fail-closed target resolution with no silent locator healing

## Quick Start

Requires Python 3.11 or newer.

```bash
git clone <repository-url>
cd DINGDONGDITCH
python -m pip install -e .
python -m playwright install chromium
python -m dingdongditch profile create demo
python -m dingdongditch run examples/plans/example_navigation_verified.json --profile demo --headed
```

Chromium opens `https://example.com`, verifies the final URL and visible page
text, writes a concise result to the terminal, closes cleanly, and preserves the
named profile for later runs.

Remove the example profile when finished:

```bash
python -m dingdongditch profile remove demo
```

Install all bundled browser engines and development dependencies with:

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium firefox webkit
```

## Example

The canonical verified plan is
[`examples/plans/example_navigation_verified.json`](./examples/plans/example_navigation_verified.json):

```json
{
  "browser": {
    "provider": "playwright",
    "engine": "chromium",
    "channel": "bundled",
    "headless": false
  },
  "plan": {
    "plan_id": "example",
    "failure_policy": "stop_on_failure",
    "operations": [
      {
        "operation_id": "nav",
        "url": "https://example.com",
        "action": { "type": "navigate" },
        "expectations": [
          {
            "type": "url",
            "url_value": "https://example.com/",
            "url_match": "exact"
          },
          {
            "type": "text",
            "locator": { "strategy": "exact_text", "value": "Example Domain" },
            "text_value": "Example Domain",
            "text_match": "contains"
          }
        ]
      }
    ]
  }
}
```

The CLI consumes authored plans from a file or standard input. It never authors,
heals, or reinterprets them.

## Core Capabilities

- Ordered plans and standalone operations with bounded timeouts
- Explicit URL, DOM, text, attribute, network, and page-state expectations
- `VERIFIED`, `NOT_VERIFIED`, `INDETERMINATE`, and `EXECUTION_FAILED` receipts
- Bundled Chromium, Firefox, and WebKit in headed or headless mode
- Named profiles with automatic startup, readiness checks, exclusive locks, and clean shutdown
- Persistent Chromium sessions with cookie and origin-local-storage state
- Session export, import, validation, and clear commands
- Explicit guarded optional target actions
- Runtime-only secret injection and generic authentication callbacks
- Declared waits, one-level iframe targeting, downloads, native dialogs, and tab/page operations
- Read-only target and page inspection for active host-owned sessions

## Guarded Optional Actions

A guarded action expresses one narrow conditional explicitly:

- If the declared target exists, dispatch the action and verify its normal expectations.
- If the target is conclusively absent, dispatch nothing and verify the declared already-satisfied state.

```json
"guard": {
  "when_target_absent": {
    "expectations": [
      {
        "type": "element_exists",
        "locator": { "strategy": "css", "value": "#consent-banner" },
        "exists": false
      }
    ]
  }
}
```

Only a clean zero-match result selects the absent branch. Ambiguous targets,
backend errors, action failures, and failed postconditions remain failures.
Unguarded actions retain strict missing-target behavior.

## Authentication & Sessions

Named profiles are application-managed browser state containers:

```bash
python -m dingdongditch profile create work
python -m dingdongditch profile list
python -m dingdongditch session export work session.json
python -m dingdongditch session clear work
python -m dingdongditch session import work session.json
python -m dingdongditch profile remove work
```

Session files contain validated cookies and origin local storage. They are
sensitive application artifacts and are not encrypted credential vaults.

Applications may provide a `SecretProvider` for short-lived browser injection
and register generic callbacks for authentication-required, OTP, TOTP, passkey,
and WebAuthn requests. DingDongDitch executes explicitly authored browser
operations; it does not store credentials or implement website-specific login
flows.

## Receipts

Every operation and plan produces browser-observable evidence and a structured
verdict:

- `VERIFIED`: every required expectation passed with fresh evidence.
- `NOT_VERIFIED`: execution completed, but a declared expectation failed.
- `INDETERMINATE`: the runtime could not make a justified success or failure claim.
- `EXECUTION_FAILED`: validation, setup, resolution, or action dispatch failed.

```json
{
  "plan_id": "example",
  "plan_verdict": "VERIFIED",
  "completion_status": "completed",
  "declared_step_count": 1,
  "verified_step_count": 1
}
```

Receipts include step results, lifecycle identifiers, target-resolution traces,
expectation evidence, timing, cleanup state, and guarded-branch selection where
applicable. Receipt success describes browser-observable facts, not external
world truth.

## Project Philosophy

- Deterministic: the host authors every operation and expected outcome.
- Explicit: URLs, targets, actions, guards, waits, and verification are declared.
- Fail-closed: malformed, ambiguous, stale, or unsupported inputs do not dispatch.
- Bounded: timeouts and retry windows are finite and authored.
- Model-neutral: no model or AI provider owns the execution contract.
- Observable: success requires evidence, not merely a successful tool call.
- Non-autonomous: no hidden AI decisions, silent locator healing, or invented recovery.

See [Engineering Principles](./Engineering/ENGINEERING_PRINCIPLES.md) and
[Non-Goals](./Engineering/NON_GOALS.md) for the full architectural boundaries.

## Current Limitations

- Website-specific selectors and behavior belong in plans or host applications.
- External websites may change and should not be the sole CI validation source.
- Plans are ordered and stop on failure; general branches, loops, and DAGs are unsupported.
- Guarded actions cover only explicit target-present/target-absent behavior.
- Persistent named profiles currently require Chromium.
- Only Playwright-bundled Chromium, Firefox, and WebKit are generally supported; native Safari is unsupported.
- Iframe targeting is limited to one declared level with no automatic frame search.
- Authentication integrations are callback-driven; no website-specific login flows exist.
- Session transfer covers cookies and origin local storage, not every browser data store.
- Upload actions and arbitrary JavaScript execution from plans are unsupported.

The repository remains pre-1.0; review the [changelog](./CHANGELOG.md) when
upgrading between minor versions.

## Roadmap

Future work is kept separate from implemented behavior:

- Application-provided passkey and WebAuthn transports
- External secret-manager adapters
- Upload contracts and additional portable browser-state support
- Nested-frame paths and additional browser capabilities
- Additional installed browser-channel support where it can remain deterministic

Roadmap items are not part of the current runtime contract.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Please review the
[engineering principles](./Engineering/ENGINEERING_PRINCIPLES.md) and
[non-goals](./Engineering/NON_GOALS.md) before proposing architectural changes.

Project policies: [Support](./SUPPORT.md) · [Security](./SECURITY.md) ·
[Governance](./GOVERNANCE.md) · [Code of Conduct](./CODE_OF_CONDUCT.md)

## License

DingDongDitch is available under the [MIT License](./LICENSE).
