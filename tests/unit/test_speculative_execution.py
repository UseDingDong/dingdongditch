from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dingdongditch import (
    Action,
    ActionType,
    AuthorityEnvelope,
    BranchSelectionStatus,
    Expectation,
    ExpectationType,
    Locator,
    LocatorStrategy,
    MutationArbitrationPolicy,
    Operation,
    ProvenanceClass,
    SpeculativeBranch,
    SpeculativePlan,
    StatefulSessionError,
    StatefulSessionRuntime,
    GovernedAgentService,
    Verdict,
    parse_speculative_plan,
)
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.runtime.executor import _failed_receipt


class _Backend:
    cleanup_errors: list[str] = []
    def __init__(self):
        self.is_started = True; self.page = SimpleNamespace(url="https://example.test/a")
        self.page_id = "page-1"; self.backend_identity = "test"; self.browser_identity = "test"
        self.scope = {"url": self.page.url, "readyState": "complete", "title": "a", "root": "<body></body>", "history_length": 1, "history_state": "null", "controls": [], "document_token": "doc", "mutation_count": 0}
    def start(self): pass
    def stop(self): self.is_started = False
    def scoped_action_url(self, **_kwargs): return self.page.url
    def transaction_scope_state(self, **_kwargs): return deepcopy(self.scope)
    def list_pages(self): return [{"page_id": "page-1", "active": True, "current_url": self.page.url, "lifecycle_state": "open"}]
    def list_dialog_history(self): return []
    def browser_environment(self): return {"page_id": "page-1"}
    def mutate(self): self.scope["mutation_count"] += 1; self.scope["root"] = "<body>changed</body>"


def _policy(*, prep: bool = False, actions=("navigate",)):
    return AuthorityEnvelope(policy_id="spec", allowed_origins=("https://example.test",), allowed_action_types=actions, require_preparation_for=("navigate",) if prep else (), granted_authorities=(ProvenanceClass.HOST_POLICY, ProvenanceClass.AGENT_REASONING))


def _operation(identifier="next"):
    return Operation(identifier, "https://example.test/a", Action(ActionType.NAVIGATE), provenance=(ProvenanceClass.AGENT_REASONING,))


def _plan(*branches):
    parent = _operation("parent")
    return SpeculativePlan("spec-1", "parent", tuple(branches), parent_operation=parent)


def _open(policy, mutation=None):
    backend = _Backend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime = StatefulSessionRuntime()
        opened = runtime.open_session(authority_envelope=policy, agent_id="agent", mutation_policy=mutation)
    return runtime, opened, backend


def _mark_parent_executed(runtime, opened, token):
    record = runtime._records[opened.session_id]
    item = record.speculations[token]
    record.receipt_chain.append(SimpleNamespace(
        operation_id="parent", verdict=Verdict.VERIFIED,
        receipt_chain={"operation_hash": item.parent_operation_hash},
    ))


def _executed_receipt(operation, backend) -> ExecutionReceipt:
    base = _failed_receipt(
        operation=operation, started_at=1,
        collector=EvidenceCollector(scope_id=operation.operation_id, window_started_at_ms=1),
        locator_desc=None, execution_status="completed", execution_error="", failure_kind=None,
        browser=backend.browser_environment(), backend_identity="test", browser_identity="test",
        verdict=Verdict.VERIFIED,
    )
    return replace(
        base, _sealed=False, action_started_at_ms=1, action_completed_at_ms=2,
        action_executed_successfully=True,
    ).seal()


def test_exactly_one_branch_selection_and_consequential_branch_returns_preparation():
    yes = SpeculativeBranch("yes", (Expectation(ExpectationType.URL, url_value="https://example.test/a"),), _operation())
    no = SpeculativeBranch("no", (Expectation(ExpectationType.URL, url_value="https://example.test/b"),), _operation("other"))
    runtime, opened, _ = _open(_policy(prep=True))
    prepared = runtime.prepare_speculation(opened.session_id, _plan(yes, no), agent_id="agent", control_token=opened.control["control_token"])
    _mark_parent_executed(runtime, opened, prepared.token)
    selected = runtime.select_speculative_branch(opened.session_id, prepared.token, agent_id="agent", control_token=opened.control["control_token"])
    result = runtime.execute_selected_speculative_branch(opened.session_id, prepared.token, agent_id="agent", control_token=opened.control["control_token"])
    assert selected.status is BranchSelectionStatus.SELECTED and selected.branch_id == "yes"
    assert result.prepared_operation is not None


