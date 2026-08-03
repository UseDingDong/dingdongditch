from __future__ import annotations

import hashlib
import json
import threading

import pytest

from dingdongditch.continuity import (
    CommandState,
    ContinuityError,
    ContinuitySession,
    SessionLifecycle,
    TerminalClassification,
    TransportKind,
)
from dingdongditch.runtime.file_lease import LeaseUnavailableError
from dingdongditch.runtime.publication import publish_json


def create_session(tmp_path, generation="host-1"):
    return ContinuitySession.create(
        tmp_path / "session",
        session_id="session-1",
        principal_id="agent-1",
        objective_id="objective-1",
        objective={"reference": "objectives/one.json"},
        owner_generation=generation,
        permission_reference="permissions/v1.json",
    )


def bind(session, generation="browser-1"):
    return session.acquire_browser_binding(
        binding_id=f"binding-{generation}",
        binding_generation=generation,
        browser_profile_reference="profiles/dingdong",
        backend_identity="playwright-sync",
        session_identity=f"browser-session-{generation}",
        lease_owner=session.header.owner_generation,
        capability_snapshot={"engine": "chromium", "downloads": True},
    )


def authorized(session, command_id="command-1"):
    return session.record_authorized_command(
        command_id=command_id,
        planner_generation="planner-1",
        transport_payload_reference=f"plans/{command_id}.json",
        authorization_version="permissions-v1",
    )


def receipt(path, verdict="VERIFIED"):
    value = {
        "schema_version": "2.2.0",
        "plan_id": "plan-1",
        "plan_verdict": verdict,
        "expectation_results": [{
            "expectation_id": "expected-page", "expectation_type": "url_matches",
            "expected": {"url": "https://example.test"},
            "observed": {"url": "https://example.test"}, "result": "pass",
            "evidence_refs": ["signal-1"],
        }],
    }
    publish_json(path, value, sort_keys=True)
    return value


def test_session_creation_publishes_minimal_header_atomically(tmp_path):
    session = create_session(tmp_path)
    try:
        stored = json.loads((session.root / "session.json").read_text(encoding="utf-8"))
        assert stored == session.header.to_dict()
        assert stored["lifecycle_status"] == "active"
        assert stored["objective"] == {"reference": "objectives/one.json"}
        assert set(stored) == {
            "session_id", "created_at", "principal_id", "objective_id",
            "objective", "schema_version", "lifecycle_status",
            "owner_generation", "permission_reference",
        }
        assert not list(session.root.glob(".session.json.*.tmp"))
    finally:
        session.close()


