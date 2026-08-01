# Evidence screenshot implementation report

## Architecture changes

Screenshot capture is an additive observability layer on the existing typed
`ExecutionPlan -> runtime -> Playwright backend -> receipts` path. The runtime
does not interpret images, heal locators, retry operations, or capture
everything implicitly.

`ScreenshotConfig` is available at plan level and operation level. The default
policy is `ON_FAILURE`; an operation configuration overrides the plan default.

## Typed screenshot policy

`ScreenshotPolicy` supports `NEVER`, `ON_FAILURE`, `BEFORE_AND_AFTER`,
`AFTER_SUCCESS`, and `ALWAYS`. Configuration also declares viewport/full-page
mode, per-operation and per-plan limits, portable artifact root, sensitive
selectors, password-redaction preference, and mandatory-redaction intent.

Example:

```python
plan = ExecutionPlan(
    plan_id="evidence-plan",
    screenshot_config=ScreenshotConfig(
        policy=ScreenshotPolicy.ON_FAILURE,
        full_page=False,
        artifact_root="artifacts/evidence_screenshots",
    ),
    operations=[operation],
)
```

## Capture lifecycle and artifacts

After operation dispatch and verification, the runtime evaluates the effective
policy and captures a deterministic PNG named:

`<plan>__<step>__<operation>__<reason>__<page-id>.png`

Paths are stored using portable POSIX separators relative to the configured
artifact root. Each capture records plan/step/operation/page identity, reason,
URL, timestamp, full-page flag, duration, and capture error. Artifacts remain
on disk after browser cleanup; the backend does not delete them during shutdown.

## Redaction and limits

The typed configuration carries password-default and sensitive-selector
redaction declarations, mandatory-redaction intent, and bounded counts. The
current capture path records `redaction_status` explicitly; it reports
`not_applied` when no reliable DOM redaction step is available and `failed` on
capture failure. It does not claim redaction that did not occur. Per-operation
limit enforcement is active; plan-level aggregation and reliable DOM masking
are compatibility follow-ups before treating mandatory redaction as complete.

## Receipt and failure handling

Screenshot records are attached to `action_evidence` under `screenshots`, with
the effective `screenshot_policy`. Capture exceptions are represented as
`captured: false` plus `capture_error`; they never replace the operation's
execution or verification verdict. Existing cleanup/lifecycle receipts remain
authoritative.

## Read-only inspection

The capture records are available through the existing read-only receipt
inspection path; artifact paths are metadata only and are never interpreted by
the runtime.

## Tests

Added focused contract tests covering the default `ON_FAILURE` policy and
portable artifact-root serialization. Focused result: **9 passed** including
the existing plan contract tests.

Two full-suite runs were attempted. Both exceeded the 120-second outer command
limit without a pytest completion summary, matching the repository's existing
suite-run limitation. No full-suite pass is claimed.

## Compatibility concerns

- Existing operation and plan constructors remain source-compatible because
  screenshot configuration is optional.
- Receipt consumers may observe an additional `action_evidence.screenshots`
  field and plan description screenshot metadata.
- Full-page capture and artifact size limits are delegated to Playwright and
  filesystem availability; capture failure is deliberately non-fatal.
- Reliable password/custom-selector masking and plan-wide screenshot counting
  need a subsequent focused implementation before mandatory redaction is
  enabled for sensitive production workflows.

## Recommended next action

Add a backend-owned DOM masking transaction and a plan-scoped screenshot
collector, then isolate the full-suite timeout by test file before claiming
full-suite stability.
