# JSON Execution Plans

DingDongDitch is execution infrastructure. The **host** (developer code,
Cursor, CI, a test framework, or another app) authors the typed plan.
Website-specific behavior belongs in your JSON or host script — not inside
DingDongDitch.

The CLI only loads and executes already-authored plans:

```bash
python -m dingdongditch run-plan path/to/plan.json
python -m dingdongditch run-plan -
```

## Run the bundled sample

The sample targets the repository's local deterministic fixture via a relative
filesystem path (resolved to a `file://` URL against this plan file):

```bash
python -m dingdongditch run-plan examples/plans/basic_navigation.json
python -m dingdongditch run-plan examples/plans/iframe_targeting.json
python -m dingdongditch run-plan - < examples/plans/basic_navigation.json
python -m dingdongditch run-plan examples/plans/basic_navigation.json --engine firefox
python -m dingdongditch run-plan examples/plans/basic_navigation.json --engine webkit --headed
python -m dingdongditch run-plan examples/plans/basic_navigation.json --output artifacts/receipt.json
```

## Author another plan

1. Copy `basic_navigation.json` (or `iframe_targeting.json` for frame-scoped steps).
2. Set `plan.plan_id`.
3. Set each operation's `url` to an absolute `http(s)://` URL or a relative
   filesystem path (resolved against the plan file directory).
4. Declare explicit `action`, `locator` / optional `frame` or `frame_path` /
   wait targets, and
   `expectations`.
5. Run with `python -m dingdongditch run-plan path/to/your_plan.json`.

Or construct an `ExecutionPlan` in Python and call `execute_plan` — see
[`../host_execution_plan.py`](../host_execution_plan.py). That pattern is
project host code, not a built-in planner.

The runner does not guess targets, invent actions, heal locators, retry steps,
or interpret natural language. Invalid enums, unknown fields, and unsupported
browser combinations fail before browser launch.

See [`Engineering/Phase 3/PLAN_RUNNER_CLI.md`](../../Engineering/Phase%203/PLAN_RUNNER_CLI.md)
and [`Engineering/Phase 3/IFRAME_TARGETING.md`](../../Engineering/Phase%203/IFRAME_TARGETING.md).
