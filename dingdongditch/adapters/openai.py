"""OpenAI-style function-tool projection; no OpenAI SDK is required."""

from __future__ import annotations

from typing import Any

from dingdongditch.machine_contract import execution_plan_tool as _generic_tool


def execution_plan_tool(*, strict: bool = False) -> dict[str, Any]:
    """Return an OpenAI function-tool object.

    OpenAI strict mode supports a documented subset of JSON Schema and is not
    a lossless representation of this discriminated contract. Passing
    ``strict=True`` therefore fails explicitly instead of silently changing
    the grammar. The lossless default preserves the canonical Draft 2020-12
    schema; hosts must always parse with ``parse_plan_document`` before
    execution.
    """
    if strict:
        raise ValueError(
            "OpenAI strict mode is not a lossless projection of the canonical "
            "DingDongDitch schema; use strict=False and parse_plan_document(), "
            "or compile a host-owned narrowed schema."
        )
    tool = _generic_tool()
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
            "strict": strict,
        },
    }
