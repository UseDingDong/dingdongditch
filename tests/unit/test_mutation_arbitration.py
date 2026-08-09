from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dingdongditch import (
    Action,
    ActionType,
    AuthorityEnvelope,
    MutationActor,
    MutationArbitrationPolicy,
    ObservationReference,
    Operation,
    ProvenanceClass,
    StatefulSessionError,
    StatefulSessionRuntime,
)
from dingdongditch.contract.transaction import CommitRejectedReason, TwoPhaseCommitError


def _policy(*, mutation: MutationArbitrationPolicy) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        policy_id="mutation-policy", allowed_origins=("https://example.test",),
        allowed_action_types=("navigate",), require_preparation_for=("navigate",),
        granted_authorities=(ProvenanceClass.HOST_POLICY, ProvenanceClass.AGENT_REASONING),
    )


def _operation() -> Operation:
    return Operation("submit", "https://example.test/form", Action(ActionType.NAVIGATE), provenance=(ProvenanceClass.AGENT_REASONING,))


class _MutationBackend:
    def __init__(self):
        self.is_started = True
        self.page = SimpleNamespace(url="https://example.test/form")
        self.page_id = "page-1"
        self.backend_identity = "test"
        self.browser_identity = "test"
        self.scope = {
            "url": "https://example.test/form", "readyState": "complete", "title": "form",
            "root": "<form><input value='1'></form>", "history_length": 1, "history_state": "null",
            "controls": [{"value": "1"}], "document_token": "doc-1", "mutation_count": 0,
        }

    def transaction_scope_state(self, **_kwargs):
        return deepcopy(self.scope)

    def start(self):
        return None

    def stop(self):
        self.is_started = False

    cleanup_errors: list[str] = []

    def browser_environment(self):
        return {"page_id": "page-1"}

    def list_pages(self):
        return [{"page_id": "page-1", "active": True}]

    def list_dialog_history(self):
        return []

    def scoped_action_url(self, **_kwargs):
        return self.page.url

    def mutate(self, *, value: str = "10"):
        self.scope["controls"] = [{"value": value}]
        self.scope["root"] = f"<form><input value='{value}'></form>"
        self.scope["mutation_count"] += 1


def _opened(policy: MutationArbitrationPolicy):
    runtime = StatefulSessionRuntime()
    opened = runtime.open_session(authority_envelope=_policy(mutation=policy), agent_id="agent", mutation_policy=policy)
    return runtime, opened


def test_external_form_change_invalidates_prepared_commit_and_reprepare_succeeds():
    backend = _MutationBackend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime, opened = _opened(MutationArbitrationPolicy.REQUIRE_REPREPARE)
        prepared = runtime.prepare_operation(opened.session_id, _operation(), agent_id="agent", control_token=opened.control["control_token"])
        backend.mutate(value="10")
        rejected = runtime.commit_operation(opened.session_id, prepared.token, agent_id="agent", control_token=opened.control["control_token"])
        assert not rejected.committed
        assert rejected.rejection_reason is CommitRejectedReason.PREPARATION_INVALIDATED
        reprepared = runtime.prepare_operation(opened.session_id, _operation(), agent_id="agent", control_token=opened.control["control_token"])
    assert reprepared.mutation_epoch == 1
    assert runtime.mutation_status(opened.session_id)["last_evidence"]["actor"] == "external_unknown"


def test_stale_observation_and_human_priority_fail_closed_then_allow_new_prepare():
    backend = _MutationBackend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime, opened = _opened(MutationArbitrationPolicy.HUMAN_PRIORITY)
        runtime.record_external_mutation(opened.session_id, actor=MutationActor.HUMAN)
        stale = ObservationReference("obs", "target", control_epoch=0, mutation_epoch=0)
        with pytest.raises(StatefulSessionError) as rejected:
            runtime.execute_operation(opened.session_id, _operation(), observation_reference=stale, agent_id="agent", control_token=opened.control["control_token"])
        prepared = runtime.prepare_operation(opened.session_id, _operation(), agent_id="agent", control_token=opened.control["control_token"])
    assert rejected.value.failure_kind.value == "mutation_conflict"
    assert prepared.mutation_epoch == 1
    assert runtime.mutation_status(opened.session_id)["last_evidence"]["actor"] == "human"


def test_external_change_cannot_be_bypassed_by_omitting_an_observation_reference():
    backend = _MutationBackend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime, opened = _opened(MutationArbitrationPolicy.REQUIRE_REPREPARE)
        backend.mutate(value="10")
        with pytest.raises(StatefulSessionError) as rejected:
            runtime.execute_operation(
                opened.session_id, _operation(), agent_id="agent", control_token=opened.control["control_token"],
            )
    assert rejected.value.failure_kind.value == "mutation_conflict"


def test_fail_on_external_mutation_blocks_new_prepare():
    backend = _MutationBackend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime, opened = _opened(MutationArbitrationPolicy.FAIL_ON_EXTERNAL_MUTATION)
        backend.mutate()
        with pytest.raises(StatefulSessionError) as rejected:
            runtime.prepare_operation(opened.session_id, _operation(), agent_id="agent", control_token=opened.control["control_token"])
    assert rejected.value.failure_kind.value == "mutation_conflict"


def test_browser_detected_mutation_never_claims_human_actor_and_stales_handoff():
    backend = _MutationBackend()
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime, opened = _opened(MutationArbitrationPolicy.REQUIRE_REPREPARE)
        checkpoint = runtime.prepare_agent_handoff(opened.session_id, agent_id="agent", control_token=opened.control["control_token"], recipient_agent_id="next")
        backend.mutate()
        with pytest.raises(StatefulSessionError) as rejected:
            runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "next", authenticated_agent_id="next")
    assert rejected.value.failure_kind.value == "handoff_checkpoint_stale"
    assert runtime.mutation_status(opened.session_id)["last_evidence"]["actor"] == "external_unknown"


def test_agent_mutation_evidence_is_conservative_when_dispatch_boundary_is_ambiguous():
    backend = _MutationBackend()
    # Direct execution is denied by the 2PC policy, so use the host mutation
    # recorder to verify the public actor boundary itself remains host-only.
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend):
        runtime, opened = _opened(MutationArbitrationPolicy.REQUIRE_REPREPARE)
        with pytest.raises(ValueError):
            runtime.record_external_mutation(opened.session_id, actor=MutationActor.AGENT)
