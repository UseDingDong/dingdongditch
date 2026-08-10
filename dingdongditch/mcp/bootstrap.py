"""Trusted-host bootstrap loading for the stdio MCP command.

The bootstrap reference belongs to the process launcher, not an MCP client or
tool call.  It deliberately accepts a Python module factory rather than a
planner-provided policy document: opening a browser session and installing
authority are host trust decisions.
"""

from __future__ import annotations

import importlib
import re
from typing import Any

from dingdongditch.runtime.governed_agent import GovernedAgentSession


class MCPBootstrapError(ValueError):
    """Bounded host-startup error for an invalid bootstrap reference."""


_REFERENCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")


def load_governed_session(reference: str, *, authenticated_principal: str) -> GovernedAgentSession:
    """Load ``module:factory`` and obtain a host-created governed session.

    The factory receives the transport-authenticated principal and must return
    a ``GovernedAgentSession`` whose ``agent_id`` is exactly that value.  It
    may use any host-owned policy, browser, identity, signed-plan, secret, or
    attestation configuration before returning; none crosses the MCP boundary.
    """
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise MCPBootstrapError("bootstrap must use module:factory syntax")
    module_name, attribute = reference.split(":", 1)
    try:
        module = importlib.import_module(module_name)
        factory: Any = getattr(module, attribute)
    except Exception as exc:
        raise MCPBootstrapError("trusted MCP bootstrap could not be loaded") from exc
    if not callable(factory):
        raise MCPBootstrapError("trusted MCP bootstrap factory is not callable")
    try:
        session = factory(authenticated_principal)
    except Exception as exc:
        raise MCPBootstrapError("trusted MCP bootstrap could not open a governed session") from exc
    if not isinstance(session, GovernedAgentSession):
        raise MCPBootstrapError("trusted MCP bootstrap must return a GovernedAgentSession")
    if session.agent_id != authenticated_principal:
        try:
            session.close()
        except Exception:
            pass
        raise MCPBootstrapError("trusted MCP bootstrap lease owner does not match authenticated principal")
    return session


__all__ = ["MCPBootstrapError", "load_governed_session"]
