# Generic Plan-Runner CLI

**Status:** Complete  
**Date:** 2026-07-26  
**Scope:** Tooling adapter only — not a new browser capability milestone

## Purpose

DingDongDitch is **execution infrastructure**. The host (developer code,
Cursor, CI, a test framework, or another application) authors a typed
`ExecutionPlan`. This CLI only **loads** that plan from a JSON file or stdin
and runs it through the existing contracts and shared Playwright executor.

```text
Developer / Cursor / CI / custom host
        ↓ authors ExecutionPlan (JSON or Python API)
plan.json  or  stdin "-"
        ↓
generic CLI adapter (dingdongditch.cli / plan_json)
        ↓
typed contract validation → execute_plan → PlaywrightBackend → PlanReceipt
```

DingDongDitch does **not** invent workflows, interpret natural language,
explore websites, or own project-specific business logic. Website-specific
targets belong in the host's plan data.

## Command syntax

```bash
python -m dingdongditch run-plan path/to/plan.json
python -m dingdongditch run-plan -
python -m dingdongditch run-plan path/to/plan.json --engine chromium|firefox|webkit
python -m dingdongditch run-plan path/to/plan.json --headed
python -m dingdongditch run-plan path/to/plan.json --headless
python -m dingdongditch run-plan path/to/plan.json --output path/to/receipt.json
python -m dingdongditch run-plan path/to/plan.json --verbose
```

`run-plan -` reads UTF-8 JSON from stdin (no temporary plan files). Validation,
execution, receipts, exit codes, lifecycle, and cleanup are identical to file
input. Relative filesystem operation URLs require a plan file path and are
rejected for stdin plans.

Installed console script (after `pip install -e .`):

```bash
dingdongditch run-plan path/to/plan.json
dingdongditch run-plan -
```

## JSON plan structure

Preferred document shape:

```json
{
  "browser": {
    "provider": "playwright",
    "engine": "chromium",
    "channel": "bundled",
    "headless": true
  },
  "plan": {
    "plan_id": "example",
    "failure_policy": "stop_on_failure",
    "operations": [
      {
        "operation_id": "nav",
        "url": "https://example.com",
        "action": { "type": "navigate" },
        "expectations": []
      }
    ]
  }
}
```

A bare `ExecutionPlan` object (`plan_id` + `operations` + optional
`browser_config`) is also accepted. Deserialization constructs the real
`BrowserConfig`, `Operation`, `Action`, `WaitCondition`, `Expectation`,
`Locator`, and `ExecutionPlan` models, then calls their `validate()` methods.
Unknown fields fail closed. There is no CLI-specific action schema.

### Explicit guarded target actions

A target-based action may declare a narrow optional-target guard. The action is
dispatched normally when its authored locator resolves uniquely. Only a clean
zero-match result selects `target_absent`, where every explicitly declared guard
expectation must pass; ambiguity, resolver errors, and dispatch failures never
select the absent branch.

```json
"guard": {
  "when_target_absent": {
    "expectations": [
      {
        "type": "element_exists",
        "locator": { "strategy": "css", "value": "#desired-state" },
        "exists": true
      }
    ]
  }
}
```

Guard expectations are required and non-empty. Unguarded operations preserve
the original strict missing-target failure semantics.

Relative operation `url` values that are not `http(s)://`, `file://`, or
`about:` are resolved against the plan file directory and converted to
`file://` URIs.

## Browser option precedence

1. Plan JSON may declare browser defaults (`browser` or `plan.browser_config`).
2. Explicit CLI `--engine`, `--headed`, and `--headless` override those defaults.
3. `--headed` and `--headless` are mutually exclusive.
4. Unsupported engines/channels and contradictory configs fail before launch.
5. There is no silent engine fallback. Native Safari is not supported.

## Validation behavior

Invalid JSON, missing files, unknown fields, unknown actions, invalid enums,
missing required fields, and unsupported engine/channel combinations fail
**before** browser dispatch with exit code `1`. Concise structured errors are
printed; stack traces only with `--verbose` on unexpected internal failures.

## Receipt output

`--output` writes the complete `PlanReceipt.to_dict()` JSON (schema 2.1.0),
including stable `browser_session_id` / `context_id` / `page_id` when a session
was started.

## Process exit codes

| Code | Meaning |
|------|---------|
| 0 | Plan completed; all required steps `VERIFIED` |
| 1 | Invalid input / validation failure before or without treating as plan crash |
| 2 | Plan verdict `NOT_VERIFIED` |
| 3 | Plan verdict `INDETERMINATE` |
| 4 | Plan verdict `EXECUTION_FAILED` |
| 5 | Unexpected internal CLI error |

Expected `NOT_VERIFIED` / `EXECUTION_FAILED` results are not Python crashes.

## Authoring plans (host responsibility)

Supply explicit URLs, targets, actions, wait conditions, and expectations in
JSON or via the Python `ExecutionPlan` API. Do not add website branches to
DingDongDitch. Developers may keep small project-specific host scripts outside
this package. See [`examples/plans/README.md`](../../examples/plans/README.md)
and [`examples/host_execution_plan.py`](../../examples/host_execution_plan.py).

## Explicit non-goals (this CLI does not provide)

- built-in / universal / natural-language planning
- autonomous website exploration
- inventing steps, targets, or workflows
- "click every button"
- target healing
- retries / replanning
- arbitrary sleeps
- nested iframe paths / auto frame search
- popup or new-tab handling
- dialog handling
- download handling
- file uploads
- native Safari automation
- universal website compatibility
- a second executor, verifier, or browser backend
- project-specific business logic (Amazon, YouTube, etc.)

## Sample

[`examples/plans/basic_navigation.json`](../../examples/plans/basic_navigation.json)
runs against the local fixture via relative filesystem path resolution.

[`examples/plans/iframe_targeting.json`](../../examples/plans/iframe_targeting.json)
demonstrates declared one-level iframe `frame` targeting.
