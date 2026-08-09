"""External-developer smoke test using only public machine-contract APIs."""

from __future__ import annotations

from jsonschema import Draft202012Validator

import dingdongditch as dingdong


def _valid(schema: dict, value: object) -> None:
    errors = list(Draft202012Validator(schema).iter_errors(value))
    assert not errors, errors[0].message


def test_external_planner_machine_contract_smoke(fixture_url):
    # A new host needs only the public package API: get a tool/schema, produce
    # JSON, parse it, execute it, and validate the public receipt.
    tool = dingdong.execution_plan_tool()
    assert tool["input_schema"] == dingdong.execution_schema()
    payload = {
        "schema_version": dingdong.MACHINE_CONTRACT_VERSION,
        "browser": {"engine": "chromium", "channel": "bundled", "headless": True},
        "plan": {
            "plan_id": "external-developer-smoke",
            "operations": [
                {
                    "operation_id": "navigate",
                    "url": f"{fixture_url}/index.html",
                    "action": {"type": "navigate"},
                    "expectations": [
                        {
                            "type": "url",
                            "url_value": "index.html",
                            "url_match": "contains",
                        }
                    ],
                }
            ],
        },
    }
    _valid(dingdong.execution_schema(), payload)
    document = dingdong.parse_plan_document(payload)
    receipt = dingdong.execute_plan(document.plan)
    serialized = receipt.to_dict()
    _valid(dingdong.plan_receipt_schema(), serialized)
    assert dingdong.parse_plan_receipt(serialized).plan_id == document.plan.plan_id
    assert isinstance(dingdong.parse_receipt(serialized), dingdong.PlanReceipt)


def test_real_public_observation_and_execution_receipt_validate(fixture_url):
    runtime = dingdong.StatefulSessionRuntime()
    session = runtime.open_session(dingdong.BrowserConfig(headless=True))
    try:
        operation = dingdong.parse_operation(
            {
                "operation_id": "navigate-observe",
                "url": f"{fixture_url}/index.html",
                "action": {"type": "navigate"},
                "expectations": [],
            }
        )
        result = runtime.execute_operation(session.session_id, operation)
        _valid(dingdong.execution_receipt_schema(), result.receipt.to_dict())
        assert dingdong.parse_execution_receipt(result.receipt.to_dict()).operation_id == operation.operation_id
        assert isinstance(dingdong.parse_receipt(result.receipt.to_dict()), dingdong.ExecutionReceipt)
        observation = runtime.observe_page(session.session_id)
        _valid(dingdong.observation_schema(), observation.observation.to_dict())
    finally:
        runtime.close_session(session.session_id)
