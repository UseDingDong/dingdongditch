"""Anthropic tool-use projection; no Anthropic SDK is required."""

from __future__ import annotations

from typing import Any

from dingdongditch.machine_contract import execution_plan_tool as _generic_tool


def execution_plan_tool() -> dict[str, Any]:
    """Return an Anthropic-compatible client tool declaration."""
    return _generic_tool()
