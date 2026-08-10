from __future__ import annotations

import anyio
from contextlib import asynccontextmanager
import json
import threading
from types import SimpleNamespace

import pytest

from dingdongditch import PlannerAdapter
from dingdongditch.contract.speculation import (
    BranchPreparation,
    BranchSelection,
    BranchSelectionStatus,
    SpeculationExecutionResult,
)
from dingdongditch.contract.transaction import (
    CommitRejectedReason,
    CommitResult,
    PreparedOperation,
    PreparationStatus,
    TwoPhaseCommitError,
)
from dingdongditch.machine_contract import execution_schema, operation_schema, speculative_plan_schema
from dingdongditch.mcp import MCPDependencyError, MCPHostBinding, MCP_PROTOCOL_REVISION, GovernedMCPServer
from dingdongditch.runtime.governed_agent import GovernedAgentSession
from dingdongditch.runtime.stateful_session import SessionFailureKind, SessionObservation, StatefulSessionError


class _Observation:
    observation_id = "observation-1"
    provenance = ()

    def to_dict(self):
        return {"observation_id": self.observation_id, "provenance": []}


class _OperationResult:
    def to_dict(self):
        return {
            "session_id": "real-session-id",
            "operation_id": "navigate",
            "verdict": "VERIFIED",
            "receipt": {"verdict": "VERIFIED", "browser": {"page_id": "page-1"}},
        }


class _LeakyOperationResult(_OperationResult):
    def to_dict(self):
        return super().to_dict() | {
            "control_token": "control-token-must-not-leak",
            "handoff_token": "handoff-token-must-not-leak",
            "browser_context": "browser-object-must-not-leak",
            "filesystem_path": "synthetic-path-must-not-leak",
        }


class _Service:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.epoch = 4
        self.observation = SessionObservation(
            session_id="real-session-id",
            page_id="page-1",
            observation=_Observation(),
            observed_at_ms=1,
            control_epoch=4,
            mutation_epoch=9,
        )

    def observe(self, **kwargs):
        self.calls.append(("observe", kwargs))
        return self.observation

    def control_epoch(self, **kwargs):
        self.calls.append(("control_epoch", kwargs))
        return self.epoch

    def execute(self, **kwargs):
        self.calls.append(("execute", kwargs))
        return _OperationResult()

    def prepare(self, **kwargs):
        self.calls.append(("prepare", kwargs))
        return PreparedOperation(
            token="real-prepared-token-must-not-leak",
            session_id="real-session-id",
            expires_at_ms=9_000_000_000_000,
            status=PreparationStatus.PREPARED,
            action_type="navigate",
            origin="https://example.test",
            page_id="page-1",
            state_fingerprint="state",
            target_fingerprint=None,
            operation_hash="operation",
            authority_policy_hash="policy",
            authority_decision={"outcome": "AUTHORIZED"},
            mutation_epoch=9,
            arbitration_policy="require_reprepare",
        )

    def commit(self, **kwargs):
        self.calls.append(("commit", kwargs))
        return CommitResult("real-session-id", kwargs["token"], True, None, None)

    def prepare_speculation(self, **kwargs):
        self.calls.append(("prepare_speculation", kwargs))
        return BranchPreparation(
            token="real-speculation-token-must-not-leak",
            session_id="real-session-id",
            speculation_id="spec-1",
            parent_operation_id="parent",
            control_epoch=4,
            mutation_epoch=9,
            expires_at_ms=9_000_000_000_000,
            branch_count=1,
        )

    def select_speculative_branch(self, **kwargs):
        self.calls.append(("select_speculative_branch", kwargs))
        return BranchSelection(kwargs["token"], BranchSelectionStatus.SELECTED, "branch-1", ({"check": "pass"},))

    def execute_selected_speculative_branch(self, **kwargs):
        self.calls.append(("execute_selected_speculative_branch", kwargs))
        return SpeculationExecutionResult(
            selection=BranchSelection(kwargs["token"], BranchSelectionStatus.SELECTED, "branch-1", ()),
            prepared_operation=None,
            operation_result=_OperationResult(),
        )


