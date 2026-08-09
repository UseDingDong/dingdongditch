# Agent integration guide

## The compatibility promise

DingDongDitch is the deterministic execution boundary below a planner. It
does not know, call, configure, or reason like a model. A host decides how to
plan; DingDongDitch accepts a fail-closed, versioned `PlanDocument`, executes
only its declared operations, and returns structured receipts.

```text
planner/model
      ↓
canonical DingDongDitch JSON Schema
      ↓
PlanDocument → parse/validate → execute
      ↓
structured receipt
```

The generic JSON Schema path is the primary compatibility mechanism. It works
for a future model, private/internal company model, fine-tuned model, local or
open-source model, research agent, personal project, or deterministic non-LLM
planner just as it does for a hosted LLM. Compatibility means that a host can
target DingDongDitch's execution interface; it does not guarantee that a
planner is capable of generating reliable plans.

## Vendor-neutral integration

No model SDK is required. The public API returns ordinary Python dictionaries
and accepts ordinary JSON-compatible payloads:

```python
import dingdongditch as dingdong

schema = dingdong.execution_schema()
tool = dingdong.execution_plan_tool()

# The external system is wholly host-owned. It can be an LLM, rules engine,
# test generator, internal service, or any program that emits the schema.
raw_document = my_agent_or_planner(schema=schema, tool=tool)

document = dingdong.parse_plan_document(raw_document)
receipt = dingdong.execute_plan(document.plan)

# A host can validate/decode the structured result without inspecting keys.
plan_receipt = dingdong.parse_plan_receipt(receipt.to_dict())
```

When the host only needs an `ExecutionPlan`, use the equally public shortcut:

```python
plan = dingdong.parse_execution_plan(raw_document)
receipt = dingdong.execute_plan(plan)
```

For generated files and external tooling:

```bash
dingdongditch schema list
dingdongditch schema plan-document > dingdong-plan-document.schema.json
dingdongditch schema execution-receipt --output execution-receipt.schema.json
```

The canonical root is `PlanDocument` contract version `1.0.0`. See
[PUBLIC_MACHINE_CONTRACT.md](./PUBLIC_MACHINE_CONTRACT.md) for the complete
schema/versioning policy, runtime validation boundary, receipt schemas, and
observation schema.

## Public integration surfaces

| Need | Public API |
| --- | --- |
| Canonical input schema | `dingdong.execution_schema()` / `plan_document_schema()` |
| Other schemas | `execution_plan_schema()`, `operation_schema()`, `observation_schema()`, `execution_receipt_schema()`, `plan_receipt_schema()` |
| Installed JSON resource | `published_schema_resource(name)` |
| Generic tool declaration | `execution_plan_tool()` |
| Canonical parser | `parse_plan_document()` |
| Plan parser, including legacy compatibility | `parse_execution_plan()` |
| One operation parser | `parse_operation()` |
| Receipt decoding | `parse_execution_receipt()`, `parse_plan_receipt()`, `parse_receipt()` |
| Safe static errors | `ContractValidationError` with `ValidationIssue` values and `to_dict()` |

All emitted plans must still be parsed before execution. JSON Schema constrains
the declared grammar; live browser facts such as target uniqueness, frame
existence, page freshness, filesystem authorization, and actual expectation
results are runtime validation boundaries.

## Optional vendor envelopes

These helpers are data-only projections of the canonical schema. They do not
install a model SDK, call a model, store keys, own prompts, or run browser
execution.

### OpenAI / GPT / Codex

```python
from dingdongditch.adapters import openai

tool = openai.execution_plan_tool()
```

This is an OpenAI-style function-tool envelope with the canonical schema as
`parameters`. It deliberately defaults to lossless non-strict tool calling.
OpenAI strict mode is not a lossless projection of this discriminated contract
and is rejected rather than silently changing plan semantics.

### Anthropic Claude / Claude Code

```python
from dingdongditch.adapters import anthropic

tool = anthropic.execution_plan_tool()
```

The result is the standard `name` / `description` / `input_schema` shape.

### Google Gemini

```python
from dingdongditch.adapters import gemini

tool = gemini.execution_plan_tool()  # parametersJsonSchema
# or gemini.execution_plan_tool(api_style="python")
```

The helper changes only envelope field spelling. The canonical schema remains
authoritative.

## All other planners and model categories

There is intentionally no branded adapter when it would only duplicate the
generic path. For each of the following, obtain `execution_schema()` and/or
`execution_plan_tool()`, have the host emit the canonical `PlanDocument`, then
call `parse_plan_document()` before `execute_plan()`:

- xAI Grok and DeepSeek;
- Meta Llama, Qwen, and Mistral;
- Ollama and other locally hosted/open-source models;
- OpenAI-compatible API servers;
- generic tool-calling agents and generic structured-output agents;
- custom/private company models and fine-tuned models;
- experimental or local agents with no vendor SDK; and
- deterministic non-LLM planners, rules engines, CI generators, and tests.

Do not create a second, vendor-specific DingDongDitch grammar. If an external
provider supports only a JSON Schema subset, the host may narrow or compile a
provider request schema, but it must preserve the canonical runtime semantics
and pass the resulting JSON through `parse_plan_document()`.

## Receipt and observation consumption

`ExecutionReceipt.to_dict()` validates against the public ExecutionReceipt
schema (1.8.0). `execute_plan()` returns a `PlanReceipt` whose `to_dict()`
validates against the public PlanReceipt schema (2.2.0). `PageObservation`
serialization validates against `observation_schema()`.

Use `parse_receipt()` when receiving serialized output of an unknown receipt
kind. This keeps receipt selection, version validation, and typed decoding out
of host key-inspection code.

## Security and ownership

The host owns model reasoning, consent, retries, recovery strategy, and model
credentials. DingDongDitch owns only deterministic plan validation, browser
execution, verification, observations, and receipts. It never executes
unvalidated model output and does not add API-key storage, autonomous planning,
or vendor-specific runtime behavior.
