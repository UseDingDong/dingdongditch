# Runtime regression gates

The CI reliability/performance check consumes the JSON produced by
[`runtime_latency_audit/benchmark_runtime.py`](./runtime_latency_audit/benchmark_runtime.py).
It does not replace that benchmark, alter browser execution, or claim a
precise performance measurement on a shared runner.

## CI scenario

CI runs the local deterministic scenario only:

```bash
python Engineering/runtime_latency_audit/benchmark_runtime.py \
  --repetitions 2 --complex-repetitions 0 --output <temporary-result.json>
python Engineering/runtime_latency_audit/check_ci_regression.py \
  --result <temporary-result.json>
```

The benchmark still captures screenshots, receipts, inspection, verification,
and cleanup. It does not visit the optional external complex-app URL in CI.

## Reliability gate

[`ci_regression_baseline.json`](./runtime_latency_audit/ci_regression_baseline.json)
declares seven local activities per repetition. All seven must dispatch
successfully; six are intentionally `VERIFIED` and the download scenario is
not treated as a verification-backed success. The gate also requires zero
atomic-snapshot fallbacks. A changed count or any failed deterministic action
is a regression, not a performance fluctuation.

## Performance gate

The checked metric is the existing `total_operation` median. Its reference is
the recorded local audit median of **270.4465 ms**. CI permits the larger of:

- eight times that reference; or
- **3000 ms**.

The absolute floor intentionally dominates ordinary shared-runner noise; this
is a broad signal for material slowdowns, not a millisecond-level budget. The
result JSON is retained only for the CI job and is not a new performance
baseline artifact.

## Updating a baseline intentionally

Do not update the JSON after an isolated slow run. First reproduce the full
benchmark locally with the normal audit command, explain the change in the
pull request, and preserve deterministic reliability counts unless the
scenario itself was deliberately changed. Then update the reference and this
document in the same reviewed change. A performance relaxation without that
evidence is not an acceptable baseline update.