def _adapter(principal: str = "agent-a", session_id: str = "real-session-id") -> tuple[GovernedMCPServer, _Service]:
    # The unit test replaces the transport-neutral service with a spy. The
    # adapter itself still receives the real capability-scoped public handle.
    session = GovernedAgentSession(SimpleNamespace(), session_id, principal, "real-control-token")
    adapter = GovernedMCPServer(MCPHostBinding(session, principal, close_on_disconnect=False))
    service = _Service()
    adapter._service = service
    return adapter, service


def _operation() -> dict:
    return {
        "operation_id": "navigate",
        "url": "https://example.test",
        "action": {"type": "navigate"},
        "expectations": [],
    }


def _speculation() -> dict:
    parent = _operation() | {"operation_id": "parent"}
    continuation = _operation() | {"operation_id": "branch"}
    return {
        "speculation_id": "spec-1",
        "parent_operation_id": "parent",
        "parent_operation": parent,
        "max_depth": 1,
        "branches": [
            {
                "branch_id": "branch-1",
                "preconditions": [
                    {"type": "url", "url_value": "https://example.test", "expectation_id": "url"}
                ],
                "continuation": continuation,
            }
        ],
    }


def test_mcp_binding_requires_transport_principal_to_match_governed_lease():
    session = GovernedAgentSession(SimpleNamespace(), "session", "agent-a", "token")
    with pytest.raises(ValueError, match="must match"):
        MCPHostBinding(session, "planner-supplied-agent-b")


def test_tool_definitions_reuse_generated_contract_definitions_and_exclude_host_only_tools():
    adapter, _ = _adapter()
    tools = {tool.name: tool for tool in adapter.tool_definitions()}
    assert set(tools) == {
        "dingdong.get_contract", "dingdong.get_capabilities", "dingdong.observe", "dingdong.reobserve",
        "dingdong.execute", "dingdong.prepare", "dingdong.commit", "dingdong.prepare_speculation",
        "dingdong.select_speculative_branch", "dingdong.execute_selected_speculative_branch",
    }
    assert tools["dingdong.execute"].input_schema["$defs"] == operation_schema()["$defs"]
    assert tools["dingdong.execute"].input_schema["properties"]["operation"] == {"$ref": "#/$defs/Operation"}
    assert tools["dingdong.prepare_speculation"].input_schema["$defs"] == speculative_plan_schema()["$defs"]
    is_error, payload = adapter.call_tool("dingdong.get_contract", {})
    assert not is_error
    assert payload["mcp_protocol_revision"] == MCP_PROTOCOL_REVISION
    assert payload["machine_contract"] == execution_schema()

    is_error, capabilities = adapter.call_tool("dingdong.get_capabilities", {})
    assert not is_error
    assert capabilities["primary_calls"]["reobserve"] == "dingdong.reobserve"
    assert "press_key" in capabilities["operation"]["action_types"]
    assert "high_level_primitives" not in capabilities


def test_execute_uses_host_held_principal_and_server_side_observation_reference():
    adapter, service = _adapter()
    is_error, observed = adapter.call_tool("dingdong.observe", {})
    assert not is_error
    is_error, result = adapter.call_tool(
        "dingdong.execute",
        {
            "operation": _operation(),
            "observation_handle": observed["observation_handle"],
            "element_id": "button-1",
        },
    )
    assert not is_error
    assert "session_id" not in result
    execute = next(kwargs for name, kwargs in service.calls if name == "execute")
    assert execute["authenticated_agent_id"] == "agent-a"
    assert execute["agent_id"] == "agent-a"
    assert execute["control_token"] == "real-control-token"
    reference = execute["observation_reference"]
    assert reference.element_id == "button-1"
    assert reference.control_epoch == 4
    assert reference.mutation_epoch == 9