def test_command_journal_is_append_only_and_reconstructs_state(tmp_path):
    with create_session(tmp_path) as session:
        proposed = session.propose_command(
            command_id="command-1",
            planner_generation="planner-1",
            transport_payload_reference="plans/one.json",
            authorization_version="permissions-v1",
        )
        assert proposed.state == CommandState.PROPOSED
        current = session.authorize_command("command-1")
        assert current.state == CommandState.AUTHORIZED
        assert current.transport_kind == TransportKind.BROWSER
        events = (session.root / "commands.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(events) == 2
        assert [json.loads(event)["event_type"] for event in events] == [
            "command_created", "command_state_changed"
        ]


def test_lifecycle_is_monotonic_and_terminal_session_is_read_only(tmp_path):
    session = create_session(tmp_path)
    session.set_lifecycle(SessionLifecycle.COMPLETED)
    assert session.header.lifecycle_status == SessionLifecycle.COMPLETED
    with pytest.raises(ContinuityError):
        authorized(session)
    with pytest.raises(ContinuityError):
        session.set_lifecycle(SessionLifecycle.STOPPED)
    session.close()


def test_browser_binding_and_rebinding_have_distinct_generations(tmp_path):
    with create_session(tmp_path) as session:
        first = bind(session, "browser-1")
        with pytest.raises(ContinuityError):
            bind(session, "browser-2")
        session.release_browser_binding(binding_generation="browser-1")
        second = bind(session, "browser-2")
        assert first.released_at is None
        assert second.binding_generation == "browser-2"
        assert session.active_binding() == second
        assert len(session.bindings()) == 2


@pytest.mark.parametrize("forbidden", ["locator", "page", "dom_handle", "playwright", "freshness"])
def test_binding_rejects_browser_local_state(tmp_path, forbidden):
    with create_session(tmp_path) as session:
        with pytest.raises(ValueError):
            session.acquire_browser_binding(
                binding_id="binding-1",
                binding_generation="browser-1",
                browser_profile_reference="profiles/dingdong",
                backend_identity="playwright-sync",
                session_identity="browser-session-1",
                lease_owner="host-1",
                capability_snapshot={forbidden: "not-allowed"},
            )


def test_dispatch_requires_active_generation_and_cannot_replay(tmp_path):
    with create_session(tmp_path) as session:
        authorized(session)
        bind(session)
        with pytest.raises(ContinuityError):
            session.dispatch_command("command-1", binding_generation="stale-browser")
        dispatched = session.dispatch_command("command-1", binding_generation="browser-1")
        assert dispatched.state == CommandState.DISPATCHED
        with pytest.raises(ContinuityError):
            session.dispatch_command("command-1", binding_generation="browser-1")
        with pytest.raises(ContinuityError):
            session.cancel_command("command-1")


def test_receipt_attachment_indexes_existing_receipt_and_hash(tmp_path):
    with create_session(tmp_path) as session:
        authorized(session)
        bind(session)
        session.dispatch_command("command-1", binding_generation="browser-1")
        receipt_path = tmp_path / "receipt.json"
        receipt(receipt_path)
        result = session.attach_receipt(
            "command-1",
            receipt_reference=receipt_path,
            binding_generation="browser-1",
            terminal_classification=TerminalClassification.VERIFIED,
        )
        assert result.state == CommandState.VERIFIED
        entry = session.evidence_index(verify_integrity=True)[0]
        assert entry["receipt_reference"] == str(receipt_path.resolve())
        assert entry["receipt_schema"] == "2.2.0"
        assert entry["receipt_sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        assert entry["binding_generation"] == "browser-1"
        assert entry["verified_facts"][0]["expectation_id"] == "expected-page"


def test_receipt_classification_cannot_contradict_runtime(tmp_path):
    with create_session(tmp_path) as session:
        authorized(session)
        bind(session)
        session.dispatch_command("command-1", binding_generation="browser-1")
        receipt_path = tmp_path / "receipt.json"
        receipt(receipt_path, verdict="EXECUTION_FAILED")
        with pytest.raises(ContinuityError):
            session.attach_receipt(
                "command-1",
                receipt_reference=receipt_path,
                binding_generation="browser-1",
                terminal_classification=TerminalClassification.VERIFIED,
            )
        assert session.commands()["command-1"].state == CommandState.DISPATCHED


def test_evidence_integrity_detects_receipt_mutation(tmp_path):
    with create_session(tmp_path) as session:
        authorized(session)
        bind(session)
        session.dispatch_command("command-1", binding_generation="browser-1")
        receipt_path = tmp_path / "receipt.json"
        receipt(receipt_path)
        session.attach_receipt(
            "command-1", receipt_reference=receipt_path,
            binding_generation="browser-1",
            terminal_classification=TerminalClassification.VERIFIED,
        )
        publish_json(receipt_path, {"schema_version": "2.2.0", "plan_verdict": "VERIFIED", "changed": True})
        with pytest.raises(ContinuityError, match="integrity"):
            session.evidence_index(verify_integrity=True)


def test_restart_marks_unconfirmed_dispatch_outcome_unknown(tmp_path):
    session = create_session(tmp_path)
    authorized(session)
    bind(session)
    session.dispatch_command("command-1", binding_generation="browser-1")
    session.close()  # Models owner death after dispatch and before confirmation.

    with ContinuitySession.open(session.root, owner_generation="host-2") as recovered:
        command = recovered.commands()["command-1"]
        assert command.state == CommandState.OUTCOME_UNKNOWN
        assert recovered.header.owner_generation == "host-2"
        with pytest.raises(ContinuityError):
            recovered.dispatch_command("command-1", binding_generation="browser-1")


def test_recovery_completes_receipt_attach_crash_window(tmp_path):
    session = create_session(tmp_path)
    authorized(session)
    bind(session)
    session.dispatch_command("command-1", binding_generation="browser-1")
    receipt_path = tmp_path / "receipt.json"
    receipt(receipt_path)
    raw = receipt_path.read_bytes()
    # Simulate failure after durable evidence append but before command transition.
    session._append("evidence.jsonl", {
        "schema_version": "1.0.0", "event_type": "receipt_attached",
        "recorded_at": 1.0, "command_id": "command-1",
        "receipt_reference": str(receipt_path.resolve()), "receipt_schema": "2.2.0",
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "binding_generation": "browser-1", "terminal_classification": "verified",
        "verified_facts": [],
    })
    session.close()
    with ContinuitySession.open(session.root, owner_generation="host-2") as recovered:
        assert recovered.commands()["command-1"].state == CommandState.VERIFIED


def test_owner_lease_rejects_second_writer_and_allows_takeover_after_close(tmp_path):
    first = create_session(tmp_path)
    with pytest.raises(LeaseUnavailableError):
        ContinuitySession.open(first.root, owner_generation="host-2")
    first.close()
    second = ContinuitySession.open(first.root, owner_generation="host-2")
    second.close()


def test_concurrent_duplicate_command_publication_has_one_winner(tmp_path):
    with create_session(tmp_path) as session:
        outcomes = []
        barrier = threading.Barrier(3)

        def publish():
            barrier.wait()
            try:
                authorized(session, "same-command")
                outcomes.append("accepted")
            except ContinuityError:
                outcomes.append("rejected")

        threads = [threading.Thread(target=publish) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        assert sorted(outcomes) == ["accepted", "rejected"]
        assert list(session.commands()) == ["same-command"]
