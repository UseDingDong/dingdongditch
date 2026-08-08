# Three-layer receipt architecture

Each completed browser operation has one truth boundary, published in three
separate layers. DingDongDitch never treats artifacts as proof by themselves.

## Layer 1 — core receipt

`ExecutionReceipt.to_core_dict()` is a small deterministic outcome record:

- operation identity and action type;
- verdict, execution status, and failure kind;
- target-resolution summary (including frame-path failure hop when relevant);
- aggregate expectation outcome;
- monotonic per-operation timing;
- browser session/context/page identity.

It intentionally excludes DOM text, network records, screenshots, trace data,
and artifact paths. A consumer that only needs control-flow truth should use
this layer.

## Layer 2 — bounded evidence

`ExecutionReceipt.to_bounded_evidence_dict()` contains the compact material
that explains a verdict:

- failed or indeterminate expectation evidence (expected vs. observed, unique
  resolution state, safe attributes, structural fingerprint, and minimal DOM
  shape);
- sanitized bounded evidence signals;
- sanitized action evidence and freshness evaluation.

Evidence is limited by deterministic string, collection, depth, attribute, and
signal-count limits. Sensitive-key values, credentials/token-like values, and
local paths are redacted. It does not include full HTML or unconstrained DOM
subtrees. Runtime may use a transient raw observation to evaluate an expectation,
but only this bounded form is attached to the published receipt.

## Layer 3 — optional artifacts

`ExecutionReceipt.artifacts` contains safe references to heavyweight optional
material. Screenshot capture remains controlled by `ScreenshotConfig`; the
receipt stores a stable artifact ID, status, filename, reason, duration, and
redaction attestation — never image bytes or an absolute local path. Existing
action evidence references artifact IDs rather than embedding screenshot facts.

The architecture is deliberately ready for traces, downloads, HAR, and video
references, but this batch does not enable HAR or video capture. Any new
artifact producer must provide an explicit capture policy and a safe reference;
it must not add heavyweight payloads to core receipts or bounded evidence.

## Serialization

`ExecutionReceipt.to_layered_dict()` is the canonical new-consumer shape:

```text
core_receipt
bounded_evidence
artifacts
```

`to_dict()` retains legacy fields for compatibility, including bounded evidence
fields and the new `artifacts` reference list. New consumers should prefer the
layered representation.
