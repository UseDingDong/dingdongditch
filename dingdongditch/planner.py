"""Small, stable planner-facing facade over a governed DingDongDitch lease.

The facade is intentionally a projection of :mod:`dingdongditch.mcp`, rather
than another browser/session implementation.  A trusted host creates the
governed session; an unfamiliar planner receives JSON-shaped observations,
operation results, receipts, capabilities, and recovery instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from dingdongditch.contract.operation import Operation
from dingdongditch.machine_contract import ContractValidationError, operation_schema, parse_operation
from dingdongditch.mcp.server import GovernedMCPServer
from dingdongditch.runtime.governed_agent import GovernedAgentSession


PLANNER_INTERFACE_VERSION = "1.0"
"""Version of the compact public planner method and result shapes."""


@dataclass(frozen=True)
class PlannerResponse:
    """One planner-friendly response, including bounded governed errors."""

    ok: bool
    result: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None
    recovery: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            payload["result"] = dict(self.result or {})
        else:
            payload["error"] = dict(self.error or {"code": "internal_error"})
        if self.recovery is not None:
            payload["recovery"] = dict(self.recovery)
        return payload


def _operation(operation_id: str, url: str, action: Mapping[str, Any], *,
               expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000) -> dict[str, Any]:
    """Build the small common envelope without exposing runtime internals."""
    return {
        "operation_id": operation_id,
        "url": url,
        "action": dict(action),
        "expectations": [dict(item) for item in expectations],
        "timeout_ms": timeout_ms,
    }


def navigate_operation(operation_id: str, url: str, *,
                       expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000) -> dict[str, Any]:
    return _operation(operation_id, url, {"type": "navigate"}, expectations=expectations, timeout_ms=timeout_ms)


def click_operation(operation_id: str, url: str, locator: Mapping[str, Any], *,
                    expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000) -> dict[str, Any]:
    return _operation(operation_id, url, {"type": "click", "locator": dict(locator)}, expectations=expectations, timeout_ms=timeout_ms)


def fill_operation(operation_id: str, url: str, locator: Mapping[str, Any], text: str, *,
                   expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000) -> dict[str, Any]:
    return _operation(operation_id, url, {"type": "fill", "locator": dict(locator), "text": text}, expectations=expectations, timeout_ms=timeout_ms)


def press_operation(operation_id: str, url: str, key: str, *, locator: Mapping[str, Any] | None = None,
                    key_scope: str | None = None, expectations: Sequence[Mapping[str, Any]] = (),
                    timeout_ms: int = 10_000) -> dict[str, Any]:
    action: dict[str, Any] = {"type": "press_key", "key": key}
    if locator is not None:
        action["locator"] = dict(locator)
    if key_scope is not None:
        action["key_scope"] = key_scope
    return _operation(operation_id, url, action, expectations=expectations, timeout_ms=timeout_ms)


def scroll_operation(operation_id: str, url: str, locator: Mapping[str, Any], *,
                     expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000) -> dict[str, Any]:
    return _operation(operation_id, url, {"type": "scroll_to_target", "locator": dict(locator)}, expectations=expectations, timeout_ms=timeout_ms)


def select_operation(operation_id: str, url: str, locator: Mapping[str, Any], *,
                     option_value: str | None = None, option_label: str | None = None,
                     expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000) -> dict[str, Any]:
    choices = [option_value is not None, option_label is not None]
    if sum(choices) != 1:
        raise ValueError("select_operation requires exactly one of option_value or option_label")
    action: dict[str, Any] = {"type": "select_option", "locator": dict(locator)}
    action["option_value" if option_value is not None else "option_label"] = option_value or option_label
    return _operation(operation_id, url, action, expectations=expectations, timeout_ms=timeout_ms)


class PlannerAdapter:
    """Four-call planner interface over an existing governed MCP binding.

    This is useful for an in-process host integration.  A cross-process or
    third-party planner should use the identically named ``dingdong.*`` MCP
    tools.  Neither form exposes a browser, stateful-session record, policy,
    control token, or raw backend.
    """

    def __init__(self, transport: GovernedMCPServer) -> None:
        if not isinstance(transport, GovernedMCPServer):
            raise TypeError("PlannerAdapter requires a GovernedMCPServer")
        self._transport = transport

    @classmethod
    def from_governed_session(
        cls,
        session: GovernedAgentSession,
        *,
        authenticated_principal: str | None = None,
        close_on_disconnect: bool = False,
    ) -> "PlannerAdapter":
        """Create the facade from a host-issued governed lease only."""
        if not isinstance(session, GovernedAgentSession):
            raise TypeError("PlannerAdapter requires a GovernedAgentSession")
        return cls(
            GovernedMCPServer.from_governed_session(
                session,
                authenticated_principal=authenticated_principal or session.agent_id,
                close_on_disconnect=close_on_disconnect,
            )
        )

    @staticmethod
    def _operation_payload(operation: Operation | Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(operation, Operation):
            return operation.to_public_dict()
        if isinstance(operation, Mapping):
            # Parse through the canonical schema.  Validation is deliberately
            # lossless here: the accepted mapping, not a hand-built rewrite,
            # is what crosses the transport boundary.
            parse_operation(operation)
            return operation
        raise TypeError("operation must be a canonical Operation mapping")

    def _call(self, tool: str, arguments: Mapping[str, Any]) -> PlannerResponse:
        failed, payload = self._transport.call_tool(tool, dict(arguments))
        recovery = payload.get("recovery") if isinstance(payload.get("recovery"), Mapping) else None
        if failed:
            error = payload.get("error")
            return PlannerResponse(
                ok=False,
                error=(dict(error) if isinstance(error, Mapping) else {"code": "internal_error"}),
                recovery=dict(recovery) if recovery is not None else None,
            )
        return PlannerResponse(ok=True, result=payload, recovery=dict(recovery) if recovery is not None else None)

    def available_actions(self) -> PlannerResponse:
        """Discover canonical action types, schemas, recovery, and primitives."""
        return self._call("dingdong.get_capabilities", {})

    capabilities = available_actions

    def observe(self) -> PlannerResponse:
        """Return a bounded observation and opaque handle for a current page."""
        return self._call("dingdong.observe", {})

    def execute(
        self,
        operation: Operation | Mapping[str, Any],
        *,
        observation_handle: str | None = None,
        element_id: str | None = None,
    ) -> PlannerResponse:
        """Submit one canonical operation through the retained governed runtime."""
        try:
            payload = self._operation_payload(operation)
        except ContractValidationError as exc:
            schema = operation_schema()
            return PlannerResponse(
                ok=False,
                error={
                    "code": "planner_invalid_operation",
                    "message": "planner operation rejected before execution",
                    "details": {
                        "errors": [item.to_dict() for item in exc.errors[:8]],
                        "allowed_shape": {
                            "required": schema.get("required", []),
                            "properties": schema.get("properties", {}),
                        },
                    },
                },
            )
        arguments: dict[str, Any] = {"operation": payload}
        if observation_handle is not None:
            arguments["observation_handle"] = observation_handle
        if element_id is not None:
            arguments["element_id"] = element_id
        return self._call("dingdong.execute", arguments)

    def navigate(self, operation_id: str, url: str, *, expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000) -> PlannerResponse:
        return self.execute(navigate_operation(operation_id, url, expectations=expectations, timeout_ms=timeout_ms))

    def click(self, operation_id: str, url: str, locator: Mapping[str, Any], *, expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000, observation_handle: str | None = None, element_id: str | None = None) -> PlannerResponse:
        return self.execute(click_operation(operation_id, url, locator, expectations=expectations, timeout_ms=timeout_ms), observation_handle=observation_handle, element_id=element_id)

    def fill(self, operation_id: str, url: str, locator: Mapping[str, Any], text: str, *, expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000, observation_handle: str | None = None, element_id: str | None = None) -> PlannerResponse:
        return self.execute(fill_operation(operation_id, url, locator, text, expectations=expectations, timeout_ms=timeout_ms), observation_handle=observation_handle, element_id=element_id)

    def press(self, operation_id: str, url: str, key: str, *, locator: Mapping[str, Any] | None = None, key_scope: str | None = None, expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000, observation_handle: str | None = None, element_id: str | None = None) -> PlannerResponse:
        return self.execute(press_operation(operation_id, url, key, locator=locator, key_scope=key_scope, expectations=expectations, timeout_ms=timeout_ms), observation_handle=observation_handle, element_id=element_id)

    def scroll(self, operation_id: str, url: str, locator: Mapping[str, Any], *, expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000, observation_handle: str | None = None, element_id: str | None = None) -> PlannerResponse:
        return self.execute(scroll_operation(operation_id, url, locator, expectations=expectations, timeout_ms=timeout_ms), observation_handle=observation_handle, element_id=element_id)

    def select(self, operation_id: str, url: str, locator: Mapping[str, Any], *, option_value: str | None = None, option_label: str | None = None, expectations: Sequence[Mapping[str, Any]] = (), timeout_ms: int = 10_000, observation_handle: str | None = None, element_id: str | None = None) -> PlannerResponse:
        return self.execute(select_operation(operation_id, url, locator, option_value=option_value, option_label=option_label, expectations=expectations, timeout_ms=timeout_ms), observation_handle=observation_handle, element_id=element_id)

    def reobserve(
        self,
        *,
        previous_observation_handle: str | None = None,
        previous_element_id: str | None = None,
    ) -> PlannerResponse:
        """Capture current evidence and return explicit target-rebinding guidance."""
        arguments: dict[str, Any] = {}
        if previous_observation_handle is not None:
            arguments["previous_observation_handle"] = previous_observation_handle
        if previous_element_id is not None:
            arguments["previous_element_id"] = previous_element_id
        return self._call("dingdong.reobserve", arguments)


__all__ = [
    "PLANNER_INTERFACE_VERSION", "PlannerAdapter", "PlannerResponse",
    "navigate_operation", "click_operation", "fill_operation", "press_operation",
    "scroll_operation", "select_operation",
]
