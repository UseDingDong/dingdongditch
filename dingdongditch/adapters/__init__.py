"""Optional, dependency-free projections of the canonical machine contract.

Adapters only reshape :func:`dingdongditch.execution_plan_tool` for vendor
request envelopes. They do not call models or execute browser operations.
"""

from dingdongditch.adapters import anthropic, gemini, openai

__all__ = ["anthropic", "gemini", "openai"]