def test_reobserve_returns_a_fresh_handle_and_explicit_rebind_instructions():
    adapter, _ = _adapter()
    is_error, observed = adapter.call_tool("dingdong.observe", {})
    assert not is_error

    is_error, refreshed = adapter.call_tool(
        "dingdong.reobserve",
        {
            "previous_observation_handle": observed["observation_handle"],
            "previous_element_id": "button-1",
        },
    )

    assert not is_error
    assert refreshed["observation_handle"] != observed["observation_handle"]
    assert refreshed["recovery"] == {
        "kind": "reobserve_and_rebind",
        "previous_observation_id": "observation-1",
        "previous_element_id": "button-1",
        "rebind_required": True,
        "next_step": (
            "Select a current element_id from observation.interactive_elements, then submit "
            "the operation with this observation_handle and that element_id."
        ),
    }


def test_dynamic_mutation_error_preserves_reobserve_context():
    adapter, service = _adapter()
    is_error, observed = adapter.call_tool("dingdong.observe", {})
    assert not is_error
    service.execute = lambda **_kwargs: (_ for _ in ()).throw(
        StatefulSessionError("dynamic page changed", failure_kind=SessionFailureKind.MUTATION_CONFLICT)
    )

    is_error, rejected = adapter.call_tool(
        "dingdong.execute",
        {
            "operation": _operation(),
            "observation_handle": observed["observation_handle"],
            "element_id": "button-1",
        },
    )

    assert is_error
    assert rejected["error"]["code"] == "mutation_conflict"
    assert rejected["recovery"]["arguments"] == {
        "previous_observation_handle": observed["observation_handle"],
        "previous_element_id": "button-1",
    }


def test_public_planner_adapter_projects_the_governed_mcp_responses():
    transport, _ = _adapter()
    planner = PlannerAdapter(transport)

    capabilities = planner.available_actions()
    observed = planner.observe()
    rebound = planner.reobserve(
        previous_observation_handle=observed.result["observation_handle"],
        previous_element_id="button-1",
    )

    assert capabilities.ok and capabilities.result["planner_interface_version"] == "1.0"
    assert observed.ok and observed.result["observation_handle"]
    assert rebound.ok and rebound.recovery["kind"] == "reobserve_and_rebind"
    assert rebound.to_dict()["ok"] is True


def test_planner_cannot_forge_identity_or_call_host_only_tools():
    adapter, service = _adapter()
    is_error, payload = adapter.call_tool(
        "dingdong.execute",
        {"operation": _operation(), "authenticated_agent_id": "agent-b"},
    )
    assert is_error
    assert payload["error"]["code"] == "invalid_arguments"
    assert not service.calls
    for tool_name in (
        "dingdong.install_authority",
        "dingdong.raw_execute_plan",
        "dingdong.configure_signer",
        "dingdong.configure_secret_provider",
        "dingdong.configure_attester",
        "dingdong.configure_identity_registry",
        "dingdong.retain_checkpoint",
        "dingdong.record_human_mutation",
        "dingdong.prepare_handoff",
        "dingdong.claim_handoff",
        "dingdong.close_session",
    ):
        is_error, payload = adapter.call_tool(tool_name, {})
        assert is_error
        assert payload["error"]["code"] == "unknown_tool"


def test_prepared_handles_are_principal_scoped_single_use_and_do_not_leak_real_tokens():
    adapter, service = _adapter()
    is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert not is_error
    serialized = json.dumps(prepared)
    assert "real-prepared-token-must-not-leak" not in serialized
    assert "real-session-id" not in serialized
    is_error, committed = adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert not is_error
    assert committed["committed"] is True
    commit = next(kwargs for name, kwargs in service.calls if name == "commit")
    assert commit["token"] == "real-prepared-token-must-not-leak"
    is_error, replay = adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert is_error
    assert replay["error"]["code"] == "handle_already_used"
    other, _ = _adapter("agent-b")
    is_error, cross = other.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert is_error
    assert cross["error"]["code"] == "invalid_handle"


