"""Deterministic local all-ten-governance demonstration.

No model SDK, network service, raw browser export, or private key enters the
runtime.  The independent attester is a separate local process used only to
demonstrate the key/process boundary; it is not hardware attestation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import multiprocessing as mp
import time
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dingdongditch import (
    Action, ActionType, AssuranceLevel, AttesterTrustRegistry,
    AuthorityEnvelope, BranchSelectionStatus, EvidenceSourceClass, ExecutionPlan, Expectation,
    ExpectationType, ExternalAttesterAdapter, IdentityRegistry, IdentitySigner,
    Locator, LocatorStrategy, MutationActor, MutationArbitrationPolicy,
    Operation, ProvenanceClass, SpeculativeBranch, SpeculativePlan,
    StatefulSessionRuntime, TrustedPlanSigner, TrustedPlanVerifier,
    VerificationCheck, VerificationPolicy, VerificationQuorum,
    make_execution_attestation_statement, evaluate_quorum,
)
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.models import ExpectationResult
from dingdongditch.machine_contract import MACHINE_CONTRACT_VERSION, PlanDocument
from dingdongditch.runtime.executor import _failed_receipt


class _Backend:
    cleanup_errors: list[str] = []

    def __init__(self) -> None:
        self.is_started = True
        self.page_id = "page-local"
        self.page = SimpleNamespace(url="https://local.example.test/form")
        self.backend_identity = "local-fixture"
        self.browser_identity = "local-fixture"
        self.scope = {
            "url": self.page.url, "readyState": "complete", "title": "Local form",
            "root": "<form><input value='1'></form>", "history_length": 1,
            "history_state": "null", "controls": [{"value": "1"}],
            "document_token": "local-document", "mutation_count": 0,
        }

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self.is_started = False

    def transaction_scope_state(self, **_kwargs):
        return deepcopy(self.scope)

    def scoped_action_url(self, **_kwargs) -> str:
        return self.page.url

    def list_pages(self):
        return [{"page_id": self.page_id, "current_url": self.page.url, "title": "Local form", "active": True, "lifecycle_state": "open"}]

    def list_dialog_history(self):
        return []

    def browser_environment(self):
        return {"engine": "chromium", "channel": "bundled", "page_id": self.page_id, "browser_session_id": "local-session", "context_id": "local-context"}


def _receipt(operation: Operation, backend: _Backend, quorum: dict) -> ExecutionReceipt:
    base = _failed_receipt(
        operation=operation, started_at=1,
        collector=EvidenceCollector(scope_id=operation.operation_id, window_started_at_ms=1),
        locator_desc=None, execution_status="completed", execution_error="", failure_kind=None,
        browser=backend.browser_environment(), backend_identity=backend.backend_identity,
        browser_identity=backend.browser_identity, verdict=Verdict.VERIFIED,
    )
    return replace(
        base, _sealed=False, action_started_at_ms=1, action_completed_at_ms=2,
        verification_completed_at_ms=3, action_executed_successfully=True,
        quorum_verification=quorum,
    ).seal()


def _attester_process(connection) -> None:
    private = Ed25519PrivateKey.generate()
    connection.send(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    while True:
        payload = connection.recv()
        if payload is None:
            return
        connection.send(private.sign(payload))


class _PipeTransport:
    def __init__(self, connection) -> None:
        self._connection = connection

    def sign_statement(self, canonical_statement: bytes) -> bytes:
        self._connection.send(canonical_statement)
        return self._connection.recv()


def run_demo() -> dict[str, bool]:
    """Return only deterministic security assertions from a local run."""
    backend = _Backend()
    policy = AuthorityEnvelope(
        policy_id="complete-demo-policy",
        granted_authorities=(ProvenanceClass.HOST_POLICY, ProvenanceClass.AGENT_REASONING),
        allowed_origins=("https://local.example.test",), allowed_action_types=("navigate", "fill"),
        irreversible_action_types=("navigate",), require_preparation_for=("navigate",),
    )
    quorum = VerificationQuorum(
        policy=VerificationPolicy.ALL,
        checks=(
            VerificationCheck("dom", "dom", EvidenceSourceClass.DOM_STATE),
            VerificationCheck("network", "network", EvidenceSourceClass.NETWORK),
        ),
    )
    quorum_result = evaluate_quorum(quorum, [
        ExpectationResult("dom", "element_visible", {}, {}, "pass", ["dom"], 1, "pass", True),
        ExpectationResult("network", "network", {}, {}, "pass", ["network"], 1, "pass", True),
    ]).to_dict()
    parent = Operation("continue", backend.page.url, Action(ActionType.NAVIGATE), provenance=(ProvenanceClass.AGENT_REASONING,))
    branch_operation = Operation(
        "modal-fill", backend.page.url,
        Action(ActionType.FILL, locator=Locator(LocatorStrategy.TEST_ID, "message"), text="approved"),
        provenance=(ProvenanceClass.AGENT_REASONING,),
    )
    topology = SpeculativePlan(
        "continue-outcomes", "continue", (
            SpeculativeBranch("modal", (Expectation(ExpectationType.URL, url_value=backend.page.url),), branch_operation),
            SpeculativeBranch("other", (Expectation(ExpectationType.URL, url_value="https://local.example.test/other"),), Operation("other-fill", backend.page.url, Action(ActionType.FILL, locator=Locator(LocatorStrategy.TEST_ID, "message"), text="other"), provenance=(ProvenanceClass.AGENT_REASONING,))),
        ), parent_operation=parent,
    )
    submit = Operation(
        "submit", backend.page.url, Action(ActionType.NAVIGATE),
        expectations=(
            Expectation(ExpectationType.ELEMENT_VISIBLE, locator=Locator(LocatorStrategy.TEST_ID, "message"), visible=True, expectation_id="dom"),
            Expectation(ExpectationType.NETWORK, network_url_substring="https://local.example.test/submit", expectation_id="network"),
        ),
        provenance=(ProvenanceClass.AGENT_REASONING,), verification_quorum=quorum,
    )
    plan = ExecutionPlan("complete-demo", [parent, submit], authority_envelope=policy, speculative_plans=(topology,))
    document = PlanDocument(MACHINE_CONTRACT_VERSION, plan.browser_config, plan)

    identity_signer = IdentitySigner.generate(identity_id="user-agent-x", owner_id="local-user", issuer_id="local-host")
    identities = IdentityRegistry(); identities.register(identity_signer.identity)
    now = int(time.time() * 1000)
    identity_a = identity_signer.assert_identity(issued_at_ms=now - 1, expires_at_ms=now + 60_000, controller_scope="planner-a")
    identity_b = identity_signer.assert_identity(issued_at_ms=now - 1, expires_at_ms=now + 60_000, controller_scope="planner-b")
    plan_signer = TrustedPlanSigner.generate("local-plan-signer")
    plan_verifier = TrustedPlanVerifier({"local-plan-signer": plan_signer.public_key_bytes()})

    parent_pipe, child_pipe = mp.Pipe()
    process = mp.Process(target=_attester_process, args=(child_pipe,))
    process.start()
    try:
        attester_public = parent_pipe.recv()
        attester = ExternalAttesterAdapter("local-independent-attester", _PipeTransport(parent_pipe))
        with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend), patch(
            "dingdongditch.runtime.stateful_session._execute_operation",
            side_effect=lambda operation, **_: _receipt(operation, backend, quorum_result),
        ):
            runtime = StatefulSessionRuntime()
            opened = runtime.open_session(authority_envelope=policy, agent_id="planner-a", mutation_policy=MutationArbitrationPolicy.REQUIRE_REPREPARE)
            token_a = opened.control["control_token"]
            runtime.bind_identity(opened.session_id, identity_a, identities)
            signed = plan_signer.sign(
                document, authority_envelope_hash=policy.digest, issued_at_ms=now - 1,
                expires_at_ms=now + 60_000, nonce="complete-demo-plan", session_scope=opened.session_id,
                agent_identity_id="user-agent-x",
            )
            runtime.bind_signed_plan_authority(opened.session_id, document, signed, plan_verifier)
            branch_preparation = runtime.prepare_speculation(opened.session_id, topology, agent_id="planner-a", control_token=token_a)
            parent_preparation = runtime.prepare_operation(opened.session_id, parent, agent_id="planner-a", control_token=token_a)
            parent_commit = runtime.commit_operation(opened.session_id, parent_preparation.token, agent_id="planner-a", control_token=token_a)
            selection = runtime.select_speculative_branch(opened.session_id, branch_preparation.token, agent_id="planner-a", control_token=token_a)
            branch_result = runtime.execute_selected_speculative_branch(opened.session_id, branch_preparation.token, agent_id="planner-a", control_token=token_a)
            stale = runtime.prepare_operation(opened.session_id, submit, agent_id="planner-a", control_token=token_a)
            runtime.record_external_mutation(opened.session_id, actor=MutationActor.HUMAN)
            stale_result = runtime.commit_operation(opened.session_id, stale.token, agent_id="planner-a", control_token=token_a)
            fresh = runtime.prepare_operation(opened.session_id, submit, agent_id="planner-a", control_token=token_a)
            final = runtime.commit_operation(opened.session_id, fresh.token, agent_id="planner-a", control_token=token_a)
            checkpoint = runtime.receipt_chain_checkpoint(opened.session_id)
            material = runtime.attestation_material(opened.session_id, checkpoint)
            statement = make_execution_attestation_statement(
                **material, checkpoint=checkpoint, contract_version=MACHINE_CONTRACT_VERSION,
                attester_id=attester.attester_id, assurance_level=attester.assurance_level,
                expires_at_ms=now + 60_000, issued_at_ms=now, nonce="complete-demo-challenge",
            )
            attestation = attester.sign(statement)
            attestation_registry = AttesterTrustRegistry({attester.attester_id: (attester_public, AssuranceLevel.INDEPENDENT_ATTESTER)})
            offline_ok = attestation_registry.verify(
                attestation, receipts=runtime.receipt_chain(opened.session_id), expected_nonce="complete-demo-challenge",
                expected_plan_hash=signed.plan_hash, expected_session_id=opened.session_id,
                expected_policy_hash=policy.digest, expected_contract_version=MACHINE_CONTRACT_VERSION,
            )[0]
            altered_receipts = list(runtime.receipt_chain(opened.session_id))
            altered_receipts[-1] = replace(altered_receipts[-1], _sealed=False, operation_id="altered").seal()
            altered_rejected = not attestation_registry.verify(attestation, receipts=tuple(altered_receipts))[0]
            checkpoint_handoff = runtime.prepare_agent_handoff(
                opened.session_id, agent_id="planner-a", control_token=token_a,
                recipient_agent_id="planner-b", recipient_identity_assertion=identity_b,
            )
            handoff = runtime.claim_agent_handoff(opened.session_id, checkpoint_handoff.handoff_token, "planner-b", authenticated_agent_id="planner-b")
            old_rejected = False
            try:
                runtime.execute_operation(opened.session_id, submit, agent_id="planner-a", control_token=token_a)
            except Exception:
                old_rejected = True
            checkpoint_retained = checkpoint.chain_length == len(runtime.receipt_chain(opened.session_id))
            runtime.close_session(opened.session_id, agent_id="planner-b", control_token=handoff.control_token)
        return {
            "signed_speculation_selected": selection.status is BranchSelectionStatus.SELECTED and branch_result.operation_result is not None,
            "parent_committed_once": parent_commit.committed,
            "human_mutation_rejected_stale_commit": not stale_result.committed,
            "reprepared_commit_verified": final.committed and final.receipt.verdict is Verdict.VERIFIED,
            "same_identity_across_models": handoff.identity is not None and handoff.identity["identity_id"] == "user-agent-x",
            "old_controller_rejected": old_rejected,
            "receipt_chain_checkpointed": checkpoint_retained,
            "offline_independent_attestation_verified": offline_ok,
            "altered_receipt_rejected": altered_rejected,
        }
    finally:
        if process.is_alive():
            parent_pipe.send(None)
            process.join(timeout=10)
        if process.is_alive():
            process.terminate()


if __name__ == "__main__":
    print(run_demo())
