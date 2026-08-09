"""No-key examples for connecting an external planner to DingDongDitch.

The dictionaries returned here are what a host supplies to its own model SDK.
This module intentionally never imports a model client or performs a network
call. Run it to inspect the generic and vendor-shaped tool declarations.
"""

from __future__ import annotations

import json

import dingdongditch as dingdong
from dingdongditch.adapters import anthropic, gemini, openai


def mock_model_arguments() -> dict[str, object]:
    """A deterministic stand-in for arguments emitted by an external model."""
    return {
        "schema_version": dingdong.MACHINE_CONTRACT_VERSION,
        "browser": {"engine": "chromium", "channel": "bundled", "headless": True},
        "plan": {
            "plan_id": "external-agent-example",
            "operations": [
                {
                    "operation_id": "navigate",
                    "url": "https://example.com",
                    "action": {"type": "navigate"},
                    "expectations": [
                        {"type": "url", "url_value": "https://example.com/"}
                    ],
                }
            ],
        },
    }


def generic_planner_example() -> dingdong.PlanDocument:
    schema = dingdong.execution_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    # model_output = host_model_client(..., tools=[dingdong.execution_plan_tool()])
    document = dingdong.parse_plan_document(mock_model_arguments())
    # receipt = dingdong.execute_plan(document.plan)  # host chooses when to run
    return document


def tool_projection_examples() -> dict[str, object]:
    return {
        "generic": dingdong.execution_plan_tool(),
        "openai": openai.execution_plan_tool(),
        "anthropic": anthropic.execution_plan_tool(),
        "gemini": gemini.execution_plan_tool(),
    }


if __name__ == "__main__":
    document = generic_planner_example()
    print(json.dumps(document.to_dict(), indent=2, sort_keys=True))
    print(json.dumps(tool_projection_examples(), indent=2, sort_keys=True))
