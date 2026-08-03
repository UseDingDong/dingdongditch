"""Durable logical continuity above DingDongDitch execution.

This module records host decisions and references runtime receipts.  It never
executes, plans, retries, or interprets browser state.
"""

from __future__ import annotations

import hashlib
import json
import time
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from dingdongditch.runtime.file_lease import FileLease, acquire_file_lease
from dingdongditch.runtime.publication import (
    PublicationUnavailableError,
    append_json_line,
    publish_json,
    read_published_json,
    read_published_text,
)


CONTINUITY_SCHEMA_VERSION = "1.0.0"


class ContinuityError(RuntimeError):
    """A continuity contract or state transition was rejected."""


class SessionLifecycle(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    STOPPED = "stopped"


class CommandState(str, Enum):
    PROPOSED = "proposed"
    AUTHORIZED = "authorized"
    DISPATCHED = "dispatched"
    VERIFIED = "verified"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    CANCELLED = "cancelled"


class TransportKind(str, Enum):
    # A schema discriminator, not a transport implementation abstraction.
    BROWSER = "browser"


class TerminalClassification(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


_TERMINAL_COMMAND_STATES = frozenset(
    {
        CommandState.VERIFIED,
        CommandState.FAILED,
        CommandState.OUTCOME_UNKNOWN,
        CommandState.CANCELLED,
    }
)

_COMMAND_TRANSITIONS = {
    CommandState.PROPOSED: {CommandState.AUTHORIZED, CommandState.CANCELLED},
    CommandState.AUTHORIZED: {CommandState.DISPATCHED, CommandState.CANCELLED},
    CommandState.DISPATCHED: {
        CommandState.VERIFIED,
        CommandState.FAILED,
        CommandState.OUTCOME_UNKNOWN,
    },
}


def _now() -> float:
    return time.time()


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in value):
        raise ValueError(f"{name} contains unsupported characters")
    return value


def _json_value(name: str, value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-serializable") from exc
    return value


def _event(event_type: str, **fields: Any) -> dict[str, Any]:
    return {
        "schema_version": CONTINUITY_SCHEMA_VERSION,
        "event_type": event_type,
        "recorded_at": _now(),
        **fields,
    }


@dataclass(frozen=True)
class SessionHeader:
    session_id: str
    created_at: float
    principal_id: str
    objective_id: str
    objective: Any
    schema_version: str
    lifecycle_status: SessionLifecycle
    owner_generation: str
    permission_reference: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SessionHeader":
        return cls(
            session_id=value["session_id"],
            created_at=value["created_at"],
            principal_id=value["principal_id"],
            objective_id=value["objective_id"],
            objective=value["objective"],
            schema_version=value["schema_version"],
            lifecycle_status=SessionLifecycle(value["lifecycle_status"]),
            owner_generation=value["owner_generation"],
            permission_reference=value["permission_reference"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "principal_id": self.principal_id,
            "objective_id": self.objective_id,
            "objective": self.objective,
            "schema_version": self.schema_version,
            "lifecycle_status": self.lifecycle_status.value,
            "owner_generation": self.owner_generation,
            "permission_reference": self.permission_reference,
        }


@dataclass(frozen=True)
class CommandRecord:
    command_id: str
    session_id: str
    planner_generation: str
    transport_kind: TransportKind
    transport_payload_reference: str
    authorization_version: str
    created_at: float
    state: CommandState
    receipt_reference: str | None = None
    binding_generation: str | None = None


@dataclass(frozen=True)
class BrowserBinding:
    binding_id: str
    binding_generation: str
    browser_profile_reference: str
    backend_identity: str
    session_identity: str
    lease_owner: str
    capability_snapshot: dict[str, Any]
    acquired_at: float
    released_at: float | None = None


class ContinuitySession:
    """Exclusive writer for one durable continuity session directory."""

    def __init__(self, root: Path, header: SessionHeader, lease: FileLease) -> None:
        self.root = root
        self.header = header
        self._lease = lease
        self._closed = False
        self._mutation_lock = threading.RLock()

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        session_id: str,
        principal_id: str,
        objective_id: str,
        objective: Any,
        owner_generation: str,
        permission_reference: str,
    ) -> "ContinuitySession":
        root = root.resolve()
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(f"continuity session already exists: {root}")
        root.mkdir(parents=True, exist_ok=True)
        lease = acquire_file_lease(root / ".owner.lock")
        try:
            header = SessionHeader(
                session_id=_identifier("session_id", session_id),
                created_at=_now(),
                principal_id=_identifier("principal_id", principal_id),
                objective_id=_identifier("objective_id", objective_id),
                objective=_json_value("objective", objective),
                schema_version=CONTINUITY_SCHEMA_VERSION,
                lifecycle_status=SessionLifecycle.ACTIVE,
                owner_generation=_identifier("owner_generation", owner_generation),
                permission_reference=permission_reference,
            )
            if not permission_reference:
                raise ValueError("permission_reference must be non-empty")
            publish_json(root / "session.json", header.to_dict(), sort_keys=True)
            return cls(root, header, lease)
        except Exception:
            lease.close()
            raise

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        owner_generation: str,
        recover_interrupted: bool = True,
    ) -> "ContinuitySession":
        root = root.resolve()
        lease = acquire_file_lease(root / ".owner.lock")
        try:
            header = SessionHeader.from_dict(read_published_json(root / "session.json"))
            if header.schema_version != CONTINUITY_SCHEMA_VERSION:
                raise ContinuityError("unsupported continuity schema version")
            header = SessionHeader(
                **{
                    **header.__dict__,
                    "owner_generation": _identifier("owner_generation", owner_generation),
                }
            )
            publish_json(root / "session.json", header.to_dict(), sort_keys=True)
            session = cls(root, header, lease)
            if recover_interrupted:
                session.recover_interrupted_commands()
            return session
        except Exception:
            lease.close()
            raise

    def close(self) -> None:
        if not self._closed:
            self._lease.close()
            self._closed = True

    def __enter__(self) -> "ContinuitySession":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _require_writable(self) -> None:
        if self._closed:
            raise ContinuityError("continuity session owner is closed")
        if self.header.lifecycle_status != SessionLifecycle.ACTIVE:
            raise ContinuityError("terminal continuity session is read-only")

    def _append(self, stream: str, value: dict[str, Any]) -> None:
        self._require_writable()
        append_json_line(self.root / stream, value)

    def _read_events(self, stream: str) -> list[dict[str, Any]]:
        path = self.root / stream
        try:
            payload = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        try:
            return [json.loads(line) for line in payload.splitlines() if line]
        except json.JSONDecodeError as exc:
            raise ContinuityError(f"corrupt continuity stream: {stream}") from exc

    def set_lifecycle(self, status: SessionLifecycle) -> None:
        self._require_writable()
        if status == SessionLifecycle.ACTIVE:
            raise ContinuityError("session is already active")
        self.header = SessionHeader(**{**self.header.__dict__, "lifecycle_status": status})
        publish_json(self.root / "session.json", self.header.to_dict(), sort_keys=True)

    def propose_command(
        self,
        *,
        command_id: str,
        planner_generation: str,
        transport_payload_reference: str,
        authorization_version: str,
    ) -> CommandRecord:
        with self._mutation_lock:
            command_id = _identifier("command_id", command_id)
            if command_id in self.commands():
                raise ContinuityError(f"command_id already exists: {command_id}")
            record = CommandRecord(
                command_id=command_id,
                session_id=self.header.session_id,
                planner_generation=_identifier("planner_generation", planner_generation),
                transport_kind=TransportKind.BROWSER,
                transport_payload_reference=transport_payload_reference,
                authorization_version=authorization_version,
                created_at=_now(),
                state=CommandState.PROPOSED,
            )
            if not transport_payload_reference or not authorization_version:
                raise ValueError("payload reference and authorization version are required")
            self._append("commands.jsonl", _event("command_created", **self._command_dict(record)))
            return record

    def record_authorized_command(self, **values: Any) -> CommandRecord:
        record = self.propose_command(**values)
        return self.authorize_command(record.command_id)

    def authorize_command(self, command_id: str) -> CommandRecord:
        return self._transition(command_id, CommandState.AUTHORIZED)

    def dispatch_command(self, command_id: str, *, binding_generation: str) -> CommandRecord:
        with self._mutation_lock:
            binding = self.active_binding()
            if binding is None or binding.binding_generation != binding_generation:
                raise ContinuityError("dispatch requires the active browser binding generation")
            return self._transition(
                command_id,
                CommandState.DISPATCHED,
                binding_generation=binding_generation,
            )

    def cancel_command(self, command_id: str) -> CommandRecord:
        return self._transition(command_id, CommandState.CANCELLED)

    def mark_outcome_unknown(self, command_id: str, *, reason: str) -> CommandRecord:
        if not reason:
            raise ValueError("unknown outcome requires a reason")
        return self._transition(command_id, CommandState.OUTCOME_UNKNOWN, reason=reason)

    def _transition(self, command_id: str, state: CommandState, **detail: Any) -> CommandRecord:
        with self._mutation_lock:
            commands = self.commands()
            try:
                current = commands[command_id]
            except KeyError as exc:
                raise ContinuityError(f"unknown command_id: {command_id}") from exc
            if state not in _COMMAND_TRANSITIONS.get(current.state, set()):
                raise ContinuityError(f"invalid command transition: {current.state.value} -> {state.value}")
            self._append(
                "commands.jsonl",
                _event(
                    "command_state_changed",
                    command_id=command_id,
                    from_state=current.state.value,
                    state=state.value,
                    **detail,
                ),
            )
            return self.commands()[command_id]

    def commands(self) -> dict[str, CommandRecord]:
        records: dict[str, CommandRecord] = {}
        for event in self._read_events("commands.jsonl"):
            command_id = event["command_id"]
            if event["event_type"] == "command_created":
                if command_id in records:
                    raise ContinuityError(f"duplicate command creation: {command_id}")
                records[command_id] = CommandRecord(
                    command_id=command_id,
                    session_id=event["session_id"],
                    planner_generation=event["planner_generation"],
                    transport_kind=TransportKind(event["transport_kind"]),
                    transport_payload_reference=event["transport_payload_reference"],
                    authorization_version=event["authorization_version"],
                    created_at=event["created_at"],
                    state=CommandState(event["state"]),
                )
            elif event["event_type"] == "command_state_changed":
                current = records.get(command_id)
                if current is None or current.state.value != event["from_state"]:
                    raise ContinuityError(f"invalid command journal chain: {command_id}")
                new_state = CommandState(event["state"])
                if new_state not in _COMMAND_TRANSITIONS.get(current.state, set()):
                    raise ContinuityError(f"invalid persisted command transition: {command_id}")
                records[command_id] = CommandRecord(
                    **{
                        **current.__dict__,
                        "state": new_state,
                        "receipt_reference": event.get("receipt_reference", current.receipt_reference),
                        "binding_generation": event.get("binding_generation", current.binding_generation),
                    }
                )
        return records

    @staticmethod
    def _command_dict(record: CommandRecord) -> dict[str, Any]:
        return {
            **record.__dict__,
            "transport_kind": record.transport_kind.value,
            "state": record.state.value,
        }

    def recover_interrupted_commands(self) -> list[str]:
        recovered: list[str] = []
        evidence = {item["command_id"]: item for item in self.evidence_index()}
        for command in list(self.commands().values()):
            if command.state == CommandState.DISPATCHED:
                attached = evidence.get(command.command_id)
                if attached is not None:
                    target = CommandState(attached["terminal_classification"])
                    self._transition(
                        command.command_id,
                        target,
                        receipt_reference=attached["receipt_reference"],
                        recovered_from_evidence=True,
                    )
                else:
                    self.mark_outcome_unknown(
                        command.command_id, reason="owner_restart_after_dispatch"
                    )
                recovered.append(command.command_id)
        return recovered

    def acquire_browser_binding(
        self,
        **values: Any,
    ) -> BrowserBinding:
        with self._mutation_lock:
            return self._acquire_browser_binding(**values)

    def _acquire_browser_binding(
        self,
        *,
        binding_id: str,
        binding_generation: str,
        browser_profile_reference: str,
        backend_identity: str,
        session_identity: str,
        lease_owner: str,
        capability_snapshot: dict[str, Any],
    ) -> BrowserBinding:
        if self.active_binding() is not None:
            raise ContinuityError("a browser binding is already active")
        for name, value in {
            "binding_id": binding_id,
            "binding_generation": binding_generation,
            "backend_identity": backend_identity,
            "session_identity": session_identity,
            "lease_owner": lease_owner,
        }.items():
            _identifier(name, value)
        if not browser_profile_reference:
            raise ValueError("browser_profile_reference is required")
        _json_value("capability_snapshot", capability_snapshot)
        forbidden = {"locator", "page", "page_reference", "dom_handle", "playwright", "freshness"}
        if self._contains_forbidden_key(capability_snapshot, forbidden):
            raise ValueError("capability snapshot contains browser-local state")
        binding = BrowserBinding(
            binding_id=binding_id,
            binding_generation=binding_generation,
            browser_profile_reference=browser_profile_reference,
            backend_identity=backend_identity,
            session_identity=session_identity,
            lease_owner=lease_owner,
            capability_snapshot=dict(capability_snapshot),
            acquired_at=_now(),
        )
        self._append("bindings.jsonl", _event("binding_acquired", **binding.__dict__))
        return binding

    @staticmethod
    def _contains_forbidden_key(value: Any, forbidden: set[str]) -> bool:
        if isinstance(value, dict):
            return any(
                str(key).lower() in forbidden
                or ContinuitySession._contains_forbidden_key(item, forbidden)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(ContinuitySession._contains_forbidden_key(item, forbidden) for item in value)
        return False

    def release_browser_binding(self, *, binding_generation: str) -> BrowserBinding:
        with self._mutation_lock:
            binding = self.active_binding()
            if binding is None or binding.binding_generation != binding_generation:
                raise ContinuityError("binding generation is not active")
            released_at = _now()
            self._append(
                "bindings.jsonl",
                _event(
                    "binding_released",
                    binding_id=binding.binding_id,
                    binding_generation=binding.binding_generation,
                    released_at=released_at,
                ),
            )
            return BrowserBinding(**{**binding.__dict__, "released_at": released_at})

    def bindings(self) -> list[BrowserBinding]:
        bindings: list[BrowserBinding] = []
        positions: dict[str, int] = {}
        for event in self._read_events("bindings.jsonl"):
            generation = event["binding_generation"]
            if event["event_type"] == "binding_acquired":
                if generation in positions:
                    raise ContinuityError("duplicate binding generation")
                positions[generation] = len(bindings)
                bindings.append(
                    BrowserBinding(
                        binding_id=event["binding_id"],
                        binding_generation=generation,
                        browser_profile_reference=event["browser_profile_reference"],
                        backend_identity=event["backend_identity"],
                        session_identity=event["session_identity"],
                        lease_owner=event["lease_owner"],
                        capability_snapshot=event["capability_snapshot"],
                        acquired_at=event["acquired_at"],
                    )
                )
            elif event["event_type"] == "binding_released":
                try:
                    index = positions[generation]
                except KeyError as exc:
                    raise ContinuityError("release references unknown binding") from exc
                binding = bindings[index]
                if binding.released_at is not None:
                    raise ContinuityError("binding released more than once")
                bindings[index] = BrowserBinding(
                    **{**binding.__dict__, "released_at": event["released_at"]}
                )
        return bindings

    def active_binding(self) -> BrowserBinding | None:
        active = [binding for binding in self.bindings() if binding.released_at is None]
        if len(active) > 1:
            raise ContinuityError("multiple active browser bindings")
        return active[0] if active else None

    def attach_receipt(
        self,
        command_id: str,
        **values: Any,
    ) -> CommandRecord:
        with self._mutation_lock:
            return self._attach_receipt(command_id, **values)

    def _attach_receipt(
        self,
        command_id: str,
        *,
        receipt_reference: str | Path,
        binding_generation: str,
        terminal_classification: TerminalClassification,
    ) -> CommandRecord:
        command = self.commands().get(command_id)
        if command is None or command.state != CommandState.DISPATCHED:
            raise ContinuityError("receipt can attach only to a dispatched command")
        if command.binding_generation != binding_generation:
            raise ContinuityError("receipt binding generation does not match dispatch")
        path = Path(receipt_reference).resolve()
        try:
            raw = read_published_text(path).encode("utf-8")
            receipt = json.loads(raw)
        except (PublicationUnavailableError, json.JSONDecodeError) as exc:
            raise PublicationUnavailableError(str(path)) from exc
        schema = receipt.get("schema_version")
        if not isinstance(schema, str) or not schema:
            raise ContinuityError("referenced receipt has no schema_version")
        facts = self._verified_facts_from_receipt(receipt)
        declared = self._classify_receipt(receipt)
        if terminal_classification != declared:
            raise ContinuityError(
                "terminal classification contradicts the DingDongDitch receipt"
            )
        digest = hashlib.sha256(raw).hexdigest()
        self._append(
            "evidence.jsonl",
            _event(
                "receipt_attached",
                command_id=command_id,
                receipt_reference=str(path),
                receipt_schema=schema,
                receipt_sha256=digest,
                binding_generation=binding_generation,
                terminal_classification=terminal_classification.value,
                verified_facts=facts,
            ),
        )
        target = {
            TerminalClassification.VERIFIED: CommandState.VERIFIED,
            TerminalClassification.FAILED: CommandState.FAILED,
            TerminalClassification.OUTCOME_UNKNOWN: CommandState.OUTCOME_UNKNOWN,
        }[terminal_classification]
        return self._transition(
            command_id,
            target,
            receipt_reference=str(path),
        )

    @staticmethod
    def _verified_facts_from_receipt(receipt: dict[str, Any]) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        results: list[Any] = list(receipt.get("expectation_results") or [])
        for step in receipt.get("steps") or []:
            nested = step.get("receipt") if isinstance(step, dict) else None
            if isinstance(nested, dict):
                results.extend(nested.get("expectation_results") or [])
        for result in results:
            if isinstance(result, dict) and result.get("result") == "pass":
                facts.append(
                    {
                        "fact_type": "verified_expectation",
                        "expectation_id": result.get("expectation_id"),
                        "expectation_type": result.get("expectation_type"),
                        "expected": result.get("expected"),
                        "observed": result.get("observed"),
                        "evidence_refs": list(result.get("evidence_refs") or []),
                    }
                )
        return facts

    @staticmethod
    def _classify_receipt(receipt: dict[str, Any]) -> TerminalClassification:
        verdict = receipt.get("plan_verdict", receipt.get("verdict"))
        if verdict == "VERIFIED":
            return TerminalClassification.VERIFIED
        if verdict in {"NOT_VERIFIED", "EXECUTION_FAILED"}:
            return TerminalClassification.FAILED
        if verdict == "INDETERMINATE":
            return TerminalClassification.OUTCOME_UNKNOWN
        raise ContinuityError("referenced artifact is not a recognized DingDongDitch receipt")

    def evidence_index(self, *, verify_integrity: bool = False) -> list[dict[str, Any]]:
        records = self._read_events("evidence.jsonl")
        if verify_integrity:
            for record in records:
                path = Path(record["receipt_reference"])
                try:
                    payload = read_published_text(path).encode("utf-8")
                    digest = hashlib.sha256(payload).hexdigest()
                except PublicationUnavailableError as exc:
                    raise ContinuityError("referenced receipt is missing") from exc
                if digest != record["receipt_sha256"]:
                    raise ContinuityError("referenced receipt failed integrity verification")
        return records
