"""Optional MCP transport adapter for governed DingDongDitch sessions.

Importing this package does not import the optional ``mcp`` dependency.  A
trusted host creates the governed session first, then binds it to an
authenticated stdio principal through :class:`GovernedMCPServer`.
"""

from .server import (
    MCP_PROTOCOL_REVISION,
    MCP_SDK_REQUIREMENT,
    MCPDependencyError,
    MCPHostBinding,
    GovernedMCPServer,
)

__all__ = [
    "MCP_PROTOCOL_REVISION",
    "MCP_SDK_REQUIREMENT",
    "MCPDependencyError",
    "MCPHostBinding",
    "GovernedMCPServer",
]
