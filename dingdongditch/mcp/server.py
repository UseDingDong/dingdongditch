"""Standards-compliant, stdio-only MCP adapter for governed sessions.

This module is deliberately transport glue.  It never invokes the legacy raw
execution helpers and never contains browser dispatch, policy, quorum,
transaction, handoff, signing, identity, attestation, or speculation logic.
Those decisions remain in :class:`GovernedAgentService` and its retained
``StatefulSessionRuntime``.

The initial adapter targets MCP protocol ``2026-07-28`` through the official
Python SDK.  It supports only stdio because process ownership is the smallest
practical authenticated transport for a first release.  A trusted host passes
the principal at process launch; it is never a tool argument.
"""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hmac
from importlib.metadata import PackageNotFoundError, version as distribution_version
import json
import secrets
import threading
import time
from typing import Any, Callable, Mapping

from dingdongditch.contract.authority import canonical_json_bytes
from dingdongditch.contract.speculation import BranchPreparation, BranchSelection, SpeculationExecutionResult
from dingdongditch.contract.transaction import CommitResult, PreparedOperation
from dingdongditch.machine_contract import (
    ContractValidationError,
    execution_schema,
    operation_schema,
    parse_operation,
    parse_speculative_plan,
    speculative_plan_schema,
)
from dingdongditch.runtime.governed_agent import GovernedAgentService, GovernedAgentSession
from dingdongditch.runtime.stateful_session import SessionObservation, SessionOperationResult, StatefulSessionError
from dingdongditch.contract.transaction import TwoPhaseCommitError


MCP_PROTOCOL_REVISION = "2026-07-28"
"""Exact MCP protocol revision implemented and tested by this adapter."""

MCP_SDK_REQUIREMENT = "mcp==2.0.0"
"""Exact official Python SDK dependency and tested implementation version."""
_MCP_SDK_VERSION = "2.0.0"

MAX_MCP_ARGUMENT_BYTES = 1_000_000
MAX_MCP_RESULT_BYTES = 2_500_000
MAX_MCP_HANDLES = 128
MAX_MCP_CONSUMED_HANDLE_TOMBSTONES = 128
MAX_MCP_JSON_DEPTH = 64
MAX_MCP_JSON_NODES = 10_000
MCP_HANDLE_TTL_MS = 120_000
MCP_PREPARE_TTL_MS = 30_000
MCP_SPECULATION_TTL_MS = 30_000
_HANDLE_PREFIX = "ddd_mcp_"
_HANDLE_KINDS = frozenset({"observation", "prepared", "speculation"})


class MCPDependencyError(RuntimeError):
    """Raised only when a caller selects the optional MCP integration without its extra."""


class _MCPAdapterError(RuntimeError):
    def __init__(self, code: str, message: str = "governed MCP request rejected") -> None:
        self.code = code
        super().__init__(message)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _require_mcp_sdk() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    """Import the optional official SDK only at MCP-server construction time."""
    try:
        from mcp.server.lowlevel.server import Server
        from mcp.server.stdio import stdio_server
        from mcp_types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations
        from mcp_types.version import MODERN_PROTOCOL_VERSIONS
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised from an installed base package
        raise MCPDependencyError(
            "MCP support is optional; install DingDongDitch with the 'mcp' extra "
            f"({MCP_SDK_REQUIREMENT})"
        ) from exc
    try:
        installed_version = distribution_version("mcp")
    except PackageNotFoundError as exc:  # pragma: no cover - import metadata broken/mocked
        raise MCPDependencyError(
            "installed MCP SDK distribution metadata is unavailable; install DingDongDitch with "
            f"the 'mcp' extra ({MCP_SDK_REQUIREMENT})"
        ) from exc
    if installed_version != _MCP_SDK_VERSION:
        raise MCPDependencyError(
            f"installed MCP SDK version is not the supported pinned version {_MCP_SDK_VERSION}"
        )
    if MCP_PROTOCOL_REVISION not in MODERN_PROTOCOL_VERSIONS:
        raise MCPDependencyError(
            f"installed MCP SDK does not support protocol {MCP_PROTOCOL_REVISION}"
        )
    return Server, stdio_server, CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations


@dataclass(frozen=True)
class MCPHostBinding:
    """Trusted-host binding of one governed lease to one stdio principal.

    ``authenticated_principal`` comes from the trusted process launcher, not
    from MCP JSON-RPC.  The server refuses a mismatch with the governed lease
    owner before it starts accepting planner calls.
    """

    session: GovernedAgentSession
    authenticated_principal: str
    close_on_disconnect: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.session, GovernedAgentSession):
            raise TypeError("MCP host binding requires a GovernedAgentSession")
        principal = self.authenticated_principal
        if (
            not isinstance(principal, str)
            or not principal
            or len(principal) > 128
            or any(character.isspace() for character in principal)
        ):
            raise ValueError("authenticated MCP principal must be a non-empty token up to 128 characters")
        if principal != self.session.agent_id:
            raise ValueError("authenticated MCP principal must match the governed lease owner")
        if not isinstance(self.close_on_disconnect, bool):
            raise ValueError("close_on_disconnect must be boolean")


@dataclass
class _OpaqueHandle:
    kind: str
    principal: str
    session_id: str
    control_epoch: int | None
    expires_at_ms: int
    value: Any
    consumed: bool = False


def _copy_definition(schema: Mapping[str, Any], definition: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Embed one generated DingDongDitch definition without inventing its grammar."""
    defs = schema.get("$defs")
    if not isinstance(defs, Mapping) or definition not in defs:
        raise RuntimeError("canonical machine schema does not contain the requested definition")
    root_schema = schema.get("$schema")
    if not isinstance(root_schema, str):
        raise RuntimeError("canonical machine schema is malformed")
    return {"$schema": root_schema, "$defs": deepcopy(dict(defs))}, {"$ref": f"#/$defs/{definition}"}


def _wrapper_schema(
    properties: Mapping[str, Any],
    *,
    required: tuple[str, ...] = (),
    source_schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": deepcopy(dict(properties)),
        "additionalProperties": False,
    }
    if required:
        result["required"] = list(required)
    if source_schema is not None:
        prefix, _ = _copy_definition(source_schema, "Operation")
        result = {**prefix, **result}
    return result


def _operation_input_schema(*, include_observation: bool) -> dict[str, Any]:
    canonical = operation_schema()
    prefix, operation = _copy_definition(canonical, "Operation")
    properties: dict[str, Any] = {"operation": operation}
    if include_observation:
        properties.update(
            {
                "observation_handle": {
                    "type": "string", "minLength": 16, "maxLength": 128,
                    "pattern": "^ddd_mcp_observation_[A-Za-z0-9_-]+$",
                },
                "element_id": {"type": "string", "minLength": 1, "maxLength": 256},
            }
        )
    return {
        **prefix,
        "type": "object",
        "properties": properties,
        "required": ["operation"],
        "additionalProperties": False,
    }


def _speculation_input_schema() -> dict[str, Any]:
    canonical = speculative_plan_schema()
    prefix, plan = _copy_definition(canonical, "SpeculativePlan")
    return {
        **prefix,
        "type": "object",
        "properties": {"speculative_plan": plan},
        "required": ["speculative_plan"],
        "additionalProperties": False,
    }


def _handle_input_schema(kind: str) -> dict[str, Any]:
    if kind not in _HANDLE_KINDS:
        raise ValueError("unknown MCP handle kind")
    name = f"{kind}_handle"
    return _wrapper_schema(
        {
            name: {
                "type": "string", "minLength": 16, "maxLength": 128,
                "pattern": rf"^ddd_mcp_{kind}_[A-Za-z0-9_-]+$",
            }
        },
        required=(name,),
    )


def _empty_input_schema() -> dict[str, Any]:
    return _wrapper_schema({})


class GovernedMCPServer:
    """Thin MCP-to-:class:`GovernedAgentService` adapter for one host lease.

    A server has exactly one authenticated stdio principal and one governed
    session.  It intentionally has no planner-facing tool to create sessions,
    install authority, configure trust, change identities, retain checkpoints,
    report human activity, request attestations, or transfer handoff tokens.
    """

    def __init__(
        self,
        binding: MCPHostBinding,
        *,
        execution_executor: ThreadPoolExecutor | None = None,
    ) -> None:
        if not isinstance(binding, MCPHostBinding):
            raise TypeError("binding must be an MCPHostBinding")
        self._binding = binding
        # Construction is trusted-host work.  Planner calls below go solely
        # through this service and never invoke the runtime directly.
        self._service = GovernedAgentService(binding.session._runtime)
        self._handles: dict[str, _OpaqueHandle] = {}
        self._consumed_handle_tombstones: dict[str, int] = {}
        self._handles_lock = threading.RLock()
        self._handle_reservations = 0
        self._handle_generation = 0
        self._lifecycle_lock = threading.RLock()
        # A stdio bootstrap creates the synchronous browser runtime in this
        # one thread and every governed call returns to it.  Playwright's sync
        # API is thread-affine and cannot run in MCP's async event loop.
        self._execution_executor = execution_executor
        self._closed = False

    @classmethod
    def from_governed_session(
        cls,
        session: GovernedAgentSession,
        *,
        authenticated_principal: str,
        close_on_disconnect: bool = True,
    ) -> "GovernedMCPServer":
        """Create a server from a host-created governed session.

        The host must have installed all authority, identity, signed-plan, and
        browser lifecycle state before calling this method.
        """
        return cls(
            MCPHostBinding(
                session=session,
                authenticated_principal=authenticated_principal,
                close_on_disconnect=close_on_disconnect,
            )
        )

    @classmethod
    def from_host_factory(
        cls,
        factory: Callable[[str], GovernedAgentSession],
        *,
        authenticated_principal: str,
        close_on_disconnect: bool = True,
    ) -> "GovernedMCPServer":
        """Create a stdio server with browser work pinned to one thread.

        ``factory`` is trusted host configuration, not planner code.  It is
        deliberately evaluated on the dedicated execution thread so a
        synchronous Playwright backend and every subsequent service call have
        the same thread affinity.  The MCP protocol loop itself never owns a
        browser handle.
        """
        if not callable(factory):
            raise TypeError("trusted MCP host factory must be callable")
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dingdong-mcp-governed")
        session: GovernedAgentSession | None = None
        try:
            session = executor.submit(factory, authenticated_principal).result()
            binding = MCPHostBinding(
                session=session,
                authenticated_principal=authenticated_principal,
                close_on_disconnect=close_on_disconnect,
            )
            return cls(binding, execution_executor=executor)
        except Exception:
            # A bootstrap may have successfully opened a browser and then
            # failed the principal/type binding. Close that retained resource
            # on its owning thread before releasing the executor.
            if isinstance(session, GovernedAgentSession):
                try:
                    executor.submit(session.close).result()
                except Exception:
                    pass
            executor.shutdown(wait=True, cancel_futures=True)
            raise

    @property
    def authenticated_principal(self) -> str:
        return self._binding.authenticated_principal

    @property
    def protocol_revision(self) -> str:
        return MCP_PROTOCOL_REVISION

    def _service_kwargs(self) -> dict[str, str]:
        session = self._binding.session
        return {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "control_token": session._control_token,
            "authenticated_agent_id": self._binding.authenticated_principal,
        }

    def _current_control_epoch(self) -> int:
        return self._service.control_epoch(**self._service_kwargs())

    @staticmethod
    def _require_arguments(value: Any, *, allowed: frozenset[str], required: frozenset[str]) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise _MCPAdapterError("invalid_arguments")
        # Bound structure before canonicalization or a contract parser can
        # recurse. Repeated container identities cannot occur in JSON, so
        # reject them too on the host-side direct-call API rather than letting
        # a cyclic Python object consume unbounded work.
        stack: list[tuple[Any, int]] = [(value, 1)]
        seen_containers: set[int] = set()
        node_count = 0
        while stack:
            current, depth = stack.pop()
            node_count += 1
            if node_count > MAX_MCP_JSON_NODES or depth > MAX_MCP_JSON_DEPTH:
                raise _MCPAdapterError("request_too_complex")
            if isinstance(current, Mapping):
                identity = id(current)
                if identity in seen_containers:
                    raise _MCPAdapterError("request_too_complex")
                seen_containers.add(identity)
                for key, child in current.items():
                    if not isinstance(key, str):
                        raise _MCPAdapterError("invalid_arguments")
                    stack.append((child, depth + 1))
            elif isinstance(current, list):
                identity = id(current)
                if identity in seen_containers:
                    raise _MCPAdapterError("request_too_complex")
                seen_containers.add(identity)
                stack.extend((child, depth + 1) for child in current)
        try:
            size = len(canonical_json_bytes(dict(value)))
        except (TypeError, ValueError):
            raise _MCPAdapterError("invalid_arguments") from None
        if size > MAX_MCP_ARGUMENT_BYTES:
            raise _MCPAdapterError("request_too_large")
        keys = set(value)
        if any(not isinstance(key, str) for key in keys) or keys - allowed or required - keys:
            raise _MCPAdapterError("invalid_arguments")
        return value

    def _cleanup_handles(self) -> None:
        now = _now_ms()
        expired = [token for token, item in self._handles.items() if item.expires_at_ms <= now]
        for token in expired:
            del self._handles[token]
        expired_tombstones = [token for token, expiry in self._consumed_handle_tombstones.items() if expiry <= now]
        for token in expired_tombstones:
            del self._consumed_handle_tombstones[token]

    def _clear_handles(self) -> None:
        """Drop all connection-scoped capabilities without touching the session."""
        with self._handles_lock:
            self._handles.clear()
            self._consumed_handle_tombstones.clear()
            self._handle_reservations = 0
            self._handle_generation += 1

    def _reserve_handle_slot(self) -> int:
        """Reserve bounded handle capacity before any browser/service work."""
        with self._handles_lock:
            self._cleanup_handles()
            if len(self._handles) + self._handle_reservations >= MAX_MCP_HANDLES:
                raise _MCPAdapterError("handle_capacity")
            self._handle_reservations += 1
            return self._handle_generation

    def _release_handle_slot(self, generation: int) -> None:
        with self._handles_lock:
            if generation == self._handle_generation and self._handle_reservations > 0:
                self._handle_reservations -= 1

    def _mint_handle(
        self,
        kind: str,
        value: Any,
        *,
        expires_at_ms: int | None = None,
        control_epoch: int | None = None,
        reservation_generation: int | None = None,
    ) -> str:
        if kind not in _HANDLE_KINDS:
            raise RuntimeError("unsupported MCP handle kind")
        with self._handles_lock:
            self._cleanup_handles()
            if reservation_generation is not None and reservation_generation != self._handle_generation:
                raise _MCPAdapterError("connection_closed")
            if reservation_generation is None and len(self._handles) + self._handle_reservations >= MAX_MCP_HANDLES:
                raise _MCPAdapterError("handle_capacity")
            if control_epoch is None:
                control_epoch = self._current_control_epoch()
            effective_expiry = expires_at_ms if expires_at_ms is not None else _now_ms() + MCP_HANDLE_TTL_MS
            if isinstance(effective_expiry, bool) or not isinstance(effective_expiry, int) or effective_expiry <= _now_ms():
                raise _MCPAdapterError("invalid_handle_lifetime")
            token = f"{_HANDLE_PREFIX}{kind}_{secrets.token_urlsafe(32)}"
            self._handles[token] = _OpaqueHandle(
                kind=kind,
                principal=self._binding.authenticated_principal,
                session_id=self._binding.session.session_id,
                control_epoch=control_epoch,
                expires_at_ms=effective_expiry,
                value=value,
            )
            return token

    def _take_handle(self, token: Any, *, kind: str, consume: bool = False) -> _OpaqueHandle:
        if not isinstance(token, str) or len(token) > 128 or not token.startswith(f"{_HANDLE_PREFIX}{kind}_"):
            raise _MCPAdapterError("invalid_handle")
        with self._handles_lock:
            self._cleanup_handles()
            item = self._handles.get(token)
            # The comparison is intentionally performed even though one
            # stdio server has one principal.  It keeps the helper safe if a
            # host later multiplexes bindings and makes handles useless across
            # principals by construction.
            if item is None or item.kind != kind:
                if token in self._consumed_handle_tombstones:
                    raise _MCPAdapterError("handle_already_used")
                raise _MCPAdapterError("invalid_handle")
            if (
                not hmac.compare_digest(item.principal, self._binding.authenticated_principal)
                or not hmac.compare_digest(item.session_id, self._binding.session.session_id)
            ):
                raise _MCPAdapterError("invalid_handle")
            if item.consumed:
                raise _MCPAdapterError("handle_already_used")
            if item.control_epoch is not None and item.control_epoch != self._current_control_epoch():
                raise _MCPAdapterError("stale_handle")
            if consume:
                item.consumed = True
                # A consumed adapter capability can never be valid again.
                # Remove it immediately so repeated prepare/commit cycles
                # cannot fill the bounded live-handle table until expiry.
                del self._handles[token]
                self._consumed_handle_tombstones[token] = item.expires_at_ms
                while len(self._consumed_handle_tombstones) > MAX_MCP_CONSUMED_HANDLE_TOMBSTONES:
                    del self._consumed_handle_tombstones[next(iter(self._consumed_handle_tombstones))]
            return item

    @staticmethod
    def _prepared_public(prepared: PreparedOperation, handle: str) -> dict[str, Any]:
        return {
            "prepared_handle": handle,
            "expires_at_ms": prepared.expires_at_ms,
            "status": prepared.status.value,
            "action_type": prepared.action_type,
            "origin": prepared.origin,
            "page_id": prepared.page_id,
            "state_fingerprint": prepared.state_fingerprint,
            "target_fingerprint": prepared.target_fingerprint,
            "operation_hash": prepared.operation_hash,
            "authority_policy_hash": prepared.authority_policy_hash,
            "authority_decision": prepared.authority_decision,
            "mutation_epoch": prepared.mutation_epoch,
            "arbitration_policy": prepared.arbitration_policy,
        }

    @staticmethod
    def _speculation_public(prepared: BranchPreparation, handle: str) -> dict[str, Any]:
        return {
            "speculation_handle": handle,
            "speculation_id": prepared.speculation_id,
            "parent_operation_id": prepared.parent_operation_id,
            "control_epoch": prepared.control_epoch,
            "mutation_epoch": prepared.mutation_epoch,
            "expires_at_ms": prepared.expires_at_ms,
            "branch_count": prepared.branch_count,
        }

    @staticmethod
    def _selection_public(selection: BranchSelection) -> dict[str, Any]:
        return {
            "status": selection.status.value,
            "branch_id": selection.branch_id,
            "evidence": [dict(item) for item in selection.evidence],
        }

    @staticmethod
    def _operation_public(result: SessionOperationResult) -> dict[str, Any]:
        data = result.to_dict()
        # Strictly project the documented SessionOperationResult response.
        # Treat a future/provider-specific extra field as private by default;
        # in particular it must not turn a control, handoff, filesystem, or
        # browser implementation detail into a planner-visible capability.
        public_fields = (
            "operation_id", "receipt", "verdict", "recoverable", "terminal",
            "page_state", "events", "started_at_ms", "finished_at_ms", "duration_ms",
        )
        return {field: data[field] for field in public_fields if field in data}

    @staticmethod
    def _commit_public(result: CommitResult) -> dict[str, Any]:
        return {
            "committed": result.committed,
            "rejection_reason": (result.rejection_reason.value if result.rejection_reason is not None else None),
            "receipt": result.receipt.to_dict() if result.receipt is not None else None,
        }

    def _observe(self, arguments: Any) -> dict[str, Any]:
        self._require_arguments(arguments, allowed=frozenset(), required=frozenset())
        reservation = self._reserve_handle_slot()
        try:
            observed = self._service.observe(**self._service_kwargs())
            handle = self._mint_handle(
                "observation",
                observed,
                control_epoch=observed.control_epoch,
                reservation_generation=reservation,
            )
        finally:
            self._release_handle_slot(reservation)
        return {
            "observation_handle": handle,
            "observed_at_ms": observed.observed_at_ms,
            "control_epoch": observed.control_epoch,
            "mutation_epoch": observed.mutation_epoch,
            "observation": observed.observation.to_dict(),
        }

    def _observation_reference(self, arguments: Mapping[str, Any]) -> Any | None:
        handle = arguments.get("observation_handle")
        element_id = arguments.get("element_id")
        if handle is None and element_id is None:
            return None
        if not isinstance(handle, str) or not isinstance(element_id, str) or not element_id or len(element_id) > 256:
            raise _MCPAdapterError("invalid_observation_reference")
        item = self._take_handle(handle, kind="observation")
        observed = item.value
        if not isinstance(observed, SessionObservation):
            raise _MCPAdapterError("invalid_handle")
        return observed.reference(element_id)

    def _execute(self, arguments: Any) -> dict[str, Any]:
        parsed = self._require_arguments(
            arguments,
            allowed=frozenset({"operation", "observation_handle", "element_id"}),
            required=frozenset({"operation"}),
        )
        operation = parse_operation(parsed["operation"])
        result = self._service.execute(
            **self._service_kwargs(),
            operation=operation,
            observation_reference=self._observation_reference(parsed),
        )
        return self._operation_public(result)

    def _prepare(self, arguments: Any) -> dict[str, Any]:
        parsed = self._require_arguments(arguments, allowed=frozenset({"operation"}), required=frozenset({"operation"}))
        reservation = self._reserve_handle_slot()
        try:
            prepared = self._service.prepare(
                **self._service_kwargs(), operation=parse_operation(parsed["operation"]), ttl_ms=MCP_PREPARE_TTL_MS,
            )
            handle = self._mint_handle(
                "prepared", prepared.token, expires_at_ms=prepared.expires_at_ms, reservation_generation=reservation,
            )
        finally:
            self._release_handle_slot(reservation)
        return self._prepared_public(prepared, handle)

    def _commit(self, arguments: Any) -> dict[str, Any]:
        parsed = self._require_arguments(arguments, allowed=frozenset({"prepared_handle"}), required=frozenset({"prepared_handle"}))
        item = self._take_handle(parsed["prepared_handle"], kind="prepared", consume=True)
        result = self._service.commit(**self._service_kwargs(), token=item.value)
        return self._commit_public(result)

    def _prepare_speculation(self, arguments: Any) -> dict[str, Any]:
        parsed = self._require_arguments(arguments, allowed=frozenset({"speculative_plan"}), required=frozenset({"speculative_plan"}))
        reservation = self._reserve_handle_slot()
        try:
            prepared = self._service.prepare_speculation(
                **self._service_kwargs(),
                plan=parse_speculative_plan(parsed["speculative_plan"]),
                ttl_ms=MCP_SPECULATION_TTL_MS,
            )
            handle = self._mint_handle(
                "speculation", prepared.token,
                expires_at_ms=prepared.expires_at_ms,
                control_epoch=prepared.control_epoch,
                reservation_generation=reservation,
            )
        finally:
            self._release_handle_slot(reservation)
        return self._speculation_public(prepared, handle)

    def _select_speculation(self, arguments: Any) -> dict[str, Any]:
        parsed = self._require_arguments(arguments, allowed=frozenset({"speculation_handle"}), required=frozenset({"speculation_handle"}))
        item = self._take_handle(parsed["speculation_handle"], kind="speculation")
        selection = self._service.select_speculative_branch(**self._service_kwargs(), token=item.value)
        return {
            "speculation_handle": parsed["speculation_handle"],
            "selection": self._selection_public(selection),
        }

    def _execute_speculation(self, arguments: Any) -> dict[str, Any]:
        parsed = self._require_arguments(arguments, allowed=frozenset({"speculation_handle"}), required=frozenset({"speculation_handle"}))
        # Consuming the selected speculation capability first frees its slot.
        # Reserve that slot again before branch dispatch because a selected
        # consequential branch may return a prepared-operation handle.
        item = self._take_handle(parsed["speculation_handle"], kind="speculation", consume=True)
        reservation = self._reserve_handle_slot()
        try:
            result: SpeculationExecutionResult = self._service.execute_selected_speculative_branch(
                **self._service_kwargs(), token=item.value,
            )
            payload: dict[str, Any] = {"selection": self._selection_public(result.selection)}
            if result.prepared_operation is not None:
                prepared = result.prepared_operation
                handle = self._mint_handle(
                    "prepared", prepared.token, expires_at_ms=prepared.expires_at_ms, reservation_generation=reservation,
                )
                payload["prepared_operation"] = self._prepared_public(prepared, handle)
            else:
                payload["prepared_operation"] = None
            payload["operation_result"] = (
                self._operation_public(result.operation_result)
                if result.operation_result is not None
                else None
            )
            return payload
        finally:
            self._release_handle_slot(reservation)

    def _contract(self, arguments: Any) -> dict[str, Any]:
        self._require_arguments(arguments, allowed=frozenset(), required=frozenset())
        # The complete PlanDocument source of truth remains discoverable even
        # though this adapter deliberately executes one governed operation at
        # a time instead of adding a second plan executor.
        return {
            "mcp_protocol_revision": MCP_PROTOCOL_REVISION,
            "machine_contract": execution_schema(),
            "operation_contract": operation_schema(),
            "speculative_plan_contract": speculative_plan_schema(),
        }

    @staticmethod
    def _safe_error(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, _MCPAdapterError):
            return {"error": {"code": exc.code, "message": "governed MCP request rejected"}}
        if isinstance(exc, ContractValidationError):
            return {
                "error": {
                    "code": "invalid_contract",
                    "message": "canonical DingDongDitch contract rejected",
                    "details": {
                        "contract_schema_version": exc.schema_version,
                        "errors": [item.to_dict() for item in exc.errors[:8]],
                    },
                }
            }
        if isinstance(exc, TwoPhaseCommitError):
            # Runtime exception text can be composed by providers/backends.
            # Preserve only the public enum; never forward exception content
            # through the planner-facing transport.
            return {
                "error": {
                    "code": "transaction_rejected",
                    "message": "prepared operation was rejected",
                    "details": {"reason": exc.reason.value},
                }
            }
        if isinstance(exc, StatefulSessionError):
            kind = getattr(exc.failure_kind, "value", "operation_rejected")
            return {"error": {"code": str(kind), "message": "governed session rejected the request"}}
        if isinstance(exc, PermissionError):
            return {"error": {"code": "access_denied", "message": "authenticated principal is not authorized"}}
        if isinstance(exc, (TypeError, ValueError)):
            return {"error": {"code": "invalid_request", "message": "governed MCP request rejected"}}
        return {"error": {"code": "internal_error", "message": "governed MCP operation failed"}}

    @staticmethod
    def _bounded_result(payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError):
            return {"error": {"code": "internal_error", "message": "governed MCP operation failed"}}
        if len(encoded.encode("utf-8")) > MAX_MCP_RESULT_BYTES:
            return {"error": {"code": "result_too_large", "message": "bounded MCP result exceeds adapter limit"}}
        return dict(payload)

    def _call_tool(self, name: Any, arguments: Any) -> tuple[bool, dict[str, Any]]:
        """Call a governed MCP tool without exposing JSON-RPC internals.

        The method is public for host-side tests and adapters.  It is not a
        bypass: there is no principal argument and every mutation goes through
        the service with the binding's host-held control token.
        """
        handlers: Mapping[str, Callable[[Any], dict[str, Any]]] = {
            "dingdong.get_contract": self._contract,
            "dingdong.observe": self._observe,
            "dingdong.execute": self._execute,
            "dingdong.prepare": self._prepare,
            "dingdong.commit": self._commit,
            "dingdong.prepare_speculation": self._prepare_speculation,
            "dingdong.select_speculative_branch": self._select_speculation,
            "dingdong.execute_selected_speculative_branch": self._execute_speculation,
        }
        if not isinstance(name, str) or name not in handlers:
            return True, {"error": {"code": "unknown_tool", "message": "unknown governed MCP tool"}}
        try:
            return False, self._bounded_result(handlers[name](arguments))
        except Exception as exc:
            return True, self._bounded_result(self._safe_error(exc))

    def call_tool(self, name: Any, arguments: Any) -> tuple[bool, dict[str, Any]]:
        """Call a governed MCP tool without exposing JSON-RPC internals.

        The method is public for host-side tests and alternate transports.  It
        is not a bypass: there is no principal argument and every mutation
        goes through the service with the binding's host-held control token.
        For a live stdio server, it also returns work to the one browser-owning
        execution thread rather than running it in the protocol event loop.
        """
        if self._execution_executor is not None:
            with self._lifecycle_lock:
                if self._closed:
                    return True, {"error": {"code": "server_closed", "message": "governed MCP server is closed"}}
                future = self._execution_executor.submit(self._call_tool, name, arguments)
            return future.result()
        if self._closed:
            return True, {"error": {"code": "server_closed", "message": "governed MCP server is closed"}}
        return self._call_tool(name, arguments)

    def tool_definitions(self) -> list[Any]:
        """Return official MCP Tool definitions derived from canonical schemas."""
        _, _, _, _, _, Tool, ToolAnnotations = _require_mcp_sdk()
        no_args = _empty_input_schema()
        return [
            Tool(
                name="dingdong.get_contract",
                title="DingDongDitch canonical contract",
                description="Read the canonical PlanDocument, Operation, and bounded speculative-plan JSON Schemas.",
                inputSchema=no_args,
                annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
            ),
            Tool(
                name="dingdong.observe",
                title="Observe governed browser state",
                description="Capture bounded browser evidence and return a principal-bound observation handle.",
                inputSchema=no_args,
                annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True),
            ),
            Tool(
                name="dingdong.execute",
                title="Execute one governed operation",
                description="Submit one canonical Operation through the existing authority, lease, freshness, transaction, quorum, receipt-chain, and signed-plan checks.",
                inputSchema=_operation_input_schema(include_observation=True),
                annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True),
            ),
            Tool(
                name="dingdong.prepare",
                title="Prepare consequential operation",
                description="Create a bounded opaque preparation handle for an operation whose host policy requires two-phase commit.",
                inputSchema=_operation_input_schema(include_observation=False),
                annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
            ),
            Tool(
                name="dingdong.commit",
                title="Commit prepared operation",
                description="Commit one principal-bound, single-use prepared-operation handle after the existing material-state rechecks.",
                inputSchema=_handle_input_schema("prepared"),
                annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True),
            ),
            Tool(
                name="dingdong.prepare_speculation",
                title="Prepare bounded speculative branches",
                description="Validate one canonical, bounded speculative graph without dispatching any branch action.",
                inputSchema=_speculation_input_schema(),
                annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
            ),
            Tool(
                name="dingdong.select_speculative_branch",
                title="Select one speculative branch",
                description="Use existing deterministic evidence to select exactly one prepared branch, or fail closed.",
                inputSchema=_handle_input_schema("speculation"),
                annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True),
            ),
            Tool(
                name="dingdong.execute_selected_speculative_branch",
                title="Execute selected speculative branch",
                description="Run one selected branch through existing lease, authority, mutation, two-phase-commit, quorum, and receipt controls.",
                inputSchema=_handle_input_schema("speculation"),
                annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True),
            ),
        ]

    def build_server(self) -> Any:
        """Build an official SDK server without starting an alternate runtime."""
        Server, _, CallToolResult, ListToolsResult, TextContent, _, _ = _require_mcp_sdk()

        async def list_tools(_context: Any, _params: Any) -> Any:
            return ListToolsResult(tools=self.tool_definitions(), ttlMs=60_000, cacheScope="public")

        async def call_tool(_context: Any, params: Any) -> Any:
            # Keep sync browser work entirely outside the MCP async loop. The
            # adapter then serializes it again onto its dedicated browser
            # thread where applicable.
            import anyio

            is_error, payload = await anyio.to_thread.run_sync(
                self.call_tool,
                params.name,
                {} if params.arguments is None else params.arguments,
            )
            text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            return CallToolResult(
                content=[TextContent(type="text", text=text)],
                structuredContent=payload,
                isError=is_error,
            )

        return Server(
            "dingdongditch-governed",
            version=__import__("dingdongditch").__version__,
            title="DingDongDitch Governed Execution",
            description="Thin MCP adapter over a host-owned GovernedAgentService session.",
            instructions=(
                "Submit only canonical DingDongDitch operations. The server enforces host policy, "
                "control leases, signed-plan limits, mutation freshness, two-phase commit, quorum, "
                "receipt chains, and bounded speculation. It does not expose browser objects, secrets, "
                "keys, trust configuration, checkpoints, or handoff bearer tokens."
            ),
            on_list_tools=list_tools,
            on_call_tool=call_tool,
        )

    def run_stdio(self) -> None:
        """Run the official MCP stdio transport until stdin closes.

        The SDK owns JSON-RPC framing and protects stdout from stray handler
        output.  This method emits no diagnostics itself; CLI diagnostics go
        to stderr.  The host-selected session is closed on disconnect by
        default so a disconnected planner cannot retain a live browser lease.
        """
        _, stdio_server, _, _, _, _, _ = _require_mcp_sdk()
        server = self.build_server()

        async def serve() -> None:
            try:
                async with stdio_server() as (read_stream, write_stream):
                    await server.run(
                        read_stream,
                        write_stream,
                        server.create_initialization_options(),
                    )
            finally:
                # Retaining a session is a host lifecycle choice, never a
                # permission to reuse a previous connection's capabilities.
                self._clear_handles()
                if self._binding.close_on_disconnect:
                    await anyio.to_thread.run_sync(self.close)

        import anyio

        anyio.run(serve)

    def close(self) -> None:
        """Host-side lifecycle cleanup; never exposed as a planner MCP tool."""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            executor = self._execution_executor
        self._clear_handles()
        try:
            if executor is not None:
                executor.submit(self._binding.session.close).result()
            else:
                self._binding.session.close()
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)


__all__ = [
    "MCP_PROTOCOL_REVISION",
    "MCP_SDK_REQUIREMENT",
    "MCPDependencyError",
    "MCPHostBinding",
    "GovernedMCPServer",
]
