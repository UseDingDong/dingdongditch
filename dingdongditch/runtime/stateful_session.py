"""Public stateful facade over the existing DingDongDitch execution runtime."""

from __future__ import annotations

import threading
import time
import uuid
import hashlib
import secrets
import hmac
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from dingdongditch.authentication import AuthenticationError
from dingdongditch.authentication import AuthenticationCapability
from dingdongditch.backends.playwright_backend import PlaywrightBackend, monotonic_ms
from dingdongditch.contract.browser import BrowserConfig, BrowserConfigError
from dingdongditch.contract.observation import (
    ObservationReference,
    PageObservation,
    PageObservationOptions,
)
from dingdongditch.contract.operation import Operation
from dingdongditch.contract.authority import AuthorityEnvelope, AuthorityFirewall, canonical_json_bytes
from dingdongditch.contract.authority import merge_provenance
from dingdongditch.contract.plan import ExecutionPlan, PlanReceipt
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.transaction import (
    CommitRejectedReason,
    CommitResult,
    PreparedOperation,
    PreparationStatus,
    TwoPhaseCommitError,
)
from dingdongditch.contract.receipt_chain import (
    ReceiptChainCheckpoint,
    chain_receipt,
    make_receipt_chain_checkpoint,
    verify_receipt_chain_against_checkpoint,
)
from dingdongditch.contract.handoff import AgentHandoff, AgentHandoffCheckpoint
from dingdongditch.contract.signed_plan import (
    SignedPlanAuthority,
    TrustedPlanVerifier,
    canonical_plan_hash,
    public_signed_plan_reference,
)
from dingdongditch.contract.identity import (
    AgentIdentity,
    IdentityAssertion,
    IdentityError,
    IdentityRegistry,
    identity_reference,
)
from dingdongditch.contract.mutation import (
    MutationActor,
    MutationArbitrationPolicy,
    MutationEvidence,
)
from dingdongditch.contract.speculation import (
    BranchPreparation,
    BranchSelection,
    BranchSelectionStatus,
    SpeculationExecutionResult,
    SpeculativePlan,
)
from dingdongditch.contract.verdict import Verdict
from dingdongditch.contract.download import TrustedDownloadConfig
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.runtime.executor import _execute_operation, _failed_receipt
from dingdongditch.runtime.plan_executor import execute_plan as _execute_plan
from dingdongditch.runtime.verifier import evaluate_expectations


def _now_ms() -> int:
    return int(time.time() * 1000)


class PublicSessionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"
    TERMINAL = "terminal"


class SessionFailureKind(str, Enum):
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_CLOSED = "session_closed"
    SESSION_EXPIRED = "session_expired"
    PROFILE_LOCKED = "profile_locked"
    BROWSER_STARTUP_FAILURE = "browser_startup_failure"
    INVALID_PAGE_ID = "invalid_page_id"
    TERMINAL_BROWSER_FAILURE = "terminal_browser_failure"
    OPERATION_REJECTED = "operation_rejected"
    CLEANUP_FAILURE = "cleanup_failure"
    SESSION_BUSY = "session_busy"
    SESSION_CONFIG_MISMATCH = "session_config_mismatch"
    CONTROL_LEASE_REJECTED = "control_lease_rejected"
    HANDOFF_TOKEN_INVALID = "handoff_token_invalid"
    HANDOFF_TOKEN_EXPIRED = "handoff_token_expired"
    HANDOFF_ALREADY_CLAIMED = "handoff_already_claimed"
    HANDOFF_RECIPIENT_REJECTED = "handoff_recipient_rejected"
    HANDOFF_CHECKPOINT_STALE = "handoff_checkpoint_stale"
    SIGNED_PLAN_REJECTED = "signed_plan_rejected"
    MUTATION_CONFLICT = "mutation_conflict"


class StatefulSessionError(RuntimeError):
    def __init__(self, message: str, *, failure_kind: SessionFailureKind) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind

    def to_dict(self) -> dict[str, str]:
        return {"failure_kind": self.failure_kind.value, "message": str(self)}


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    status: PublicSessionStatus
    created_at_ms: int
    last_activity_at_ms: int
    idle_timeout_ms: int
    profile: str
    browser_engine: str
    headless: bool
    pages: tuple[dict[str, Any], ...]
    cleanup_errors: tuple[str, ...] = ()
    authority_policy: dict[str, Any] | None = None
    receipt_chain_head: str | None = None
    control: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "created_at_ms": self.created_at_ms,
            "last_activity_at_ms": self.last_activity_at_ms,
            "idle_timeout_ms": self.idle_timeout_ms,
            "profile": self.profile,
            "browser_engine": self.browser_engine,
            "headless": self.headless,
            "pages": [dict(page) for page in self.pages],
            "cleanup_errors": list(self.cleanup_errors),
            "authority_policy": self.authority_policy,
            "receipt_chain_head": self.receipt_chain_head,
            "control": self.control,
        }


@dataclass(frozen=True)
class SessionObservation:
    session_id: str
    page_id: str
    observation: PageObservation
    observed_at_ms: int
    control_epoch: int = 0
    mutation_epoch: int = 0

    def reference(self, element_id: str, *, expected: dict[str, Any] | None = None) -> ObservationReference:
        return ObservationReference(
            observation_id=self.observation.observation_id,
            element_id=element_id,
            expected=dict(expected or {}),
            control_epoch=self.control_epoch,
            mutation_epoch=self.mutation_epoch,
            provenance=tuple(self.observation.provenance),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "page_id": self.page_id,
            "observed_at_ms": self.observed_at_ms,
            "control_epoch": self.control_epoch,
            "mutation_epoch": self.mutation_epoch,
            "observation": self.observation.to_dict(),
        }


@dataclass(frozen=True)
class SessionOperationResult:
    session_id: str
    operation_id: str
    receipt: ExecutionReceipt
    verdict: str
    recoverable: bool
    terminal: bool
    page_state: tuple[dict[str, Any], ...]
    events: dict[str, Any]
    started_at_ms: int
    finished_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "operation_id": self.operation_id,
            "receipt": self.receipt.to_dict(),
            "verdict": self.verdict,
            "recoverable": self.recoverable,
            "terminal": self.terminal,
            "page_state": [dict(page) for page in self.page_state],
            "events": dict(self.events),
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "duration_ms": max(0, self.finished_at_ms - self.started_at_ms),
        }


@dataclass(frozen=True)
class SessionPlanResult:
    session_id: str
    receipt: PlanReceipt
    recoverable: bool
    terminal: bool
    page_state: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "receipt": self.receipt.to_dict(),
            "recoverable": self.recoverable,
            "terminal": self.terminal,
            "page_state": [dict(page) for page in self.page_state],
        }


@dataclass
class _SessionRecord:
    session_id: str
    backend: PlaywrightBackend | None
    config: BrowserConfig
    created_at_ms: int
    last_activity_at_ms: int
    idle_timeout_ms: int
    status: PublicSessionStatus = PublicSessionStatus.OPEN
    cleanup_errors: list[str] = field(default_factory=list)
    authority_envelope: AuthorityEnvelope | None = None
    authority_action_count: int = 0
    authority_side_effect_count: int = 0
    preparations: dict[str, "_PreparedRecord"] = field(default_factory=dict)
    active_commit_token: str | None = None
    active_transaction: dict[str, Any] | None = None
    receipt_chain_head: str | None = None
    receipt_chain: list[ExecutionReceipt] = field(default_factory=list)
    agent_id: str | None = None
    control_epoch: int = 0
    control_token: str | None = None
    pending_handoffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # These are host-installed only after cryptographic verification.  The
    # statement is public; neither signer keys nor plan payloads are exported
    # through session inspection or receipts.
    signed_plan_authority: SignedPlanAuthority | None = None
    signed_plan_operation_bytes: tuple[bytes, ...] = ()
    signed_plan_speculations: dict[str, SpeculativePlan] = field(default_factory=dict)
    signed_plan_next_index: int = 0
    identity_registry: IdentityRegistry | None = None
    identity_assertion: IdentityAssertion | None = None
    identity_descriptor: AgentIdentity | None = None
    mutation_policy: MutationArbitrationPolicy | None = None
    mutation_epoch: int = 0
    mutation_scope_key: str | None = None
    mutation_state_fingerprint: str | None = None
    mutation_last_evidence: MutationEvidence | None = None
    mutation_events: list[MutationEvidence] = field(default_factory=list)
    speculations: dict[str, "_SpeculationRecord"] = field(default_factory=dict)
    active_speculation: dict[str, Any] | None = None
    # HMAC key for prepared-state fingerprints.  The public fingerprint must
    # not become an offline oracle for transient form/CSRF/secret values.
    preparation_fingerprint_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    lock: Any = field(default_factory=threading.RLock)


@dataclass
class _PreparedRecord:
    public: PreparedOperation
    operation: Operation
    state: dict[str, Any]
    signed_speculation_operation: bytes | None = None
    speculation_summary: dict[str, Any] | None = None


@dataclass
class _SpeculationRecord:
    public: BranchPreparation
    plan: SpeculativePlan
    selected: BranchSelection | None = None
    consumed: bool = False
    parent_operation_hash: str | None = None
    signed_speculation_operation_bytes: dict[str, bytes] = field(default_factory=dict)


