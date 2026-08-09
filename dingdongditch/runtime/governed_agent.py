"""Capability-scoped, agent-facing access to a host-owned governed session.

This module is the recommended integration boundary for external planners.  It
does not expose a Playwright object, backend, raw session record, authority
installation, secret provider, or lifecycle internals.  The older module-level
execution helpers remain compatibility APIs for trusted host code only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from dingdongditch.authentication import AuthenticationCapability
from dingdongditch.contract.authority import AuthorityEnvelope
from dingdongditch.contract.handoff import AgentHandoffCheckpoint
from dingdongditch.contract.observation import ObservationReference
from dingdongditch.contract.operation import Operation
from dingdongditch.contract.transaction import CommitResult, PreparedOperation
from dingdongditch.contract.signed_plan import SignedPlanAuthority, TrustedPlanVerifier
from dingdongditch.contract.identity import IdentityAssertion, IdentityRegistry
from dingdongditch.contract.mutation import MutationArbitrationPolicy, MutationEvidence
from dingdongditch.contract.attestation import (
    Attester,
    ExecutionAttestation,
    make_execution_attestation_statement,
)
from dingdongditch.contract.speculation import (
    BranchPreparation,
    BranchSelection,
    SpeculationExecutionResult,
    SpeculativePlan,
)
from dingdongditch.contract.receipt_chain import ReceiptChainCheckpoint
from dingdongditch.machine_contract import MACHINE_CONTRACT_VERSION
from dingdongditch.machine_contract import parse_operation, parse_speculative_plan
from dingdongditch.runtime.stateful_session import (
    SessionObservation,
    SessionOperationResult,
    StatefulSessionRuntime,
)


def _operation(value: Operation | Mapping[str, Any]) -> Operation:
    if isinstance(value, Operation):
        value.validate()
        return value
    return parse_operation(value)


def _speculative_plan(value: SpeculativePlan | Mapping[str, Any]) -> SpeculativePlan:
    """Machine transport accepts only the canonical, parent-bound shape."""
    if isinstance(value, SpeculativePlan):
        value.require_execution_binding()
        return value
    return parse_speculative_plan(value)


@dataclass(frozen=True)
class GovernedAgentSession:
    """One planner's least-privilege handle to a retained governed session.

    The handle is deliberately issued by :class:`TrustedHostRuntime`; callers
    cannot choose an authority envelope or access a browser directly.  In a
    single Python process this is API capability separation, not a hostile-code
    sandbox.  Cross-process callers should use ``GovernedAgentService`` behind
    an authenticated transport.
    """

    _runtime: StatefulSessionRuntime
    _session_id: str
    _agent_id: str
    _control_token: str

    @property
    def session_id(self) -> str:
        """Opaque host session reference; it is not a browser capability."""
        return self._session_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def observe(self, **kwargs: Any) -> SessionObservation:
        return self._runtime.observe_page(self._session_id, **kwargs)

    def execute(
        self,
        operation: Operation | Mapping[str, Any],
        *,
        observation_reference: ObservationReference | None = None,
    ) -> SessionOperationResult:
        return self._runtime.execute_operation(
            self._session_id, _operation(operation), observation_reference=observation_reference,
            agent_id=self._agent_id, control_token=self._control_token,
        )

    def prepare(self, operation: Operation | Mapping[str, Any], *, ttl_ms: int = 30_000) -> PreparedOperation:
        return self._runtime.prepare_operation(
            self._session_id, _operation(operation), ttl_ms=ttl_ms,
            agent_id=self._agent_id, control_token=self._control_token,
        )

    def commit(self, token: str, *, operation: Operation | Mapping[str, Any] | None = None) -> CommitResult:
        return self._runtime.commit_operation(
            self._session_id, token, operation=(_operation(operation) if operation is not None else None),
            agent_id=self._agent_id, control_token=self._control_token,
        )

    def prepare_handoff(self, recipient_agent_id: str, *, ttl_ms: int = 60_000) -> AgentHandoffCheckpoint:
        """Offer control to one named recipient; host delivers its token safely."""
        return self._runtime.prepare_agent_handoff(
            self._session_id, agent_id=self._agent_id, control_token=self._control_token,
            recipient_agent_id=recipient_agent_id, ttl_ms=ttl_ms,
        )

    def receipt_chain_checkpoint(self):
        return self._runtime.receipt_chain_checkpoint(self._session_id)

    def mutation_status(self) -> dict[str, Any]:
        return self._runtime.mutation_status(self._session_id)

    def prepare_speculation(self, plan: SpeculativePlan | Mapping[str, Any], *, ttl_ms: int = 30_000) -> BranchPreparation:
        return self._runtime.prepare_speculation(self._session_id, _speculative_plan(plan), ttl_ms=ttl_ms, agent_id=self._agent_id, control_token=self._control_token)

    def select_speculative_branch(self, token: str) -> BranchSelection:
        return self._runtime.select_speculative_branch(self._session_id, token, agent_id=self._agent_id, control_token=self._control_token)

    def execute_selected_speculative_branch(self, token: str) -> SpeculationExecutionResult:
        return self._runtime.execute_selected_speculative_branch(self._session_id, token, agent_id=self._agent_id, control_token=self._control_token)

    def close(self):
        return self._runtime.close_session(
            self._session_id, agent_id=self._agent_id, control_token=self._control_token,
        )


class TrustedHostRuntime:
    """Host-only owner of policy installation, secrets, and agent lifecycles."""

    def __init__(self, runtime: StatefulSessionRuntime | None = None) -> None:
        self._runtime = runtime or StatefulSessionRuntime()

    def open_governed_agent_session(
        self,
        *,
        authority_envelope: AuthorityEnvelope,
        agent_id: str,
        browser_config: Any | None = None,
        idle_timeout_ms: int | None = None,
        authentication: AuthenticationCapability | None = None,
        trusted_download_config: Any | None = None,
        identity_assertion: IdentityAssertion | None = None,
        identity_registry: IdentityRegistry | None = None,
        mutation_policy: MutationArbitrationPolicy = MutationArbitrationPolicy.REQUIRE_REPREPARE,
    ) -> GovernedAgentSession:
        if not isinstance(authority_envelope, AuthorityEnvelope):
            raise ValueError("a host-installed AuthorityEnvelope is required")
        opened = self._runtime.open_session(
            browser_config,
            idle_timeout_ms=idle_timeout_ms,
            authentication=authentication,
            trusted_download_config=trusted_download_config,
            authority_envelope=authority_envelope,
            agent_id=agent_id,
            mutation_policy=mutation_policy,
        )
        control = opened.control or {}
        session = GovernedAgentSession(self._runtime, opened.session_id, agent_id, str(control["control_token"]))
        if identity_assertion is not None or identity_registry is not None:
            if identity_assertion is None or identity_registry is None:
                try:
                    session.close()
                except Exception:
                    pass
                raise ValueError("identity assertion and trusted identity registry must be supplied together")
            try:
                self._runtime.bind_identity(session.session_id, identity_assertion, identity_registry)
            except Exception:
                try:
                    session.close()
                except Exception:
                    pass
                raise
        return session

    def open_signed_plan_agent_session(
        self,
        document: Any,
        signed_plan_authority: SignedPlanAuthority,
        *,
        trusted_plan_verifier: TrustedPlanVerifier,
        authority_envelope: AuthorityEnvelope,
        agent_id: str,
        browser_config: Any | None = None,
        idle_timeout_ms: int | None = None,
        authentication: AuthenticationCapability | None = None,
        trusted_download_config: Any | None = None,
        agent_identity_id: str | None = None,
        identity_assertion: IdentityAssertion | None = None,
        identity_registry: IdentityRegistry | None = None,
        mutation_policy: MutationArbitrationPolicy = MutationArbitrationPolicy.REQUIRE_REPREPARE,
    ) -> GovernedAgentSession:
        """Open the public agent path with an exact trusted signed plan.

        Only a trusted host can supply signer trust and install the envelope.
        The planner gets the same narrow governed handle as an unsigned
        session; it never receives signing keys or a way to replace the plan.
        """
        plan = getattr(document, "plan", document)
        if browser_config is None:
            browser_config = getattr(plan, "browser_config", None)
        session = self.open_governed_agent_session(
            authority_envelope=authority_envelope,
            agent_id=agent_id,
            browser_config=browser_config,
            idle_timeout_ms=idle_timeout_ms,
            authentication=authentication,
            trusted_download_config=trusted_download_config,
            identity_assertion=identity_assertion,
            identity_registry=identity_registry,
            mutation_policy=mutation_policy,
        )
        try:
            self._runtime.bind_signed_plan_authority(
                session.session_id,
                document,
                signed_plan_authority,
                trusted_plan_verifier,
                agent_identity_id=agent_identity_id,
            )
        except Exception:
            # Do not leave a browser session alive after a failed authority
            # bind. This is host cleanup, not an agent-visible raw API.
            try:
                session.close()
            except Exception:
                pass
            raise
        return session

    def claim_handoff(
        self,
        checkpoint: AgentHandoffCheckpoint,
        *,
        authenticated_agent_id: str,
    ) -> GovernedAgentSession:
        """Claim after the host transport authenticated the new recipient."""
        handoff = self._runtime.claim_agent_handoff(
            checkpoint.session_id, checkpoint.handoff_token, authenticated_agent_id,
            authenticated_agent_id=authenticated_agent_id,
        )
        return GovernedAgentSession(
            self._runtime, handoff.session_id, handoff.agent_id, handoff.control_token,
        )

    def prepare_identity_handoff(
        self,
        session: GovernedAgentSession,
        *,
        recipient_agent_id: str,
        recipient_identity_assertion: IdentityAssertion,
        ttl_ms: int = 60_000,
    ) -> AgentHandoffCheckpoint:
        """Host-only identity transition for a named controller handoff.

        Regular agent-facing handoff retains an unscoped identity. Changing a
        portable identity is a host trust decision and is never exposed as a
        planner proposal field.
        """
        if not isinstance(session, GovernedAgentSession) or session._runtime is not self._runtime:
            raise ValueError("session does not belong to this trusted host runtime")
        return self._runtime.prepare_agent_handoff(
            session.session_id,
            agent_id=session.agent_id,
            control_token=session._control_token,
            recipient_agent_id=recipient_agent_id,
            recipient_identity_assertion=recipient_identity_assertion,
            ttl_ms=ttl_ms,
        )

    def record_human_mutation(self, session: GovernedAgentSession) -> MutationEvidence:
        """Host-only attribution hook for an out-of-band manual interaction."""
        if not isinstance(session, GovernedAgentSession) or session._runtime is not self._runtime:
            raise ValueError("session does not belong to this trusted host runtime")
        from dingdongditch.contract.mutation import MutationActor
        return self._runtime.record_external_mutation(session.session_id, actor=MutationActor.HUMAN)

    def attest_execution(
        self,
        session: GovernedAgentSession,
        *,
        checkpoint: ReceiptChainCheckpoint,
        attester: Attester,
        expires_at_ms: int,
        nonce: str | None = None,
    ) -> ExecutionAttestation:
        """Submit bounded verified execution material to a host/external attester.

        The attester may be an external process adapter. This API never passes
        it browser/context/page objects or any key material from the runtime.
        """
        if not isinstance(session, GovernedAgentSession) or session._runtime is not self._runtime:
            raise ValueError("session does not belong to this trusted host runtime")
        material = self._runtime.attestation_material(session.session_id, checkpoint)
        statement = make_execution_attestation_statement(
            **material,
            checkpoint=checkpoint,
            contract_version=MACHINE_CONTRACT_VERSION,
            attester_id=attester.attester_id,
            assurance_level=attester.assurance_level,
            expires_at_ms=expires_at_ms,
            nonce=nonce,
        )
        return attester.sign(statement)


class GovernedAgentService:
    """Small transport-neutral RPC adapter for authenticated agent processes.

    A web, IPC, or queue transport authenticates a caller and passes that
    trusted principal as ``authenticated_agent_id``.  The adapter then enforces
    that principal against lease operations.  It serializes only JSON-shaped
    proposals/results and opaque session/lease tokens; raw browser/context/page
    objects are never part of this boundary.
    """

    def __init__(self, runtime: StatefulSessionRuntime) -> None:
        self._runtime = runtime

    @staticmethod
    def _principal(agent_id: str, authenticated_agent_id: str) -> None:
        if not isinstance(authenticated_agent_id, str) or authenticated_agent_id != agent_id:
            raise PermissionError("authenticated principal does not own this agent lease")

    def execute(
        self, *, session_id: str, agent_id: str, control_token: str,
        authenticated_agent_id: str, operation: Operation | Mapping[str, Any],
    ) -> SessionOperationResult:
        self._principal(agent_id, authenticated_agent_id)
        return self._runtime.execute_operation(
            session_id, _operation(operation), agent_id=agent_id, control_token=control_token,
        )

    def prepare(
        self, *, session_id: str, agent_id: str, control_token: str,
        authenticated_agent_id: str, operation: Operation | Mapping[str, Any], ttl_ms: int = 30_000,
    ) -> PreparedOperation:
        self._principal(agent_id, authenticated_agent_id)
        return self._runtime.prepare_operation(
            session_id, _operation(operation), ttl_ms=ttl_ms, agent_id=agent_id, control_token=control_token,
        )

    def commit(
        self, *, session_id: str, agent_id: str, control_token: str,
        authenticated_agent_id: str, token: str, operation: Operation | Mapping[str, Any] | None = None,
    ) -> CommitResult:
        self._principal(agent_id, authenticated_agent_id)
        return self._runtime.commit_operation(
            session_id, token, operation=(_operation(operation) if operation is not None else None),
            agent_id=agent_id, control_token=control_token,
        )

    def prepare_handoff(
        self, *, session_id: str, agent_id: str, control_token: str,
        authenticated_agent_id: str, recipient_agent_id: str, ttl_ms: int = 60_000,
    ) -> AgentHandoffCheckpoint:
        """Create a recipient-bound offer for host-controlled token delivery."""
        self._principal(agent_id, authenticated_agent_id)
        return self._runtime.prepare_agent_handoff(
            session_id, agent_id=agent_id, control_token=control_token,
            recipient_agent_id=recipient_agent_id, ttl_ms=ttl_ms,
        )

    def claim_handoff(
        self, *, session_id: str, handoff_token: str, authenticated_agent_id: str,
    ) -> dict[str, Any]:
        handoff = self._runtime.claim_agent_handoff(
            session_id, handoff_token, authenticated_agent_id,
            authenticated_agent_id=authenticated_agent_id,
        )
        return handoff.to_dict()

    def prepare_speculation(self, *, session_id: str, agent_id: str, control_token: str, authenticated_agent_id: str, plan: SpeculativePlan | Mapping[str, Any], ttl_ms: int = 30_000) -> BranchPreparation:
        self._principal(agent_id, authenticated_agent_id)
        return self._runtime.prepare_speculation(session_id, _speculative_plan(plan), ttl_ms=ttl_ms, agent_id=agent_id, control_token=control_token)

    def select_speculative_branch(self, *, session_id: str, agent_id: str, control_token: str, authenticated_agent_id: str, token: str) -> BranchSelection:
        self._principal(agent_id, authenticated_agent_id)
        return self._runtime.select_speculative_branch(session_id, token, agent_id=agent_id, control_token=control_token)

    def execute_selected_speculative_branch(self, *, session_id: str, agent_id: str, control_token: str, authenticated_agent_id: str, token: str) -> SpeculationExecutionResult:
        self._principal(agent_id, authenticated_agent_id)
        return self._runtime.execute_selected_speculative_branch(session_id, token, agent_id=agent_id, control_token=control_token)