def test_handles_cannot_cross_sessions_even_for_the_same_authenticated_principal():
    adapter, _ = _adapter("agent-a", "session-a")
    is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert not is_error
    other, service = _adapter("agent-a", "session-b")
    is_error, response = other.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert is_error
    assert response["error"]["code"] == "invalid_handle"
    assert not service.calls


def test_stale_control_epoch_invalidates_all_adapter_handles_before_service_dispatch():
    adapter, service = _adapter()
    is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert not is_error
    service.epoch = 5  # Models a host-brokered handoff/control-epoch transition.
    is_error, stale = adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert is_error
    assert stale["error"]["code"] == "stale_handle"
    assert not any(name == "commit" for name, _ in service.calls)


def test_expired_adapter_handle_is_removed_before_commit_dispatch():
    adapter, service = _adapter()
    is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert not is_error
    adapter._handles[prepared["prepared_handle"]].expires_at_ms = 0
    is_error, expired = adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert is_error
    assert expired["error"]["code"] == "invalid_handle"
    assert not any(name == "commit" for name, _ in service.calls)


def test_disconnect_handle_cleanup_prevents_reconnect_replay_without_closing_session():
    adapter, service = _adapter()
    is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert not is_error
    # ``run_stdio`` calls this unconditionally, even when a trusted host
    # selects retain-on-disconnect for the browser session.
    adapter._clear_handles()
    is_error, replay = adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert is_error
    assert replay["error"]["code"] == "invalid_handle"
    assert not any(name == "commit" for name, _ in service.calls)


def test_stdio_disconnect_clears_handles_even_when_host_retains_the_session(monkeypatch):
    import dingdongditch.mcp.server as server_module

    adapter, service = _adapter()
    is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert not is_error

    @asynccontextmanager
    async def fake_stdio_server():
        yield object(), object()

    class _Server:
        def __init__(self, *_args, **_kwargs):
            pass

        def create_initialization_options(self):
            return object()

        async def run(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        server_module,
        "_require_mcp_sdk",
        lambda: (_Server, fake_stdio_server, object, object, object, object, object),
    )
    adapter.run_stdio()
    is_error, replay = adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert is_error
    assert replay["error"]["code"] == "invalid_handle"
    assert not any(name == "commit" for name, _ in service.calls)


def test_disconnect_invalidates_an_inflight_handle_reservation_before_minting():
    adapter, service = _adapter()
    entered = threading.Event()
    release = threading.Event()

    def delayed_observe(**kwargs):
        service.calls.append(("observe", kwargs))
        entered.set()
        assert release.wait(timeout=5)
        return service.observation

    service.observe = delayed_observe
    results: list[tuple[bool, dict]] = []
    worker = threading.Thread(target=lambda: results.append(adapter.call_tool("dingdong.observe", {})))
    worker.start()
    assert entered.wait(timeout=5)
    adapter._clear_handles()  # Models a stdio disconnect while work is in flight.
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert results[0][0]
    assert results[0][1]["error"]["code"] == "connection_closed"
    assert not adapter._handles


def test_live_handle_capacity_rejects_before_service_work_and_consumed_handles_do_not_exhaust_it():
    from dingdongditch.mcp.server import MAX_MCP_HANDLES

    adapter, service = _adapter()
    for _ in range(MAX_MCP_HANDLES):
        is_error, _ = adapter.call_tool("dingdong.observe", {})
        assert not is_error
    before = len(service.calls)
    is_error, full = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert is_error
    assert full["error"]["code"] == "handle_capacity"
    assert len(service.calls) == before  # no service/browser preparation after capacity rejection

    # A fresh connection can commit more than the active-handle limit because
    # consumed capabilities leave the live table immediately (with only a
    # bounded replay tombstone retained).
    adapter._clear_handles()
    for _ in range(MAX_MCP_HANDLES + 8):
        is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
        assert not is_error
        is_error, committed = adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
        assert not is_error
        assert committed["committed"] is True
    assert len(adapter._handles) == 0
    assert len(adapter._consumed_handle_tombstones) <= MAX_MCP_HANDLES