def test_zero_multiple_stale_and_undeclared_branches_fail_closed():
    zero = SpeculativeBranch("zero", (Expectation(ExpectationType.URL, url_value="https://example.test/no"),), _operation())
    one = SpeculativeBranch("one", (Expectation(ExpectationType.URL, url_value="https://example.test/a"),), _operation())
    two = SpeculativeBranch("two", (Expectation(ExpectationType.URL, url_value="https://example.test/a"),), _operation("two"))
    runtime, opened, backend = _open(_policy(), MutationArbitrationPolicy.REQUIRE_REPREPARE)
    token = runtime.prepare_speculation(opened.session_id, _plan(zero), agent_id="agent", control_token=opened.control["control_token"]).token
    _mark_parent_executed(runtime, opened, token)
    assert runtime.select_speculative_branch(opened.session_id, token, agent_id="agent", control_token=opened.control["control_token"]).status is BranchSelectionStatus.NO_MATCH
    token = runtime.prepare_speculation(opened.session_id, _plan(one, two), agent_id="agent", control_token=opened.control["control_token"]).token
    _mark_parent_executed(runtime, opened, token)
    assert runtime.select_speculative_branch(opened.session_id, token, agent_id="agent", control_token=opened.control["control_token"]).status is BranchSelectionStatus.AMBIGUOUS
    token = runtime.prepare_speculation(opened.session_id, _plan(one), agent_id="agent", control_token=opened.control["control_token"]).token
    _mark_parent_executed(runtime, opened, token)
    backend.mutate()
    assert runtime.select_speculative_branch(opened.session_id, token, agent_id="agent", control_token=opened.control["control_token"]).status is BranchSelectionStatus.STALE
    with pytest.raises(StatefulSessionError):
        runtime.execute_selected_speculative_branch(opened.session_id, token, agent_id="agent", control_token=opened.control["control_token"])


def test_unauthorized_branch_and_unbounded_graph_are_rejected():
    denied = SpeculativeBranch("denied", (Expectation(ExpectationType.URL, url_value="https://example.test/a"),), Operation("fill", "https://example.test/a", Action(ActionType.FILL, locator=Locator(LocatorStrategy.TEST_ID, "x"), text="x")))
    runtime, opened, _ = _open(_policy(actions=("navigate",)))
    with pytest.raises(StatefulSessionError):
        runtime.prepare_speculation(opened.session_id, _plan(denied), agent_id="agent", control_token=opened.control["control_token"])
    with pytest.raises(ValueError):
        SpeculativePlan("recursive", "parent", (denied,), max_depth=2).validate()
    with pytest.raises(ValueError):
        SpeculativePlan("many", "parent", tuple(denied for _ in range(9))).validate()


def test_handoff_stales_prepared_speculation_and_old_controller_cannot_select():
    branch = SpeculativeBranch("yes", (Expectation(ExpectationType.URL, url_value="https://example.test/a"),), _operation())
    runtime, opened, _ = _open(_policy())
    preparation = runtime.prepare_speculation(opened.session_id, _plan(branch), agent_id="agent", control_token=opened.control["control_token"])
    checkpoint = runtime.prepare_agent_handoff(opened.session_id, agent_id="agent", control_token=opened.control["control_token"], recipient_agent_id="next")
    handoff = runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "next", authenticated_agent_id="next")
    with pytest.raises(StatefulSessionError):
        runtime.select_speculative_branch(opened.session_id, preparation.token, agent_id="agent", control_token=opened.control["control_token"])
    assert runtime.select_speculative_branch(opened.session_id, preparation.token, agent_id="next", control_token=handoff.control_token).status is BranchSelectionStatus.STALE


def test_expected_parent_dispatch_advances_branch_epoch_without_authorizing_other_mutations():
    branch = SpeculativeBranch("yes", (Expectation(ExpectationType.URL, url_value="https://example.test/a"),), _operation())
    plan = _plan(branch)
    runtime, opened, backend = _open(_policy(), MutationArbitrationPolicy.REQUIRE_REPREPARE)
    with patch("dingdongditch.runtime.stateful_session._execute_operation", side_effect=lambda operation, **_: _executed_receipt(operation, backend)):
        prepared = runtime.prepare_speculation(opened.session_id, plan, agent_id="agent", control_token=opened.control["control_token"])
        runtime.execute_operation(opened.session_id, plan.parent_operation, agent_id="agent", control_token=opened.control["control_token"])
    assert runtime.select_speculative_branch(opened.session_id, prepared.token, agent_id="agent", control_token=opened.control["control_token"]).status is BranchSelectionStatus.SELECTED


def test_speculative_machine_contract_parser_rejects_unknown_and_unbounded_shapes():
    payload = _plan(SpeculativeBranch("yes", (Expectation(ExpectationType.URL, url_value="https://example.test/a"),), _operation())).to_dict()
    parsed = parse_speculative_plan(payload)
    assert parsed.speculation_id == "spec-1"
    with pytest.raises(Exception):
        parse_speculative_plan({**payload, "unknown": True})
    legacy = dict(payload); legacy.pop("parent_operation")
    with pytest.raises(Exception):
        parse_speculative_plan(legacy)


def test_governed_service_accepts_only_machine_safe_parent_bound_speculation():
    branch = SpeculativeBranch("yes", (Expectation(ExpectationType.URL, url_value="https://example.test/a"),), _operation())
    runtime, opened, _ = _open(_policy())
    service = GovernedAgentService(runtime)
    prepared = service.prepare_speculation(
        session_id=opened.session_id, agent_id="agent", control_token=opened.control["control_token"],
        authenticated_agent_id="agent", plan=_plan(branch).to_dict(),
    )
    assert prepared.branch_count == 1
    unsafe = _plan(branch).to_dict(); unsafe.pop("parent_operation")
    with pytest.raises(Exception):
        service.prepare_speculation(
            session_id=opened.session_id, agent_id="agent", control_token=opened.control["control_token"],
            authenticated_agent_id="agent", plan=unsafe,
        )
