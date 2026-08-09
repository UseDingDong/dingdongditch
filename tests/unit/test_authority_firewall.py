from __future__ import annotations

from unittest.mock import MagicMock, patch

from dingdongditch import (
    Action,
    ActionType,
    AuthorityEnvelope,
    AuthorityFirewall,
    FirewallOutcome,
    Locator,
    LocatorStrategy,
    Operation,
    ProvenanceClass,
    StatefulSessionRuntime,
)
from dingdongditch.authentication import SecretReference
from dingdongditch.contract.upload import UploadAuthorization
from dingdongditch.plan_json import plan_document_from_dict


def _operation(action: Action, *, provenance=()) -> Operation:
    return Operation("op", "https://allowed.example.test/form", action, provenance=tuple(provenance))


def _policy(**changes):
    base = dict(
        policy_id="host-policy",
        granted_authorities=(ProvenanceClass.HOST_POLICY, ProvenanceClass.USER_AUTHORITY),
        allowed_origins=("https://allowed.example.test",),
        allowed_action_types=("navigate", "fill", "upload_file"),
        required_authority_by_action={"upload_file": ProvenanceClass.USER_AUTHORITY},
    )
    base.update(changes)
    return AuthorityEnvelope(**base)


def _decision(operation: Operation, policy: AuthorityEnvelope, **kwargs):
    return AuthorityFirewall().decide(operation, policy, now_ms=100, **kwargs)


def test_firewall_allowed_denied_origin_action_expiry_and_budget():
    op = _operation(Action(ActionType.NAVIGATE))
    assert _decision(op, _policy()).outcome is FirewallOutcome.AUTHORIZED
    assert _decision(op, _policy(denied_action_types=("navigate",))).outcome is FirewallOutcome.ACTION_NOT_ALLOWED
    assert _decision(op, _policy(allowed_origins=("https://other.example.test",))).outcome is FirewallOutcome.ORIGIN_NOT_ALLOWED
    assert _decision(op, _policy(expires_at_ms=100)).outcome is FirewallOutcome.AUTHORITY_EXPIRED
    assert _decision(op, _policy(max_action_count=1), action_count=1).outcome is FirewallOutcome.SIDE_EFFECT_BUDGET_EXCEEDED


def test_firewall_upload_secret_and_untrusted_provenance_rules(tmp_path):
    upload = tmp_path / "authorized.txt"
    upload.write_text("small", encoding="utf-8")
    upload_op = _operation(Action(
        ActionType.UPLOAD_FILE,
        locator=Locator(LocatorStrategy.TEST_ID, "upload"),
        upload_authorization=UploadAuthorization((str(upload),), allowed_files=(str(upload),)),
    ))
    assert _decision(upload_op, _policy(allowed_file_names=("authorized.txt",))).authorized
    assert _decision(upload_op, _policy(allowed_file_names=("other.txt",))).outcome is FirewallOutcome.POLICY_REJECTED

    secret_op = _operation(Action(
        ActionType.FILL,
        locator=Locator(LocatorStrategy.TEST_ID, "password"),
        secret_reference=SecretReference("host/password"),
    ))
    assert _decision(secret_op, _policy(allowed_secret_references=("host/password",))).authorized
    assert _decision(secret_op, _policy(allowed_secret_references=("other",))).outcome is FirewallOutcome.POLICY_REJECTED

    irreversible = _operation(
        Action(ActionType.NAVIGATE), provenance=(ProvenanceClass.WEB_UNTRUSTED,)
    )
    decision = _decision(
        irreversible,
        _policy(irreversible_action_types=("navigate",), deny_untrusted_for_irreversible=True),
    )
    assert decision.outcome is FirewallOutcome.PROVENANCE_POLICY_REJECTED
    assert decision.input_provenance == (ProvenanceClass.WEB_UNTRUSTED,)


def test_session_enforces_policy_before_executor_and_legacy_session_remains_compatible():
    backend = MagicMock()
    backend.is_started = True
    backend.page.url = "https://allowed.example.test/"
    backend.page_id = "page-1"
    backend.backend_identity = "fake"
    backend.browser_identity = "fake"
    backend.browser_environment.return_value = {"page_id": "page-1"}
    backend.list_pages.return_value = [{"page_id": "page-1", "active": True}]
    backend.list_dialog_history.return_value = []
    with patch("dingdongditch.runtime.stateful_session.PlaywrightBackend", return_value=backend), patch(
        "dingdongditch.runtime.stateful_session._execute_operation"
    ) as execute:
        runtime = StatefulSessionRuntime()
        protected = runtime.open_session(authority_envelope=_policy(denied_action_types=("navigate",)))
        result = runtime.execute_operation(protected.session_id, _operation(Action(ActionType.NAVIGATE)))
        assert result.receipt.authority_decision["outcome"] == FirewallOutcome.ACTION_NOT_ALLOWED.value
        assert result.receipt.action_evidence["dispatch_attempted"] is False
        execute.assert_not_called()

        legacy = runtime.open_session()
        # No implicit firewall policy means the legacy call path is unchanged.
        execute.return_value = result.receipt
        runtime.execute_operation(legacy.session_id, _operation(Action(ActionType.NAVIGATE)))
        execute.assert_called_once()


def test_authority_envelope_round_trips_through_canonical_plan_contract():
    document = {
        "schema_version": "1.0.0",
        "browser": {"engine": "chromium", "channel": "bundled", "headless": True},
        "plan": {
            "plan_id": "governed", "authority_envelope": _policy().to_dict(),
            "operations": [{"operation_id": "nav", "url": "https://allowed.example.test/", "action": {"type": "navigate"}, "provenance": ["agent_reasoning"]}],
        },
    }
    plan = plan_document_from_dict(document)
    assert plan.authority_envelope.digest == _policy().digest
    assert plan.operations[0].provenance == (ProvenanceClass.AGENT_REASONING,)