def test_selected_speculation_at_capacity_reuses_its_consumed_slot_before_dispatch():
    from dingdongditch.mcp.server import MAX_MCP_HANDLES

    adapter, service = _adapter()
    for _ in range(MAX_MCP_HANDLES - 1):
        is_error, _ = adapter.call_tool("dingdong.observe", {})
        assert not is_error
    is_error, speculation = adapter.call_tool("dingdong.prepare_speculation", {"speculative_plan": _speculation()})
    assert not is_error
    is_error, result = adapter.call_tool(
        "dingdong.execute_selected_speculative_branch",
        {"speculation_handle": speculation["speculation_handle"]},
    )
    assert not is_error
    assert result["operation_result"]["verdict"] == "VERIFIED"
    assert any(name == "execute_selected_speculative_branch" for name, _ in service.calls)


def test_speculation_handle_keeps_real_token_server_side_and_uses_existing_service():
    adapter, service = _adapter()
    is_error, prepared = adapter.call_tool("dingdong.prepare_speculation", {"speculative_plan": _speculation()})
    assert not is_error
    assert "real-speculation-token-must-not-leak" not in json.dumps(prepared)
    is_error, selected = adapter.call_tool(
        "dingdong.select_speculative_branch", {"speculation_handle": prepared["speculation_handle"]}
    )
    assert not is_error
    assert selected["selection"]["status"] == "selected"
    is_error, executed = adapter.call_tool(
        "dingdong.execute_selected_speculative_branch", {"speculation_handle": prepared["speculation_handle"]}
    )
    assert not is_error
    assert executed["selection"]["branch_id"] == "branch-1"
    assert any(name == "prepare_speculation" for name, _ in service.calls)
    assert any(name == "select_speculative_branch" for name, _ in service.calls)
    assert any(name == "execute_selected_speculative_branch" for name, _ in service.calls)


