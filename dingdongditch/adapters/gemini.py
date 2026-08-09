"""Gemini function-declaration projection; no Google SDK is required."""

from __future__ import annotations

from typing import Any, Literal

from dingdongditch.machine_contract import execution_plan_tool as _generic_tool


def execution_plan_tool(
    *, api_style: Literal["json", "python"] = "json"
) -> dict[str, Any]:
    """Return a Gemini FunctionDeclaration using lossless JSON Schema.

    ``json`` emits the REST spelling ``parametersJsonSchema``. ``python``
    emits ``parameters_json_schema`` for SDKs that use snake_case. Gemini
    endpoints may support only a schema subset; this adapter never silently
    weakens the canonical contract to fit one endpoint.
    """
    tool = _generic_tool()
    field = "parametersJsonSchema" if api_style == "json" else "parameters_json_schema"
    return {
        "name": tool["name"],
        "description": tool["description"],
        field: tool["input_schema"],
    }