class StatefulSessionRuntime:
    """Process-local owner of retained, isolated browser sessions."""

    def __init__(self, *, default_idle_timeout_ms: int = 30 * 60 * 1000) -> None:
        if not isinstance(default_idle_timeout_ms, int) or default_idle_timeout_ms <= 0:
            raise ValueError("default_idle_timeout_ms must be a positive integer")
        self.default_idle_timeout_ms = default_idle_timeout_ms
        self._records: dict[str, _SessionRecord] = {}
        self._registry_lock = threading.RLock()

    def open_session(
        self,
        browser_config: BrowserConfig | None = None,
        *,
        idle_timeout_ms: int | None = None,
        trusted_download_config: TrustedDownloadConfig | None = None,
        authentication: AuthenticationCapability | None = None,
        authority_envelope: AuthorityEnvelope | None = None,
        agent_id: str | None = None,
        mutation_policy: MutationArbitrationPolicy | None = None,
    ) -> SessionInfo:
        config = browser_config or BrowserConfig()
        config.validate()
        if authority_envelope is not None and not isinstance(authority_envelope, AuthorityEnvelope):
            raise ValueError("authority_envelope must be an AuthorityEnvelope")
        self._validate_agent_id(agent_id)
        if mutation_policy is not None and not isinstance(mutation_policy, MutationArbitrationPolicy):
            raise ValueError("mutation_policy must be a MutationArbitrationPolicy")
        timeout = self.default_idle_timeout_ms if idle_timeout_ms is None else idle_timeout_ms
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("idle_timeout_ms must be a positive integer")
        backend = PlaywrightBackend(
            browser_config=config,
            trusted_download_config=trusted_download_config,
            authentication=authentication,
        )
        try:
            backend.start()
        except BrowserConfigError as exc:
            kind = (
                SessionFailureKind.PROFILE_LOCKED
                if exc.failure_kind.value == "profile_in_use"
                else SessionFailureKind.BROWSER_STARTUP_FAILURE
            )
            raise StatefulSessionError(
                "browser session could not be started",
                failure_kind=kind,
            ) from exc
        except AuthenticationError as exc:
            raise StatefulSessionError(
                "browser session authentication setup failed",
                failure_kind=SessionFailureKind.BROWSER_STARTUP_FAILURE,
            ) from exc
        now = _now_ms()
        record = _SessionRecord(
            session_id=str(uuid.uuid4()),
            backend=backend,
            config=config,
            created_at_ms=now,
            last_activity_at_ms=now,
            idle_timeout_ms=timeout,
            authority_envelope=authority_envelope,
            agent_id=agent_id,
            control_token=(secrets.token_urlsafe(32) if agent_id is not None else None),
            mutation_policy=mutation_policy,
            mutation_scope_key=("__dingdongditch_mutation_scope_" + secrets.token_hex(16) if mutation_policy is not None else None),
        )
        with self._registry_lock:
            self._records[record.session_id] = record
        if mutation_policy is not None:
            try:
                self._initialize_mutation_monitor(record)
            except Exception:
                self._close_record(record, PublicSessionStatus.TERMINAL)
                with self._registry_lock:
                    self._records.pop(record.session_id, None)
                raise StatefulSessionError("browser mutation monitor could not be initialized", failure_kind=SessionFailureKind.BROWSER_STARTUP_FAILURE)
        # The creator needs the initial lease exactly once.  Later inspection
        # is deliberately read-only and never becomes a capability-discovery
        # API.
        return self._info(record, include_control_token=True)

    def get_session(self, session_id: str) -> SessionInfo:
        record = self._require_record(session_id, require_open=False)
        if record.status == PublicSessionStatus.OPEN:
            self._expire_if_idle(record)
        return self._info(record)

    def observe_page(
        self,
        session_id: str,
        options: PageObservationOptions | None = None,
        *,
        page_id: str | None = None,
    ) -> SessionObservation:
        record = self._access(session_id)
        with self._locked(record):
            backend = self._active_backend(record)
            if page_id is not None:
                self._select_backend_page(backend, page_id)
            observation = backend.observe_page(options)
            self._touch(record)
            return SessionObservation(
                session_id=record.session_id,
                page_id=str(backend.page_id),
                observation=observation,
                observed_at_ms=_now_ms(),
                control_epoch=record.control_epoch,
                mutation_epoch=record.mutation_epoch,
            )

    def prepare_operation(
        self,
        session_id: str,
        operation: Operation,
        *,
        ttl_ms: int = 30_000,
        agent_id: str | None = None,
        control_token: str | None = None,
        _signed_speculation_operation: bytes | None = None,
        _speculation_summary: dict[str, Any] | None = None,
    ) -> PreparedOperation:
        """Bind one consequential operation to current retained browser state."""
        if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or not 100 <= ttl_ms <= 300_000:
            raise ValueError("ttl_ms must be between 100 and 300000")
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            self._require_identity(record)
            self._require_signed_plan_operation(
                record, operation, signed_speculation_operation=_signed_speculation_operation,
            )
            changed = self._refresh_external_mutation(record)
            # Preparation captures fresh material state and is the bounded
            # recovery operation for REQUIRE_REPREPARE/HUMAN_PRIORITY.
            self._reject_mutation_if_policy_requires(record, changed=changed, operation_has_fresh_observation=True)
            envelope = record.authority_envelope
            action_types = self._governed_action_types(operation)
            if envelope is None or not any(action_type in envelope.require_preparation_for for action_type in action_types):
                raise TwoPhaseCommitError(
                    CommitRejectedReason.NOT_CONSEQUENTIAL,
                    "operation is not declared consequential by the host policy",
                )
            if operation.guard is not None and not operation.guard.is_legacy_target_absent:
                raise TwoPhaseCommitError(
                    CommitRejectedReason.PREPARED_STATE_CHANGED,
                    "branching guarded actions are not eligible for a single-target commit",
                )
            backend = self._active_backend(record)
            decision = self._firewall_decision(record, operation, backend)
            if not decision.authorized:
                raise TwoPhaseCommitError(
                    CommitRejectedReason.AUTHORITY_REJECTED,
                    decision.reason or "authority firewall rejected preparation",
                )
            state = self._capture_prepared_state(
                backend, operation, fingerprint_key=record.preparation_fingerprint_key,
            )
            if operation.action.secret_reference is not None:
                try:
                    binding = backend.authentication.bind_secret(operation.action.secret_reference)
                except AuthenticationError as exc:
                    raise TwoPhaseCommitError(
                        CommitRejectedReason.SECRET_BINDING_UNAVAILABLE,
                        "secret generation could not be bound for prepared commit",
                    ) from exc
                # Private retained state only.  Neither the token response nor
                # the receipt carries a provider generation identifier.
                state["secret_binding"] = binding
            token = secrets.token_urlsafe(32)
            public = PreparedOperation(
                token=token,
                session_id=record.session_id,
                expires_at_ms=_now_ms() + ttl_ms,
                status=PreparationStatus.PREPARED,
                action_type=operation.action.type.value,
                origin=state["origin"],
                page_id=state["page_id"],
                state_fingerprint=state["state_fingerprint"],
                target_fingerprint=state.get("target_fingerprint"),
                operation_hash=self._operation_hash(operation, record.preparation_fingerprint_key),
                authority_policy_hash=envelope.digest,
                authority_decision=decision.to_dict(),
                mutation_epoch=(record.mutation_epoch if record.mutation_policy is not None else None),
                arbitration_policy=(record.mutation_policy.value if record.mutation_policy is not None else None),
            )
            record.preparations[token] = _PreparedRecord(
                public=public, operation=operation, state=state,
                signed_speculation_operation=_signed_speculation_operation,
                speculation_summary=(dict(_speculation_summary) if _speculation_summary is not None else None),
            )
            self._touch(record)
            return public

    def commit_operation(
        self,
        session_id: str,
        token: str,
        *,
        operation: Operation | None = None,
        agent_id: str | None = None,
        control_token: str | None = None,
    ) -> CommitResult:
        """Re-check a prepared record then dispatch its original operation once."""
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            self._require_identity(record)
            changed = self._refresh_external_mutation(record)
            prepared = record.preparations.get(token)
            if prepared is None:
                return CommitResult(record.session_id, token, False, CommitRejectedReason.PREPARATION_NOT_FOUND)
            if prepared.public.status is PreparationStatus.COMMITTED:
                return CommitResult(record.session_id, token, False, CommitRejectedReason.ALREADY_COMMITTED)
            if prepared.public.status is PreparationStatus.INVALIDATED:
                return CommitResult(record.session_id, token, False, CommitRejectedReason.PREPARATION_INVALIDATED)
            if _now_ms() >= prepared.public.expires_at_ms:
                prepared.public = replace(prepared.public, status=PreparationStatus.INVALIDATED)
                return CommitResult(record.session_id, token, False, CommitRejectedReason.PREPARATION_EXPIRED)
            if prepared.public.mutation_epoch is not None and prepared.public.mutation_epoch != record.mutation_epoch:
                prepared.public = replace(prepared.public, status=PreparationStatus.INVALIDATED)
                return CommitResult(record.session_id, token, False, CommitRejectedReason.MUTATION_EPOCH_CHANGED)
            if changed and record.mutation_policy is MutationArbitrationPolicy.FAIL_ON_EXTERNAL_MUTATION:
                prepared.public = replace(prepared.public, status=PreparationStatus.INVALIDATED)
                return CommitResult(record.session_id, token, False, CommitRejectedReason.MUTATION_EPOCH_CHANGED)
            if operation is not None and self._operation_hash(operation, record.preparation_fingerprint_key) != prepared.public.operation_hash:
                return CommitResult(record.session_id, token, False, CommitRejectedReason.PAYLOAD_CHANGED)

            backend = self._active_backend(record)
            current = self._capture_prepared_state(
                backend,
                prepared.operation,
                target_identity_key=prepared.state.get("target_identity_key"),
                scope_state_key=prepared.state.get("scope_state_key"),
                fingerprint_key=record.preparation_fingerprint_key,
            )
            reason = self._prepared_state_change_reason(prepared.state, current)
            if reason is not None:
                prepared.public = replace(prepared.public, status=PreparationStatus.INVALIDATED)
                return CommitResult(record.session_id, token, False, reason)
            envelope = record.authority_envelope
            if envelope is None or envelope.digest != prepared.public.authority_policy_hash:
                prepared.public = replace(prepared.public, status=PreparationStatus.INVALIDATED)
                return CommitResult(record.session_id, token, False, CommitRejectedReason.AUTHORITY_CHANGED)
            decision = self._firewall_decision(record, prepared.operation, backend)
            if not decision.authorized:
                prepared.public = replace(prepared.public, status=PreparationStatus.INVALIDATED)
                return CommitResult(record.session_id, token, False, CommitRejectedReason.AUTHORITY_REJECTED)

            secret_binding = prepared.state.get("secret_binding")
            if secret_binding is not None:
                # Validate the provider-side immutable generation immediately
                # before consumption.  The actual resolution used for fill is
                # still done by ``inject_bound`` at dispatch, which must make
                # the same atomic generation check.
                try:
                    from dingdongditch.authentication.secrets import SecretBinding
                    if not isinstance(secret_binding, SecretBinding):
                        raise ValueError("prepared secret binding is invalid")
                    secret_binding.validate()
                    backend.authentication.assert_secret_binding(
                        prepared.operation.action.secret_reference, secret_binding,
                    )
                except Exception:
                    prepared.public = replace(prepared.public, status=PreparationStatus.INVALIDATED)
                    return CommitResult(record.session_id, token, False, CommitRejectedReason.SECRET_BINDING_CHANGED)

            # Consume before dispatch.  A process/runtime failure after a
            # browser dispatch is inherently ambiguous, so allowing a retry
            # would violate at-most-once execution.
            prepared.public = replace(prepared.public, status=PreparationStatus.COMMITTED)
            record.active_commit_token = token
            record.active_transaction = {
                "status": PreparationStatus.COMMITTED.value,
                "token_id": hashlib.sha256(token.encode("utf-8")).hexdigest()[:24],
                "preparation_fingerprint": prepared.public.state_fingerprint,
                "operation_hash": prepared.public.operation_hash,
            }
            prior_speculation = record.active_speculation
            if prepared.speculation_summary is not None:
                record.active_speculation = dict(prepared.speculation_summary)
            try:
                executed = self.execute_operation(
                    record.session_id, prepared.operation,
                    agent_id=agent_id, control_token=control_token,
                    _prepared_target_identity=(
                        prepared.state.get("target_identity_key"),
                        prepared.state.get("target_identity"),
                    ) if prepared.state.get("target_identity_key") and prepared.state.get("target_identity") else None,
                    _prepared_secret_binding=secret_binding,
                    _signed_speculation_operation=prepared.signed_speculation_operation,
                )
            finally:
                record.active_commit_token = None
                record.active_transaction = None
                record.active_speculation = prior_speculation
            self._touch(record)
            return CommitResult(record.session_id, token, True, None, executed.receipt)

    def list_prepared_operations(self, session_id: str) -> tuple[PreparedOperation, ...]:
        record = self._access(session_id)
        with self._locked(record):
            return tuple(item.public for item in record.preparations.values())

    def receipt_chain(self, session_id: str) -> tuple[ExecutionReceipt, ...]:
        record = self._access(session_id)
        with self._locked(record):
            return tuple(record.receipt_chain)

    def receipt_chain_checkpoint(self, session_id: str) -> ReceiptChainCheckpoint:
        """Create an anchor the trusted host can retain outside runtime memory."""
        record = self._access(session_id)
        with self._locked(record):
            return make_receipt_chain_checkpoint(
                record.receipt_chain,
                session_id=record.session_id,
                timestamp_ms=_now_ms(),
                runtime_version=__import__("dingdongditch").__version__,
            )

    def mutation_status(self, session_id: str) -> dict[str, Any]:
        """Read-only bounded arbitration state; never exposes page handles."""
        record = self._access(session_id)
        with self._locked(record):
            return {
                "configured": record.mutation_policy is not None,
                "policy": record.mutation_policy.value if record.mutation_policy is not None else None,
                "mutation_epoch": record.mutation_epoch,
                "last_evidence": (record.mutation_last_evidence.to_dict() if record.mutation_last_evidence else None),
            }

    def attestation_material(
        self, session_id: str, checkpoint: ReceiptChainCheckpoint,
    ) -> dict[str, Any]:
        """Return bounded immutable material a host may submit to an attester."""
        record = self._access(session_id)
        with self._locked(record):
            checked = verify_receipt_chain_against_checkpoint(record.receipt_chain, checkpoint)
            if not checked.valid or checkpoint.session_id != record.session_id:
                raise StatefulSessionError("receipt chain does not satisfy supplied checkpoint", failure_kind=SessionFailureKind.OPERATION_REJECTED)
            last = record.receipt_chain[-1] if record.receipt_chain else None
            artifacts = [item for receipt in record.receipt_chain for item in (receipt.artifacts or [])]
            artifact_hash = hashlib.sha256(canonical_json_bytes(artifacts)).hexdigest() if artifacts else None
            return {
                "session_id": record.session_id,
                "plan_hash": (record.signed_plan_authority.plan_hash if record.signed_plan_authority else None),
                "signed_plan_reference": (public_signed_plan_reference(record.signed_plan_authority) if record.signed_plan_authority else None),
                "identity_reference": (identity_reference(record.identity_descriptor, record.identity_assertion)
                                       if record.identity_descriptor is not None and record.identity_assertion is not None else None),
                "authority_policy_hash": (record.authority_envelope.digest if record.authority_envelope else None),
                "receipt_chain_head": checked.head,
                "receipt_count": len(record.receipt_chain),
                "quorum_verdict": ((last.quorum_verification or {}).get("verdict") if last and last.quorum_verification else None),
                "artifact_manifest_hash": artifact_hash,
                "speculation_reference": (dict(last.speculation) if last and last.speculation else None),
                "runtime_version": __import__("dingdongditch").__version__,
                "browser": {
                    key: value for key, value in self._active_backend(record).browser_environment().items()
                    if key in {"engine", "channel", "browser_session_id", "context_id", "page_id"}
                },
            }

    def bind_signed_plan_authority(
        self,
        session_id: str,
        document: Any,
        authority: SignedPlanAuthority,
        verifier: TrustedPlanVerifier,
        *,
        agent_identity_id: str | None = None,
    ) -> dict[str, Any]:
        """Host-only installation of a verified exact-plan constraint.

        The verifier consumes the signed nonce only after all plan/session
        bindings match.  This method is deliberately absent from the
        agent-facing RPC/service contract.
        """
        if not isinstance(authority, SignedPlanAuthority) or not isinstance(verifier, TrustedPlanVerifier):
            raise ValueError("host must provide signed plan authority and trusted verifier")
        record = self._access(session_id)
        with self._locked(record):
            if record.signed_plan_authority is not None:
                raise StatefulSessionError("a signed plan is already installed", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            plan = getattr(document, "plan", document)
            if not isinstance(plan, ExecutionPlan):
                raise StatefulSessionError("signed plan document is invalid", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            try:
                plan.validate()
            except Exception as exc:
                raise StatefulSessionError("signed plan document is invalid", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED) from exc
            if plan.browser_config.describe() != record.config.describe():
                raise StatefulSessionError("signed plan browser configuration does not match session", failure_kind=SessionFailureKind.SESSION_CONFIG_MISMATCH)
            if record.authority_envelope is None or plan.authority_envelope != record.authority_envelope:
                raise StatefulSessionError("signed plan authority is not the host-installed envelope", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            current_identity_id = (
                record.identity_assertion.identity_id if record.identity_assertion is not None else None
            )
            if agent_identity_id is not None and agent_identity_id != current_identity_id:
                raise StatefulSessionError("host-supplied signed-plan identity does not match session identity", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            verified = verifier.verify(
                authority,
                document,
                authority_envelope_hash=record.authority_envelope.digest,
                session_scope=record.session_id,
                agent_identity_id=(
                    current_identity_id
                ),
                consume=True,
            )
            if not verified.valid:
                raise StatefulSessionError("signed plan verification failed", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            # The recomputation is intentional defence in depth: the signed
            # digest must name exactly the currently installed document.
            if authority.plan_hash != canonical_plan_hash(document):
                raise StatefulSessionError("signed plan hash does not match document", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            record.signed_plan_authority = authority
            record.signed_plan_operation_bytes = tuple(
                canonical_json_bytes(item.to_public_dict()) for item in plan.operations
            )
            # Keep a detached canonical copy.  Caller-owned mutable Operation
            # instances must never be able to edit an already authorized
            # graph after it has been verified.
            from dingdongditch.machine_contract import parse_speculative_plan
            record.signed_plan_speculations = {
                item.speculation_id: parse_speculative_plan(item.to_dict())
                for item in plan.speculative_plans
            }
            record.signed_plan_next_index = 0
            self._touch(record)
            return public_signed_plan_reference(authority)

    def bind_identity(
        self,
        session_id: str,
        assertion: IdentityAssertion,
        registry: IdentityRegistry,
    ) -> dict[str, Any]:
        """Host-only installation of a portable trusted identity assertion."""
        if not isinstance(assertion, IdentityAssertion) or not isinstance(registry, IdentityRegistry):
            raise ValueError("host must provide an identity assertion and trusted registry")
        record = self._access(session_id)
        with self._locked(record):
            if (
                record.signed_plan_authority is not None
                and record.signed_plan_authority.agent_identity_id is not None
                and assertion.identity_id != record.signed_plan_authority.agent_identity_id
            ):
                raise StatefulSessionError("identity is outside signed-plan scope", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            try:
                descriptor = registry.verify(assertion, controller_id=record.agent_id)
            except IdentityError as exc:
                raise StatefulSessionError("identity assertion was rejected", failure_kind=SessionFailureKind.OPERATION_REJECTED) from exc
            record.identity_registry = registry
            record.identity_assertion = assertion
            record.identity_descriptor = descriptor
            self._touch(record)
            return identity_reference(descriptor, assertion)

    def prepare_speculation(
        self,
        session_id: str,
        plan: SpeculativePlan,
        *,
        ttl_ms: int = 30_000,
        agent_id: str | None = None,
        control_token: str | None = None,
    ) -> BranchPreparation:
        """Statically prepare declared one-step branches without dispatching them."""
        if not isinstance(plan, SpeculativePlan):
            raise ValueError("plan must be a SpeculativePlan")
        plan.require_execution_binding()
        if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or not 100 <= ttl_ms <= 300_000:
            raise ValueError("ttl_ms must be between 100 and 300000")
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            self._require_identity(record)
            changed = self._refresh_external_mutation(record)
            # No live branch action is dispatched during this call; selection
            # and execution each re-check the epoch later.
            self._reject_mutation_if_policy_requires(record, changed=changed, operation_has_fresh_observation=True)
            # Defensively detach caller-owned nested Operation objects before
            # retaining the graph.  This also canonicalizes parser/default
            # representation prior to all comparisons below.
            from dingdongditch.machine_contract import parse_speculative_plan
            plan = parse_speculative_plan(plan.to_dict())
            if record.signed_plan_authority is not None:
                signed = record.signed_plan_speculations.get(plan.speculation_id)
                if signed is None or not hmac.compare_digest(
                    canonical_json_bytes(plan.to_dict()), canonical_json_bytes(signed.to_dict()),
                ):
                    raise StatefulSessionError("speculative graph is not exactly authorized by signed plan", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
                # Preparation happens before its parent is dispatched.  The
                # next ordinary signed step must be that exact signed parent.
                assert plan.parent_operation is not None
                self._require_signed_plan_operation(record, plan.parent_operation)
            backend = self._active_backend(record)
            for branch in plan.branches:
                decision = self._firewall_decision(record, branch.continuation, backend)
                if not decision.authorized:
                    raise StatefulSessionError("speculative continuation is rejected by authority firewall", failure_kind=SessionFailureKind.OPERATION_REJECTED)
            # A planner cannot accumulate unbounded retained branch graphs.
            now_ms = _now_ms()
            for old_token, old in tuple(record.speculations.items()):
                if old.consumed or now_ms >= old.public.expires_at_ms:
                    del record.speculations[old_token]
            if len(record.speculations) >= 16:
                raise StatefulSessionError("too many active speculative preparations", failure_kind=SessionFailureKind.OPERATION_REJECTED)
            token = secrets.token_urlsafe(32)
            prepared = BranchPreparation(
                token, record.session_id, plan.speculation_id, plan.parent_operation_id,
                record.control_epoch, (record.mutation_epoch if record.mutation_policy is not None else None),
                now_ms + ttl_ms, len(plan.branches),
            )
            record.speculations[token] = _SpeculationRecord(
                prepared, plan,
                parent_operation_hash=self._operation_hash(plan.parent_operation, record.preparation_fingerprint_key),
                signed_speculation_operation_bytes={
                    branch.branch_id: canonical_json_bytes(branch.continuation.to_public_dict())
                    for branch in plan.branches
                } if record.signed_plan_authority is not None else {},
            )
            self._touch(record)
            return prepared

    def select_speculative_branch(
        self,
        session_id: str,
        token: str,
        *,
        agent_id: str | None = None,
        control_token: str | None = None,
    ) -> BranchSelection:
        """Evaluate declared branch preconditions; select only one pass set."""
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            self._require_identity(record)
            item = record.speculations.get(token)
            if item is None or _now_ms() >= (item.public.expires_at_ms if item else 0):
                return BranchSelection(token, BranchSelectionStatus.STALE, None, ())
            if item.public.control_epoch != record.control_epoch:
                return BranchSelection(token, BranchSelectionStatus.STALE, None, ())
            self._refresh_external_mutation(record)
            if item.public.mutation_epoch is not None and item.public.mutation_epoch != record.mutation_epoch:
                return BranchSelection(token, BranchSelectionStatus.STALE, None, ())
            if not record.receipt_chain:
                return BranchSelection(token, BranchSelectionStatus.STALE, None, ())
            parent_receipt = record.receipt_chain[-1]
            parent_chain = getattr(parent_receipt, "receipt_chain", None)
            if (
                getattr(parent_receipt, "operation_id", None) != item.plan.parent_operation_id
                or getattr(parent_receipt, "verdict", None) != Verdict.VERIFIED
                or not isinstance(parent_chain, dict)
                or not isinstance(item.parent_operation_hash, str)
                or not hmac.compare_digest(str(parent_chain.get("operation_hash", "")), item.parent_operation_hash)
            ):
                return BranchSelection(token, BranchSelectionStatus.STALE, None, ())
            backend = self._active_backend(record)
            evidence: list[dict[str, Any]] = []
            matches: list[str] = []
            now = monotonic_ms()
            for branch in item.plan.branches:
                collector = EvidenceCollector(scope_id=f"speculation:{item.plan.speculation_id}:{branch.branch_id}", window_started_at_ms=now)
                results = evaluate_expectations(
                    backend=backend, expectations=list(branch.preconditions), collector=collector,
                    action_started_at_ms=now, verification_completed_at_ms=monotonic_ms(),
                    freshness=branch.continuation.freshness, post_network_payload={"records": []}, post_url=str(backend.page.url),
                )
                passed = bool(results) and all(result.result == "pass" for result in results)
                if passed:
                    matches.append(branch.branch_id)
                evidence.append({"branch_id": branch.branch_id, "passed": passed, "results": [result.to_dict() for result in results]})
            if len(matches) == 1:
                selection = BranchSelection(token, BranchSelectionStatus.SELECTED, matches[0], tuple(evidence))
            elif not matches:
                selection = BranchSelection(token, BranchSelectionStatus.NO_MATCH, None, tuple(evidence))
            else:
                selection = BranchSelection(token, BranchSelectionStatus.AMBIGUOUS, None, tuple(evidence))
            item.selected = selection
            self._touch(record)
            return selection

    def execute_selected_speculative_branch(
        self,
        session_id: str,
        token: str,
        *,
        agent_id: str | None = None,
        control_token: str | None = None,
    ) -> SpeculationExecutionResult:
        """Recheck a selected continuation and execute/prepare that stored action."""
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            self._require_identity(record)
            item = record.speculations.get(token)
            if item is None or item.selected is None or item.selected.status is not BranchSelectionStatus.SELECTED or item.selected.branch_id is None or item.consumed:
                raise StatefulSessionError("speculative branch is not uniquely selected", failure_kind=SessionFailureKind.OPERATION_REJECTED)
            if _now_ms() >= item.public.expires_at_ms or item.public.control_epoch != record.control_epoch:
                raise StatefulSessionError("speculative branch is stale", failure_kind=SessionFailureKind.MUTATION_CONFLICT)
            self._refresh_external_mutation(record)
            if item.public.mutation_epoch is not None and item.public.mutation_epoch != record.mutation_epoch:
                raise StatefulSessionError("speculative branch is stale after mutation", failure_kind=SessionFailureKind.MUTATION_CONFLICT)
            # Re-evaluate immediately before dispatch.  A mutation monitor is
            # intentionally conservative but cannot prove every JS listener
            # change; a branch selected from stale-looking page evidence must
            # not retain eligibility just because its visible target remains.
            original_branch_id = item.selected.branch_id
            refreshed = self.select_speculative_branch(
                session_id, token, agent_id=agent_id, control_token=control_token,
            )
            if refreshed.status is not BranchSelectionStatus.SELECTED or refreshed.branch_id != original_branch_id:
                raise StatefulSessionError("speculative branch eligibility changed", failure_kind=SessionFailureKind.MUTATION_CONFLICT)
            branch = next(candidate for candidate in item.plan.branches if candidate.branch_id == item.selected.branch_id)
            decision = self._firewall_decision(record, branch.continuation, self._active_backend(record))
            if not decision.authorized:
                raise StatefulSessionError("selected speculative branch is rejected by authority firewall", failure_kind=SessionFailureKind.OPERATION_REJECTED)
            item.consumed = True
            summary = {"speculation_id": item.plan.speculation_id, "branch_id": branch.branch_id, "selection": "selected"}
            signed_branch = item.signed_speculation_operation_bytes.get(branch.branch_id)
            if record.authority_envelope is not None and any(action in record.authority_envelope.require_preparation_for for action in self._governed_action_types(branch.continuation)):
                prepared = self.prepare_operation(
                    session_id, branch.continuation, agent_id=agent_id, control_token=control_token,
                    _signed_speculation_operation=signed_branch,
                    _speculation_summary=summary,
                )
                return SpeculationExecutionResult(item.selected, prepared_operation=prepared)
            record.active_speculation = summary
            try:
                executed = self.execute_operation(
                    session_id, branch.continuation, agent_id=agent_id, control_token=control_token,
                    _signed_speculation_operation=signed_branch,
                )
            finally:
                record.active_speculation = None
            return SpeculationExecutionResult(item.selected, operation_result=executed)

    def prepare_agent_handoff(
        self,
        session_id: str,
        *,
        agent_id: str | None,
        control_token: str | None,
        ttl_ms: int = 60_000,
        recipient_agent_id: str | None = None,
        recipient_identity_assertion: IdentityAssertion | None = None,
    ) -> AgentHandoffCheckpoint:
        if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or not 100 <= ttl_ms <= 300_000:
            raise ValueError("ttl_ms must be between 100 and 300000")
        self._validate_agent_id(recipient_agent_id)
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            self._require_identity(record)
            self._refresh_external_mutation(record)
            replacement_identity: AgentIdentity | None = None
            if recipient_identity_assertion is not None:
                if record.identity_registry is None:
                    raise StatefulSessionError("no trusted identity registry is installed", failure_kind=SessionFailureKind.OPERATION_REJECTED)
                try:
                    replacement_identity = record.identity_registry.verify(
                        recipient_identity_assertion, controller_id=recipient_agent_id,
                    )
                except IdentityError as exc:
                    raise StatefulSessionError("recipient identity assertion was rejected", failure_kind=SessionFailureKind.OPERATION_REJECTED) from exc
            backend = self._active_backend(record)
            transferable = bool(record.authority_envelope and record.authority_envelope.transfer_prepared_operations)
            pending: list[dict[str, Any]] = []
            for entry in record.preparations.values():
                if entry.public.status is PreparationStatus.PREPARED and not transferable:
                    entry.public = replace(entry.public, status=PreparationStatus.INVALIDATED)
                pending.append({
                    "action_type": entry.public.action_type,
                    "expires_at_ms": entry.public.expires_at_ms,
                    "status": entry.public.status.value,
                    "transferable": transferable,
                })
            pages = tuple(
                {
                    key: page.get(key)
                    for key in ("page_id", "current_url", "title", "active", "lifecycle_state", "opener_page_id")
                    if key in page
                }
                for page in backend.list_pages()
            )
            selected = next((page.get("page_id") for page in pages if page.get("active")), None)
            checkpoint = AgentHandoffCheckpoint(
                handoff_token=secrets.token_urlsafe(32),
                session_id=record.session_id,
                old_agent_id=record.agent_id,
                recipient_agent_id=recipient_agent_id,
                control_epoch=record.control_epoch,
                expires_at_ms=_now_ms() + ttl_ms,
                selected_page_id=selected,
                pages=pages,
                observation_checkpoint={
                    "page_id": str(backend.page_id),
                    "url": str(backend.page.url),
                    "captured_at_ms": _now_ms(),
                    "control_epoch": record.control_epoch,
                },
                authority=self._authority_summary(record),
                receipt_chain_head=record.receipt_chain_head,
                pending_preparations=tuple(pending),
                runtime_capabilities=("authority_firewall", "two_phase_commit", "quorum_verification", "receipt_chain", "hot_handoff"),
                identity=(identity_reference(record.identity_descriptor, record.identity_assertion)
                          if record.identity_descriptor is not None and record.identity_assertion is not None else None),
                mutation=(record.mutation_last_evidence.to_dict() if record.mutation_last_evidence else (
                    {"mutation_epoch": record.mutation_epoch, "policy": record.mutation_policy.value}
                    if record.mutation_policy is not None else None
                )),
                mutation_epoch=(record.mutation_epoch if record.mutation_policy is not None else None),
            )
            # There is one coherent transfer offer at a time.  Keeping stale
            # bearer offers alive made A→B→C races unnecessarily ambiguous.
            record.pending_handoffs.clear()
            record.pending_handoffs[checkpoint.handoff_token] = {
                "checkpoint": checkpoint, "claimed": False,
                "recipient_identity_assertion": recipient_identity_assertion,
                "recipient_identity_descriptor": replacement_identity,
            }
            self._touch(record)
            return checkpoint

    def claim_agent_handoff(
        self,
        session_id: str,
        handoff_token: str,
        new_agent_id: str,
        *,
        authenticated_agent_id: str | None = None,
    ) -> AgentHandoff:
        self._validate_agent_id(new_agent_id)
        record = self._access(session_id)
        with self._locked(record):
            pending = record.pending_handoffs.get(handoff_token)
            if pending is None:
                raise StatefulSessionError("handoff token is invalid", failure_kind=SessionFailureKind.HANDOFF_TOKEN_INVALID)
            checkpoint = pending["checkpoint"]
            if pending["claimed"]:
                raise StatefulSessionError("handoff token was already claimed", failure_kind=SessionFailureKind.HANDOFF_ALREADY_CLAIMED)
            if _now_ms() >= checkpoint.expires_at_ms:
                raise StatefulSessionError("handoff token expired", failure_kind=SessionFailureKind.HANDOFF_TOKEN_EXPIRED)
            if checkpoint.control_epoch != record.control_epoch or checkpoint.old_agent_id != record.agent_id:
                raise StatefulSessionError("handoff checkpoint is stale", failure_kind=SessionFailureKind.HANDOFF_CHECKPOINT_STALE)
            if checkpoint.mutation_epoch is not None:
                self._refresh_external_mutation(record)
                if checkpoint.mutation_epoch != record.mutation_epoch:
                    raise StatefulSessionError("handoff checkpoint is stale after browser mutation", failure_kind=SessionFailureKind.HANDOFF_CHECKPOINT_STALE)
            if checkpoint.recipient_agent_id is not None and checkpoint.recipient_agent_id != new_agent_id:
                raise StatefulSessionError("handoff belongs to a different recipient", failure_kind=SessionFailureKind.HANDOFF_RECIPIENT_REJECTED)
            if authenticated_agent_id is not None and authenticated_agent_id != new_agent_id:
                raise StatefulSessionError("authenticated caller does not match handoff recipient", failure_kind=SessionFailureKind.HANDOFF_RECIPIENT_REJECTED)
            if record.control_epoch >= (2**63 - 1):
                raise StatefulSessionError("control epoch is exhausted", failure_kind=SessionFailureKind.HANDOFF_CHECKPOINT_STALE)
            next_assertion = pending.get("recipient_identity_assertion")
            next_descriptor = pending.get("recipient_identity_descriptor")
            if next_assertion is None and record.identity_assertion is not None:
                try:
                    assert record.identity_registry is not None
                    # A controller-scoped assertion cannot silently survive a
                    # controller handoff. A host must issue a recipient-bound
                    # replacement assertion instead.
                    record.identity_registry.verify(record.identity_assertion, controller_id=new_agent_id)
                except IdentityError as exc:
                    raise StatefulSessionError("identity assertion does not authorize recipient controller", failure_kind=SessionFailureKind.HANDOFF_RECIPIENT_REJECTED) from exc
            if (
                record.signed_plan_authority is not None
                and record.signed_plan_authority.agent_identity_id is not None
            ):
                candidate_identity = (
                    next_assertion.identity_id if next_assertion is not None
                    else (record.identity_assertion.identity_id if record.identity_assertion is not None else None)
                )
                if candidate_identity != record.signed_plan_authority.agent_identity_id:
                    raise StatefulSessionError("handoff identity is outside signed-plan scope", failure_kind=SessionFailureKind.HANDOFF_RECIPIENT_REJECTED)
            pending["claimed"] = True
            record.agent_id = new_agent_id
            if next_assertion is not None:
                record.identity_assertion = next_assertion
                record.identity_descriptor = next_descriptor
            record.control_epoch += 1
            record.control_token = secrets.token_urlsafe(32)
            record.pending_handoffs.clear()
            self._touch(record)
            return AgentHandoff(
                session_id=record.session_id,
                agent_id=new_agent_id,
                control_epoch=record.control_epoch,
                control_token=record.control_token,
                receipt_chain_head=record.receipt_chain_head,
                authority=self._authority_summary(record),
                identity=(identity_reference(record.identity_descriptor, record.identity_assertion)
                          if record.identity_descriptor is not None and record.identity_assertion is not None else None),
            )

    def execute_operation(
        self,
        session_id: str,
        operation: Operation,
        *,
        observation_reference: ObservationReference | None = None,
        agent_id: str | None = None,
        control_token: str | None = None,
        _prepared_target_identity: tuple[str, str] | None = None,
        _prepared_secret_binding: Any | None = None,
        _prepared_commit: bool = False,
        _signed_speculation_operation: bytes | None = None,
    ) -> SessionOperationResult:
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            self._require_identity(record)
            self._require_signed_plan_operation(
                record, operation, signed_speculation_operation=_signed_speculation_operation,
            )
            changed = self._refresh_external_mutation(record)
            if (
                observation_reference is not None
                and observation_reference.control_epoch is not None
                and observation_reference.control_epoch != record.control_epoch
            ):
                raise StatefulSessionError(
                    "observation was created under a stale control epoch",
                    failure_kind=SessionFailureKind.OPERATION_REJECTED,
                )
            if observation_reference is not None and observation_reference.mutation_epoch is not None and observation_reference.mutation_epoch != record.mutation_epoch:
                raise StatefulSessionError("observation was created before a browser mutation", failure_kind=SessionFailureKind.MUTATION_CONFLICT)
            self._reject_mutation_if_policy_requires(
                record, changed=changed, operation_has_fresh_observation=(observation_reference is not None),
            )
            backend = self._active_backend(record)
            governed_operation = operation
            if observation_reference is not None and observation_reference.provenance:
                governed_operation = replace(
                    operation,
                    provenance=merge_provenance(tuple(operation.provenance), tuple(observation_reference.provenance)),
                )
            dispatch_operation = governed_operation
            if _prepared_target_identity is not None or _prepared_secret_binding is not None:
                # Private in-process binding: never part of the public
                # operation/plan/receipt schema and unavailable to planners.
                dispatch_operation = replace(operation)
                setattr(dispatch_operation, "_transaction_target_identity", _prepared_target_identity)
            if _prepared_secret_binding is not None:
                setattr(dispatch_operation, "_transaction_secret_binding", _prepared_secret_binding)
            before_pages = backend.list_pages()
            before_dialogs = backend.list_dialog_history()
            started = _now_ms()
            decision = None
            if (
                record.authority_envelope is not None
                and any(action_type in record.authority_envelope.require_preparation_for for action_type in self._governed_action_types(operation))
                and record.active_commit_token is None
            ):
                locator = operation.action.locator.describe() if operation.action.locator else None
                receipt = _failed_receipt(
                    operation=operation,
                    started_at=started,
                    collector=EvidenceCollector(scope_id=operation.operation_id, window_started_at_ms=started),
                    locator_desc=locator,
                    execution_status="preparation_required",
                    execution_error="host policy requires a valid prepared commit token",
                    failure_kind=CommitRejectedReason.PREPARATION_REQUIRED.value.lower(),
                    browser=backend.browser_environment(),
                    backend_identity=backend.backend_identity,
                    browser_identity=backend.browser_identity,
                    action_evidence={"transaction": {"status": "REJECTED", "reason": CommitRejectedReason.PREPARATION_REQUIRED.value}, "dispatch_attempted": False},
                    verdict=Verdict.NOT_VERIFIED,
                )
            elif record.authority_envelope is not None:
                decision = self._firewall_decision(record, governed_operation, backend)
                if not decision.authorized:
                    locator = operation.action.locator.describe() if operation.action.locator else None
                    rejected = _failed_receipt(
                        operation=operation,
                        started_at=started,
                        collector=EvidenceCollector(scope_id=operation.operation_id, window_started_at_ms=started),
                        locator_desc=locator,
                        execution_status="authority_rejected",
                        execution_error=decision.reason or "operation rejected by authority firewall",
                        failure_kind=decision.outcome.value.lower(),
                        browser=backend.browser_environment(),
                        backend_identity=backend.backend_identity,
                        browser_identity=backend.browser_identity,
                        action_evidence={"authority": decision.to_dict(), "dispatch_attempted": False},
                        verdict=Verdict.NOT_VERIFIED,
                    )
                    receipt = replace(rejected, _sealed=False, authority_decision=decision.to_dict()).seal()
                else:
                    receipt = _execute_operation(
                        dispatch_operation,
                        backend=backend,
                        browser_config=record.config,
                        observation_reference=observation_reference,
                    )
                    receipt = replace(receipt, _sealed=False, authority_decision=decision.to_dict()).seal()
                    # A dispatched request can cause an external side effect
                    # even if DingDong verification subsequently fails.  Count
                    # dispatch, not a favourable verdict, so retry loops
                    # cannot escape host budgets.
                    dispatched_count, side_effect_count = self._receipt_dispatch_counts(
                        receipt, record.authority_envelope, operation,
                    )
                    if dispatched_count:
                        record.authority_action_count += dispatched_count
                        record.authority_side_effect_count += side_effect_count
                    if receipt.action_started_at_ms is not None:
                        try:
                            post_dispatch_url = backend.scoped_action_url(
                                frame=operation.action.frame,
                                frame_path=operation.action.frame_path,
                            )
                        except Exception:
                            post_dispatch_url = backend.page.url
                        if not isinstance(post_dispatch_url, str):
                            post_dispatch_url = backend.page.url
                        post_navigation = AuthorityFirewall().decide(
                            operation,
                            record.authority_envelope,
                            current_url=post_dispatch_url,
                            effective_url=post_dispatch_url,
                            now_ms=_now_ms(),
                            # The navigation has already consumed its budget.
                            # Reusing the post-dispatch count here would reject
                            # every final-origin check at an exactly-full
                            # budget, turning a valid first navigation into a
                            # misleading post-navigation policy failure.
                            action_count=max(0, record.authority_action_count - 1),
                            side_effect_count=max(0, record.authority_side_effect_count - int(
                                operation.action.type.value in record.authority_envelope.irreversible_action_types
                            )),
                        )
                        if not post_navigation.authorized:
                            receipt = replace(
                                receipt,
                                _sealed=False,
                                verdict=Verdict.NOT_VERIFIED,
                                execution_status=(
                                    "post_navigation_authority_rejected"
                                    if operation.action.type.value == "navigate"
                                    else "post_dispatch_authority_rejected"
                                ),
                                execution_error=post_navigation.reason or "dispatch reached a denied origin",
                                failure_kind=(
                                    "post_navigation_" if operation.action.type.value == "navigate" else "post_dispatch_"
                                ) + post_navigation.outcome.value.lower(),
                                authority_decision=post_navigation.to_dict(),
                                action_evidence={
                                    **dict(receipt.action_evidence or {}),
                                    (
                                        "post_navigation_authority"
                                        if operation.action.type.value == "navigate"
                                        else "post_dispatch_authority"
                                    ): post_navigation.to_dict(),
                                },
                            ).seal()
            else:
                receipt = _execute_operation(
                    dispatch_operation,
                    backend=backend,
                    browser_config=record.config,
                    observation_reference=observation_reference,
                )
            if record.active_transaction is not None:
                receipt = replace(receipt, _sealed=False, transaction=dict(record.active_transaction)).seal()
            receipt = replace(receipt, _sealed=False, control_epoch=record.control_epoch).seal()
            if record.signed_plan_authority is not None:
                receipt = replace(
                    receipt, _sealed=False,
                    signed_plan=public_signed_plan_reference(record.signed_plan_authority),
                ).seal()
            if record.identity_descriptor is not None and record.identity_assertion is not None:
                receipt = replace(
                    receipt, _sealed=False,
                    identity=identity_reference(record.identity_descriptor, record.identity_assertion),
                ).seal()
            if record.active_speculation is not None:
                receipt = replace(receipt, _sealed=False, speculation=dict(record.active_speculation)).seal()
            if record.mutation_policy is not None and record.mutation_last_evidence is not None:
                receipt = replace(
                    receipt, _sealed=False,
                    mutation_arbitration=record.mutation_last_evidence.to_dict(),
                ).seal()
            receipt = chain_receipt(
                receipt,
                previous_receipt_hash=record.receipt_chain_head,
                operation_hash=self._operation_hash(operation, record.preparation_fingerprint_key),
                session_id=record.session_id,
            )
            record.receipt_chain.append(receipt)
            record.receipt_chain_head = receipt.receipt_chain["receipt_hash"]
            # A plan step is consumed only after the runtime attempted a
            # browser dispatch.  Prepare is intentionally non-consuming;
            # failed firewall checks are non-dispatches and remain bounded by
            # the pre-existing policy budget rather than silently advancing a
            # signed plan.
            if (
                record.signed_plan_authority is not None
                and _signed_speculation_operation is None
                and receipt.action_started_at_ms is not None
            ):
                record.signed_plan_next_index += 1
            if record.mutation_policy is not None and receipt.action_started_at_ms is not None:
                self._record_agent_mutation(record, ambiguous=True)
                self._advance_speculations_after_parent(record, operation, receipt)
            finished = _now_ms()
            alive = backend.is_started
            if not alive:
                record.status = PublicSessionStatus.TERMINAL
            self._touch(record)
            after_pages = backend.list_pages() if alive else tuple()
            after_dialogs = backend.list_dialog_history() if alive else tuple()
            before_page_ids = {page["page_id"] for page in before_pages}
            new_pages = [page for page in after_pages if page["page_id"] not in before_page_ids]
            new_dialogs = list(after_dialogs[len(before_dialogs):])
            events = {
                "new_pages": new_pages,
                "dialogs": new_dialogs,
                "navigation_occurred": receipt.navigation_occurred,
                "active_page_id_before": next((p["page_id"] for p in before_pages if p.get("active")), None),
                "active_page_id_after": next((p["page_id"] for p in after_pages if p.get("active")), None),
                "download": (receipt.action_evidence or {}).get("download"),
            }
            return SessionOperationResult(
                session_id=record.session_id,
                operation_id=operation.operation_id,
                receipt=receipt,
                verdict=receipt.verdict.value,
                recoverable=alive,
                terminal=not alive,
                page_state=tuple(after_pages),
                events=events,
                started_at_ms=started,
                finished_at_ms=finished,
            )

    def execute_plan(self, session_id: str, plan: ExecutionPlan, *, agent_id: str | None = None, control_token: str | None = None) -> SessionPlanResult:
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            backend = self._active_backend(record)
            if plan.browser_config.describe() != record.config.describe():
                raise StatefulSessionError(
                    "plan browser configuration does not match the retained session",
                    failure_kind=SessionFailureKind.SESSION_CONFIG_MISMATCH,
                )
            if record.authority_envelope is not None:
                if plan.authority_envelope != record.authority_envelope:
                    raise StatefulSessionError(
                        "governed session plan authority does not match the host-installed envelope",
                        failure_kind=SessionFailureKind.OPERATION_REJECTED,
                    )
                raise StatefulSessionError(
                    "governed sessions execute ordered plan operations through the session authority boundary",
                    failure_kind=SessionFailureKind.OPERATION_REJECTED,
                )
            receipt = _execute_plan(plan, backend=backend)
            alive = backend.is_started
            if not alive:
                record.status = PublicSessionStatus.TERMINAL
            self._touch(record)
            return SessionPlanResult(
                session_id=record.session_id,
                receipt=receipt,
                recoverable=alive,
                terminal=not alive,
                page_state=tuple(backend.list_pages() if alive else ()),
            )

    def inspect_pages(self, session_id: str) -> tuple[dict[str, Any], ...]:
        record = self._access(session_id)
        with self._locked(record):
            pages = tuple(self._active_backend(record).list_pages())
            self._touch(record)
            return pages

    def select_page(self, session_id: str, page_id: str, *, agent_id: str | None = None, control_token: str | None = None) -> dict[str, Any]:
        record = self._access(session_id)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            backend = self._active_backend(record)
            self._select_backend_page(backend, page_id)
            self._touch(record)
            return next(page for page in backend.list_pages() if page["page_id"] == page_id)

    def inspect_dialogs(self, session_id: str) -> tuple[dict[str, Any], ...]:
        record = self._access(session_id)
        with self._locked(record):
            dialogs = tuple(self._active_backend(record).list_dialog_history())
            self._touch(record)
            return dialogs

    def close_session(self, session_id: str, *, agent_id: str | None = None, control_token: str | None = None) -> SessionInfo:
        record = self._require_record(session_id, require_open=False)
        if record.status in (PublicSessionStatus.CLOSED, PublicSessionStatus.EXPIRED):
            return self._info(record)
        with self._locked(record):
            self._require_control(record, agent_id=agent_id, control_token=control_token)
            self._close_record(record, PublicSessionStatus.CLOSED)
            info = self._info(record)
            if record.cleanup_errors:
                raise StatefulSessionError(
                    "browser session closed with cleanup failures",
                    failure_kind=SessionFailureKind.CLEANUP_FAILURE,
                )
            return info

    def cleanup_expired_sessions(self) -> tuple[str, ...]:
        now = _now_ms()
        cleaned: list[str] = []
        with self._registry_lock:
            records = list(self._records.values())
        for record in records:
            if record.status != PublicSessionStatus.OPEN:
                continue
            if now - record.last_activity_at_ms < record.idle_timeout_ms:
                continue
            with self._locked(record):
                if record.status == PublicSessionStatus.OPEN and now - record.last_activity_at_ms >= record.idle_timeout_ms:
                    self._close_record(record, PublicSessionStatus.EXPIRED)
                    cleaned.append(record.session_id)
        return tuple(cleaned)

    @staticmethod
    def _operation_hash(operation: Operation, fingerprint_key: bytes) -> str:
        """Bind the exact proposal without making public hashes guessable.

        ``Action.text`` is normally ordinary content, but hosts must not turn
        a caller mistake into a public low-entropy credential oracle.  The
        opaque per-session HMAC still detects commit substitution and is
        chained as a receipt fact without persisting the payload or key.
        """
        return hmac.new(
            fingerprint_key, canonical_json_bytes(operation.to_public_dict()), hashlib.sha256,
        ).hexdigest()

    def _capture_prepared_state(
        self,
        backend: PlaywrightBackend,
        operation: Operation,
        *,
        target_identity_key: str | None = None,
        scope_state_key: str | None = None,
        fingerprint_key: bytes,
    ) -> dict[str, Any]:
        """Capture material state only; this is not a claim of server rollback."""
        page = backend.page
        page_id = str(backend.page_id)
        try:
            state_key = scope_state_key or "__dingdongditch_transaction_scope_" + secrets.token_hex(16)
            scoped = backend.transaction_scope_state(
                frame=operation.action.frame,
                frame_path=operation.action.frame_path,
                state_key=state_key,
            )
        except Exception as exc:
            raise TwoPhaseCommitError(
                CommitRejectedReason.PREPARED_STATE_CHANGED,
                "material browser state could not be captured",
            ) from exc
        # Lightweight dummy backends from older integrations need not expose
        # the optional scoped-state helper.  Their top-level page snapshot is
        # retained for compatibility; the real backend always takes the path
        # above and never authorizes an unresolved frame origin.
        if not isinstance(scoped, dict) or not isinstance(scoped.get("url"), str):
            scoped = None
        url = str(scoped["url"] if scoped is not None else page.url)
        origin = ""
        try:
            from urllib.parse import urlsplit
            split = urlsplit(url)
            origin = f"{split.scheme.lower()}://{split.netloc.lower()}" if split.scheme and split.netloc else ""
        except Exception:
            origin = ""
        target: dict[str, Any] | None = None
        target_identity: str | None = None
        if operation.action.locator is not None:
            target = backend.read_element_state(
                operation.action.locator,
                frame=operation.action.frame,
                frame_path=operation.action.frame_path,
            )
            if target.get("ambiguous") or not target.get("exists"):
                raise TwoPhaseCommitError(
                    CommitRejectedReason.PREPARED_STATE_CHANGED,
                    "prepared target is not uniquely available",
                )
            identity_key = target_identity_key or "__dingdongditch_prepared_" + secrets.token_hex(16)
            try:
                target_identity = backend.transaction_target_identity(
                    operation.action.locator,
                    frame=operation.action.frame,
                    frame_path=operation.action.frame_path,
                    identity_key=identity_key,
                )
                # Lightweight test/dummy backends predating this optional
                # capability may return a mock/non-string.  Do not serialize
                # it; real Playwright backends always return a non-empty str.
                if not isinstance(target_identity, str) or not target_identity:
                    target_identity = None
            except Exception as exc:
                raise TwoPhaseCommitError(
                    CommitRejectedReason.PREPARED_STATE_CHANGED,
                    "prepared target identity could not be established",
                ) from exc
        try:
            dom_identity = scoped if scoped is not None else page.evaluate(
                """() => ({url: location.href, readyState: document.readyState,
                    title: document.title, root: document.documentElement.outerHTML})"""
            )
        except Exception as exc:
            raise TwoPhaseCommitError(
                CommitRejectedReason.PREPARED_STATE_CHANGED,
                "material browser state could not be captured",
            ) from exc
        # Resolver traces carry monotonic timing diagnostics. They prove the
        # resolution path in ordinary receipts but are not material target
        # identity and would make a no-change commit falsely stale.
        target_material = (
            {key: value for key, value in target.items() if key != "target_resolution"}
            if target is not None else None
        )
        target_fingerprint = (
            hmac.new(fingerprint_key, canonical_json_bytes({"snapshot": target_material, "identity": target_identity}), hashlib.sha256).hexdigest()
            if target_material is not None else None
        )
        state_payload = {
            "page_id": page_id,
            "url": url,
            "origin": origin,
            "dom": dom_identity,
            "target": target_material,
            "target_identity": target_identity,
            # A popup/new-tab, opener relationship, or lifecycle change can
            # alter the consequence of a click while leaving the selected DOM
            # unchanged.  Bind compact registry facts without retaining page
            # handles or content.
            "pages": sorted(
                [
                    {
                        key: item.get(key)
                        for key in ("page_id", "current_url", "lifecycle_state", "active", "opener_page_id")
                    }
                    for item in backend.list_pages()
                    if isinstance(item, dict)
                ],
                key=lambda item: str(item.get("page_id", "")),
            ),
        }
        return {
            "page_id": page_id,
            "url": url,
            "origin": origin,
            "target_fingerprint": target_fingerprint,
            "state_fingerprint": hmac.new(fingerprint_key, canonical_json_bytes(state_payload), hashlib.sha256).hexdigest(),
            # Private process-local state only.  It never enters the public
            # prepared record, receipts, or handoff checkpoint.
            "target_identity_key": target_identity_key or identity_key if target is not None else None,
            "target_identity": target_identity,
            "scope_state_key": state_key if scoped is not None else None,
        }

    @staticmethod
    def _prepared_state_change_reason(before: dict[str, Any], after: dict[str, Any]) -> CommitRejectedReason | None:
        if before["page_id"] != after["page_id"]:
            return CommitRejectedReason.PAGE_CHANGED
        if before["origin"] != after["origin"]:
            return CommitRejectedReason.ORIGIN_CHANGED
        if before.get("target_fingerprint") != after.get("target_fingerprint"):
            return CommitRejectedReason.TARGET_CHANGED
        if before["state_fingerprint"] != after["state_fingerprint"]:
            return CommitRejectedReason.PREPARED_STATE_CHANGED
        return None

    @staticmethod
    def _receipt_dispatch_counts(
        receipt: ExecutionReceipt,
        envelope: AuthorityEnvelope,
        operation: Operation,
    ) -> tuple[int, int]:
        """Conservatively account for every runtime dispatch represented in a receipt."""
        guard = (receipt.action_evidence or {}).get("guard")
        branch_actions = guard.get("branch_actions") if isinstance(guard, dict) else None
        if isinstance(branch_actions, list):
            # An entry is emitted immediately after each backend.dispatch call;
            # charge it even when its result is uncertain rather than granting
            # a retry budget after a transport/browser failure.
            types = [item.get("action_type") for item in branch_actions if isinstance(item, dict)]
            return len(types), sum(action_type in envelope.irreversible_action_types for action_type in types)
        if receipt.action_started_at_ms is None:
            return 0, 0
        action_type = operation.action.type.value
        return 1, int(action_type in envelope.irreversible_action_types)

    @staticmethod
    def _governed_action_types(operation: Operation) -> tuple[str, ...]:
        """Return every action that a finite guard could physically dispatch."""
        guard = operation.guard
        if guard is None or guard.is_legacy_target_absent:
            return (operation.action.type.value,)
        actions = [action.type.value for branch in guard.branches for action in branch.execute]
        if guard.otherwise is not None:
            actions.extend(action.type.value for action in guard.otherwise)
        return tuple(actions)

    def _firewall_decision(
        self,
        record: _SessionRecord,
        operation: Operation,
        backend: PlaywrightBackend,
    ) -> Any:
        """Authorize every possible guarded action and reserve worst-case budget.

        Branching guards are deterministic, but their selected branch is page
        state controlled.  Evaluating only the outer placeholder action would
        let a planner smuggle a denied upload or irreversible action through a
        permitted primitive.  We therefore evaluate all declared branch
        actions before dispatch and apply conservative count inputs.
        """
        envelope = record.authority_envelope
        assert envelope is not None
        guard = operation.guard
        if guard is None or guard.is_legacy_target_absent:
            candidate_actions = (operation.action,)
            max_actions = 1
            max_side_effects = int(operation.action.type.value in envelope.irreversible_action_types)
        else:
            alternatives = [tuple(branch.execute) for branch in guard.branches]
            if guard.otherwise is not None:
                alternatives.append(tuple(guard.otherwise))
            candidate_actions = tuple(action for actions in alternatives for action in actions)
            max_actions = max((len(actions) for actions in alternatives), default=0)
            max_side_effects = max(
                (sum(action.type.value in envelope.irreversible_action_types for action in actions) for actions in alternatives),
                default=0,
            )
            if not candidate_actions:
                # A branch with no dispatch still has no authority to perform
                # the operation's outer action; use it solely as a governed
                # state check.
                candidate_actions = (operation.action,)
                max_actions = 0
        firewall = AuthorityFirewall()
        first = None
        for action in candidate_actions:
            candidate = replace(operation, action=action, guard=None)
            try:
                scope_url = backend.scoped_action_url(
                    frame=action.frame,
                    frame_path=action.frame_path,
                )
            except Exception:
                scope_url = ""
            if not isinstance(scope_url, str):
                scope_url = backend.page.url if not (action.frame is not None or action.frame_path) else ""
            decision = firewall.decide(
                candidate,
                envelope,
                current_url=scope_url,
                now_ms=_now_ms(),
                action_count=record.authority_action_count + max(0, max_actions - 1),
                side_effect_count=record.authority_side_effect_count + max(0, max_side_effects - 1),
            )
            if first is None:
                first = decision
            if not decision.authorized:
                return decision
        assert first is not None
        return first

    @staticmethod
    def _validate_agent_id(agent_id: str | None) -> None:
        if agent_id is None:
            return
        if not isinstance(agent_id, str) or not agent_id or len(agent_id) > 128 or any(ch.isspace() for ch in agent_id):
            raise ValueError("agent_id must be a non-empty token up to 128 characters")

    def _require_control(self, record: _SessionRecord, *, agent_id: str | None, control_token: str | None) -> None:
        if record.agent_id is None:
            return  # legacy sessions deliberately retain their pre-handoff API.
        if not isinstance(agent_id, str) or agent_id != record.agent_id:
            raise StatefulSessionError("control lease belongs to a different agent", failure_kind=SessionFailureKind.CONTROL_LEASE_REJECTED)
        if not isinstance(control_token, str) or record.control_token is None or not hmac.compare_digest(control_token, record.control_token):
            raise StatefulSessionError("control lease token is invalid", failure_kind=SessionFailureKind.CONTROL_LEASE_REJECTED)

    @staticmethod
    def _require_identity(record: _SessionRecord) -> None:
        if record.identity_assertion is None:
            return
        if record.identity_registry is None:
            raise StatefulSessionError("identity trust registry is unavailable", failure_kind=SessionFailureKind.OPERATION_REJECTED)
        try:
            descriptor = record.identity_registry.verify(record.identity_assertion, controller_id=record.agent_id)
        except IdentityError as exc:
            raise StatefulSessionError("identity assertion is not valid for this execution", failure_kind=SessionFailureKind.OPERATION_REJECTED) from exc
        if (
            record.signed_plan_authority is not None
            and record.signed_plan_authority.agent_identity_id is not None
            and descriptor.identity_id != record.signed_plan_authority.agent_identity_id
        ):
            raise StatefulSessionError("session identity does not satisfy signed-plan scope", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
        record.identity_descriptor = descriptor

    def record_external_mutation(
        self,
        session_id: str,
        *,
        actor: MutationActor = MutationActor.EXTERNAL_UNKNOWN,
    ) -> MutationEvidence:
        """Trusted-host report for detectable manual/external interaction.

        This never accepts a planner-provided actor.  Browser-detected changes
        are always ``EXTERNAL_UNKNOWN``; only this host-only API may record a
        human attribution.
        """
        if actor not in {MutationActor.HUMAN, MutationActor.EXTERNAL_UNKNOWN}:
            raise ValueError("external mutation actor must be human or external_unknown")
        record = self._access(session_id)
        with self._locked(record):
            if record.mutation_policy is None:
                raise StatefulSessionError("mutation arbitration is not configured", failure_kind=SessionFailureKind.MUTATION_CONFLICT)
            return self._advance_mutation_epoch(record, actor=actor, source="trusted_host")

    def _initialize_mutation_monitor(self, record: _SessionRecord) -> None:
        if record.mutation_policy is None or record.mutation_scope_key is None:
            return
        backend = self._active_backend(record)
        state = backend.transaction_scope_state(state_key=record.mutation_scope_key)
        record.mutation_state_fingerprint = self._mutation_state_fingerprint(record, state)

    def _refresh_external_mutation(self, record: _SessionRecord) -> bool:
        if record.mutation_policy is None or record.mutation_scope_key is None:
            return False
        backend = self._active_backend(record)
        try:
            state = backend.transaction_scope_state(state_key=record.mutation_scope_key)
            current = self._mutation_state_fingerprint(record, state)
        except Exception as exc:
            # A monitor that cannot observe its browser scope is not evidence
            # of freshness. Treat it as external/unknown and fail closed.
            self._advance_mutation_epoch(record, actor=MutationActor.EXTERNAL_UNKNOWN, source="browser_state")
            return True
        before = record.mutation_state_fingerprint
        record.mutation_state_fingerprint = current
        if before is not None and not hmac.compare_digest(before, current):
            self._advance_mutation_epoch(record, actor=MutationActor.EXTERNAL_UNKNOWN, source="browser_state")
            return True
        return False

    @staticmethod
    def _mutation_state_fingerprint(record: _SessionRecord, state: dict[str, Any]) -> str:
        material = {
            key: state.get(key)
            for key in ("url", "readyState", "title", "root", "history_length", "history_state", "controls", "document_token", "mutation_count")
        }
        return hmac.new(record.preparation_fingerprint_key, canonical_json_bytes(material), hashlib.sha256).hexdigest()

    def _advance_mutation_epoch(
        self, record: _SessionRecord, *, actor: MutationActor, source: str,
    ) -> MutationEvidence:
        if record.mutation_epoch >= (2**63 - 1):
            raise StatefulSessionError("mutation epoch is exhausted", failure_kind=SessionFailureKind.MUTATION_CONFLICT)
        record.mutation_epoch += 1
        invalidated = False
        for prepared in record.preparations.values():
            if prepared.public.status is PreparationStatus.PREPARED:
                prepared.public = replace(prepared.public, status=PreparationStatus.INVALIDATED)
                invalidated = True
        assert record.mutation_policy is not None
        evidence = MutationEvidence(record.mutation_epoch, actor, record.mutation_policy, _now_ms(), source, invalidated)
        record.mutation_last_evidence = evidence
        record.mutation_events.append(evidence)
        del record.mutation_events[:-16]
        return evidence

    def _record_agent_mutation(self, record: _SessionRecord, *, ambiguous: bool) -> None:
        if record.mutation_policy is None:
            return
        # Browser page/script effects concurrent with dispatch cannot be
        # reliably partitioned from an agent-caused mutation. Do not claim the
        # actor is known in that case.
        actor = MutationActor.EXTERNAL_UNKNOWN if ambiguous else MutationActor.AGENT
        self._advance_mutation_epoch(record, actor=actor, source="agent_dispatch")
        try:
            self._initialize_mutation_monitor(record)
        except Exception:
            pass

    def _advance_speculations_after_parent(
        self, record: _SessionRecord, operation: Operation, receipt: ExecutionReceipt,
    ) -> None:
        """Carry a branch preparation across its own exact parent dispatch.

        A speculative continuation is intentionally prepared before the
        parent operation changes browser state.  The parent itself must not
        invalidate that graph; any other mutation still does.  We only carry
        a record forward after the chained receipt proves that exact declared
        parent was dispatched and verified.
        """
        if receipt.verdict is not Verdict.VERIFIED or receipt.action_started_at_ms is None:
            return
        observed_hash = self._operation_hash(operation, record.preparation_fingerprint_key)
        for item in record.speculations.values():
            if item.consumed or item.parent_operation_hash is None:
                continue
            if not hmac.compare_digest(item.parent_operation_hash, observed_hash):
                continue
            if item.public.mutation_epoch is not None:
                item.public = replace(item.public, mutation_epoch=record.mutation_epoch)

    @staticmethod
    def _reject_mutation_if_policy_requires(
        record: _SessionRecord, *, changed: bool, operation_has_fresh_observation: bool,
    ) -> None:
        if not changed or record.mutation_policy is None:
            return
        if record.mutation_policy is MutationArbitrationPolicy.FAIL_ON_EXTERNAL_MUTATION:
            raise StatefulSessionError("external browser mutation requires host intervention", failure_kind=SessionFailureKind.MUTATION_CONFLICT)
        # REQUIRE_REPREPARE and HUMAN_PRIORITY do not mean a stale planner can
        # keep dispatching merely because it omitted an ObservationReference.
        # A new observation made *after* this epoch advance is the only
        # deterministic recovery path for governed operations.
        if not operation_has_fresh_observation:
            raise StatefulSessionError("browser mutation requires a new observation", failure_kind=SessionFailureKind.MUTATION_CONFLICT)

    @staticmethod
    def _require_signed_plan_operation(
        record: _SessionRecord,
        operation: Operation,
        *,
        signed_speculation_operation: bytes | None = None,
    ) -> None:
        authority = record.signed_plan_authority
        if authority is None:
            if signed_speculation_operation is not None:
                raise StatefulSessionError("speculative authorization is unavailable without a signed plan", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            return
        current = _now_ms()
        if current < authority.issued_at_ms or current >= authority.expires_at_ms:
            raise StatefulSessionError("signed plan authority is not currently valid", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
        candidate = canonical_json_bytes(operation.to_public_dict())
        if signed_speculation_operation is not None:
            if not hmac.compare_digest(candidate, signed_speculation_operation):
                raise StatefulSessionError("operation does not match selected signed speculative branch", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
            return
        if record.signed_plan_next_index >= len(record.signed_plan_operation_bytes):
            raise StatefulSessionError("signed plan has no remaining authorized operation", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)
        expected = record.signed_plan_operation_bytes[record.signed_plan_next_index]
        if not hmac.compare_digest(candidate, expected):
            raise StatefulSessionError("operation does not match the next signed plan step", failure_kind=SessionFailureKind.SIGNED_PLAN_REJECTED)

    @staticmethod
    def _authority_summary(record: _SessionRecord) -> dict[str, Any] | None:
        if record.authority_envelope is None:
            return None
        return {
            "policy_id": record.authority_envelope.policy_id,
            "policy_hash": record.authority_envelope.digest,
            "remaining_action_count": (
                max(0, record.authority_envelope.max_action_count - record.authority_action_count)
                if record.authority_envelope.max_action_count is not None else None
            ),
            "remaining_side_effect_count": (
                max(0, record.authority_envelope.max_side_effect_count - record.authority_side_effect_count)
                if record.authority_envelope.max_side_effect_count is not None else None
            ),
        }

    def _info(self, record: _SessionRecord, *, include_control_token: bool = False) -> SessionInfo:
        pages: tuple[dict[str, Any], ...] = ()
        if record.status == PublicSessionStatus.OPEN and record.backend is not None:
            try:
                pages = tuple(record.backend.list_pages())
            except Exception:
                pages = ()
        env = record.config.describe()
        return SessionInfo(
            session_id=record.session_id,
            status=record.status,
            created_at_ms=record.created_at_ms,
            last_activity_at_ms=record.last_activity_at_ms,
            idle_timeout_ms=record.idle_timeout_ms,
            profile=str(env["profile"]),
            browser_engine=str(env["engine"]),
            headless=bool(env["headless"]),
            pages=pages,
            cleanup_errors=tuple(record.cleanup_errors),
            authority_policy=self._authority_summary(record),
            receipt_chain_head=record.receipt_chain_head,
            control=(
                {
                    "agent_id": record.agent_id,
                    "control_epoch": record.control_epoch,
                    **({"control_token": record.control_token} if include_control_token else {}),
                }
                if record.agent_id is not None and record.control_token is not None
                else None
            ),
        )

    def _require_record(self, session_id: str, *, require_open: bool = True) -> _SessionRecord:
        if not isinstance(session_id, str) or not session_id:
            raise StatefulSessionError("session was not found", failure_kind=SessionFailureKind.SESSION_NOT_FOUND)
        with self._registry_lock:
            record = self._records.get(session_id)
        if record is None:
            raise StatefulSessionError("session was not found", failure_kind=SessionFailureKind.SESSION_NOT_FOUND)
        if require_open:
            if record.status == PublicSessionStatus.CLOSED:
                raise StatefulSessionError("session is closed", failure_kind=SessionFailureKind.SESSION_CLOSED)
            if record.status == PublicSessionStatus.EXPIRED:
                raise StatefulSessionError("session is expired", failure_kind=SessionFailureKind.SESSION_EXPIRED)
            if record.status == PublicSessionStatus.TERMINAL:
                raise StatefulSessionError("browser session is terminal", failure_kind=SessionFailureKind.TERMINAL_BROWSER_FAILURE)
        return record

    def _access(self, session_id: str) -> _SessionRecord:
        record = self._require_record(session_id)
        self._expire_if_idle(record)
        return self._require_record(session_id)

    def _expire_if_idle(self, record: _SessionRecord) -> None:
        if record.status == PublicSessionStatus.OPEN and _now_ms() - record.last_activity_at_ms >= record.idle_timeout_ms:
            with self._locked(record):
                if record.status == PublicSessionStatus.OPEN and _now_ms() - record.last_activity_at_ms >= record.idle_timeout_ms:
                    self._close_record(record, PublicSessionStatus.EXPIRED)

    def _active_backend(self, record: _SessionRecord) -> PlaywrightBackend:
        backend = record.backend
        if backend is None or not backend.is_started:
            record.status = PublicSessionStatus.TERMINAL
            raise StatefulSessionError("browser session is terminal", failure_kind=SessionFailureKind.TERMINAL_BROWSER_FAILURE)
        return backend

    def _select_backend_page(self, backend: PlaywrightBackend, page_id: str) -> None:
        page = backend.inspect_page(page_id)
        if page is None or page.get("lifecycle_state") != "open":
            raise StatefulSessionError("page ID is invalid or closed", failure_kind=SessionFailureKind.INVALID_PAGE_ID)
        backend._activate_page(page_id)

    def _touch(self, record: _SessionRecord) -> None:
        record.last_activity_at_ms = _now_ms()

    def _close_record(self, record: _SessionRecord, status: PublicSessionStatus) -> None:
        backend = record.backend
        if backend is not None:
            try:
                backend.stop()
            except Exception:
                record.cleanup_errors.append("browser cleanup failed")
            if backend.cleanup_errors and "browser cleanup reported errors" not in record.cleanup_errors:
                record.cleanup_errors.append("browser cleanup reported errors")
        record.backend = None
        record.status = status
        record.last_activity_at_ms = _now_ms()

    class _LockContext:
        def __init__(self, record: _SessionRecord) -> None:
            self.record = record
            self.acquired = False

        def __enter__(self) -> None:
            self.acquired = self.record.lock.acquire(blocking=False)
            if not self.acquired:
                raise StatefulSessionError("session is busy", failure_kind=SessionFailureKind.SESSION_BUSY)

        def __exit__(self, *_: Any) -> None:
            if self.acquired:
                self.record.lock.release()

    def _locked(self, record: _SessionRecord) -> "StatefulSessionRuntime._LockContext":
        return self._LockContext(record)


_default_runtime = StatefulSessionRuntime()


def open_session(*args: Any, **kwargs: Any) -> SessionInfo:
    return _default_runtime.open_session(*args, **kwargs)


def get_session(session_id: str) -> SessionInfo:
    return _default_runtime.get_session(session_id)


def observe_session_page(session_id: str, *args: Any, **kwargs: Any) -> SessionObservation:
    return _default_runtime.observe_page(session_id, *args, **kwargs)


def execute_session_operation(session_id: str, operation: Operation, **kwargs: Any) -> SessionOperationResult:
    return _default_runtime.execute_operation(session_id, operation, **kwargs)


def prepare_session_operation(session_id: str, operation: Operation, **kwargs: Any) -> PreparedOperation:
    return _default_runtime.prepare_operation(session_id, operation, **kwargs)


def commit_session_operation(session_id: str, token: str, **kwargs: Any) -> CommitResult:
    return _default_runtime.commit_operation(session_id, token, **kwargs)


def list_session_preparations(session_id: str) -> tuple[PreparedOperation, ...]:
    return _default_runtime.list_prepared_operations(session_id)


def get_session_receipt_chain(session_id: str) -> tuple[ExecutionReceipt, ...]:
    return _default_runtime.receipt_chain(session_id)


def get_session_receipt_chain_checkpoint(session_id: str) -> ReceiptChainCheckpoint:
    return _default_runtime.receipt_chain_checkpoint(session_id)


def execute_session_plan(session_id: str, plan: ExecutionPlan, **kwargs: Any) -> SessionPlanResult:
    return _default_runtime.execute_plan(session_id, plan, **kwargs)


def inspect_session_pages(session_id: str) -> tuple[dict[str, Any], ...]:
    return _default_runtime.inspect_pages(session_id)


def select_session_page(session_id: str, page_id: str, **kwargs: Any) -> dict[str, Any]:
    return _default_runtime.select_page(session_id, page_id, **kwargs)


def inspect_session_dialogs(session_id: str) -> tuple[dict[str, Any], ...]:
    return _default_runtime.inspect_dialogs(session_id)


def close_session(session_id: str, **kwargs: Any) -> SessionInfo:
    return _default_runtime.close_session(session_id, **kwargs)


def prepare_agent_handoff(session_id: str, **kwargs: Any) -> AgentHandoffCheckpoint:
    return _default_runtime.prepare_agent_handoff(session_id, **kwargs)


def claim_agent_handoff(session_id: str, handoff_token: str, new_agent_id: str) -> AgentHandoff:
    return _default_runtime.claim_agent_handoff(session_id, handoff_token, new_agent_id)


def cleanup_expired_sessions() -> tuple[str, ...]:
    return _default_runtime.cleanup_expired_sessions()