def test_concurrent_commit_and_speculation_execution_each_dispatch_once():
    adapter, service = _adapter()
    is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert not is_error
    barrier = threading.Barrier(3)
    commit_results: list[tuple[bool, dict]] = []

    def commit() -> None:
        barrier.wait()
        commit_results.append(adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]}))

    workers = [threading.Thread(target=commit), threading.Thread(target=commit)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()
    assert sum(not failed for failed, _ in commit_results) == 1
    assert sum(payload["error"]["code"] == "handle_already_used" for failed, payload in commit_results if failed) == 1
    assert sum(name == "commit" for name, _ in service.calls) == 1

    is_error, speculation = adapter.call_tool("dingdong.prepare_speculation", {"speculative_plan": _speculation()})
    assert not is_error
    barrier = threading.Barrier(3)
    speculation_results: list[tuple[bool, dict]] = []

    def execute_speculation() -> None:
        barrier.wait()
        speculation_results.append(adapter.call_tool(
            "dingdong.execute_selected_speculative_branch",
            {"speculation_handle": speculation["speculation_handle"]},
        ))

    workers = [threading.Thread(target=execute_speculation), threading.Thread(target=execute_speculation)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()
    assert sum(not failed for failed, _ in speculation_results) == 1
    assert sum(payload["error"]["code"] == "handle_already_used" for failed, payload in speculation_results if failed) == 1
    assert sum(name == "execute_selected_speculative_branch" for name, _ in service.calls) == 1


def test_malformed_oversized_and_unexpected_failures_are_bounded_and_secret_safe():
    adapter, service = _adapter()
    is_error, malformed = adapter.call_tool("dingdong.execute", {"operation": {"unexpected": "field"}})
    assert is_error
    assert malformed["error"]["code"] == "invalid_contract"
    is_error, oversized = adapter.call_tool(
        "dingdong.execute",
        {"operation": _operation() | {"operation_id": "x" * 1_100_000}},
    )
    assert is_error
    assert oversized["error"]["code"] == "request_too_large"
    service.execute = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret-value-must-not-leak"))
    is_error, failed = adapter.call_tool("dingdong.execute", {"operation": _operation()})
    assert is_error
    assert failed["error"]["code"] == "internal_error"
    assert "secret-value-must-not-leak" not in json.dumps(failed)


def test_operation_result_projection_drops_undocumented_privileged_fields():
    adapter, service = _adapter()
    service.execute = lambda **kwargs: _LeakyOperationResult()
    is_error, result = adapter.call_tool("dingdong.execute", {"operation": _operation()})
    assert not is_error
    serialized = json.dumps(result)
    assert "control-token-must-not-leak" not in serialized
    assert "handoff-token-must-not-leak" not in serialized
    assert "browser-object-must-not-leak" not in serialized
    assert "synthetic-path-must-not-leak" not in serialized


def test_transaction_exception_text_is_not_reflected_to_the_mcp_planner():
    adapter, service = _adapter()
    is_error, prepared = adapter.call_tool("dingdong.prepare", {"operation": _operation()})
    assert not is_error
    service.commit = lambda **kwargs: (_ for _ in ()).throw(
        TwoPhaseCommitError(CommitRejectedReason.AUTHORITY_REJECTED, "secret-provider-detail-must-not-leak")
    )
    is_error, failure = adapter.call_tool("dingdong.commit", {"prepared_handle": prepared["prepared_handle"]})
    assert is_error
    assert failure["error"]["details"] == {"reason": "AUTHORITY_REJECTED"}
    assert "secret-provider-detail-must-not-leak" not in json.dumps(failure)


def test_pathological_json_shape_fails_before_contract_parsing_or_service_dispatch():
    adapter, service = _adapter()
    value: object = {"operation": _operation()}
    for _ in range(80):
        value = {"operation": value}
    is_error, failure = adapter.call_tool("dingdong.execute", value)
    assert is_error
    assert failure["error"]["code"] == "request_too_complex"
    assert not service.calls

    cyclic: dict[str, object] = {}
    cyclic["operation"] = cyclic
    is_error, failure = adapter.call_tool("dingdong.execute", cyclic)
    assert is_error
    assert failure["error"]["code"] == "request_too_complex"
    assert not service.calls


def test_extra_authority_or_signed_plan_sidecars_cannot_widen_canonical_requests():
    adapter, service = _adapter()
    is_error, widened_operation = adapter.call_tool(
        "dingdong.execute",
        {"operation": _operation(), "authority_envelope": {"allowed_action_types": ["delete"]}},
    )
    assert is_error
    assert widened_operation["error"]["code"] == "invalid_arguments"
    is_error, widened_speculation = adapter.call_tool(
        "dingdong.prepare_speculation",
        {"speculative_plan": _speculation(), "signed_plan": {"untrusted": True}},
    )
    assert is_error
    assert widened_speculation["error"]["code"] == "invalid_arguments"
    assert not service.calls


def test_non_mapping_empty_arguments_are_not_silently_coerced_to_an_empty_object():
    adapter, service = _adapter()
    is_error, response = adapter.call_tool("dingdong.observe", [])
    assert is_error
    assert response["error"]["code"] == "invalid_arguments"
    assert not service.calls


def test_mismatched_installed_sdk_fails_closed(monkeypatch):
    import dingdongditch.mcp.server as server_module

    monkeypatch.setattr(server_module, "distribution_version", lambda _name: "2.0.1")
    adapter, _ = _adapter()
    with pytest.raises(MCPDependencyError, match="supported pinned version"):
        adapter.tool_definitions()


def test_official_mcp_sdk_discovers_governed_tools_in_process():
    adapter, _ = _adapter()

    async def exercise() -> None:
        from mcp.client import Client

        async with Client(adapter.build_server(), mode=MCP_PROTOCOL_REVISION) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} >= {"dingdong.observe", "dingdong.execute"}
            result = await client.call_tool("dingdong.get_contract", {})
            assert not result.is_error
            assert result.structured_content["mcp_protocol_revision"] == MCP_PROTOCOL_REVISION

    anyio.run(exercise)
