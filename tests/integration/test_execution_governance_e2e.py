from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from dingdongditch import (
    Action, ActionType, AuthorityEnvelope, CommitRejectedReason, EvidenceSourceClass, Expectation,
    ExpectationType, Locator, LocatorStrategy, Operation, ProvenanceClass,
    StatefulSessionError, StatefulSessionRuntime, VerificationCheck,
    VerificationPolicy, VerificationQuorum, MutationArbitrationPolicy, verify_receipt_chain,
)


def test_governed_two_phase_quorum_chain_and_hot_handoff(fixture_url):
    parsed = urlsplit(fixture_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    policy = AuthorityEnvelope(
        policy_id="governance-e2e",
        granted_authorities=(ProvenanceClass.HOST_POLICY,),
        allowed_origins=(origin,),
        allowed_action_types=("navigate", "fill"),
        require_preparation_for=("fill",),
        transfer_prepared_operations=True,
        max_action_count=3,
    )
    runtime = StatefulSessionRuntime()
    opened = runtime.open_session(authority_envelope=policy, agent_id="planner-a")
    token_a = opened.control["control_token"]
    try:
        nav = runtime.execute_operation(
            opened.session_id,
            Operation(
                "nav", fixture_url, Action(ActionType.NAVIGATE),
                expectations=[Expectation(ExpectationType.URL, url_value=fixture_url, expectation_id="page")],
            ),
            agent_id="planner-a", control_token=token_a,
        )
        assert nav.verdict == "VERIFIED"
        final = Operation(
            "fill-final", fixture_url,
            Action(ActionType.FILL, locator=Locator(LocatorStrategy.TEST_ID, "text-input"), text="governed"),
            expectations=[
                Expectation(ExpectationType.ATTRIBUTE, locator=Locator(LocatorStrategy.TEST_ID, "text-input"), attribute_name="value", attribute_value="governed", expectation_id="dom"),
                Expectation(ExpectationType.URL, url_value=fixture_url, expectation_id="page"),
            ],
            verification_quorum=VerificationQuorum(
                VerificationPolicy.ALL,
                checks=(
                    VerificationCheck("dom", "dom", EvidenceSourceClass.DOM_STATE),
                    VerificationCheck("page", "page", EvidenceSourceClass.PAGE_STATE),
                ),
            ),
        )
        prepared = runtime.prepare_operation(opened.session_id, final, agent_id="planner-a", control_token=token_a)
        checkpoint = runtime.prepare_agent_handoff(opened.session_id, agent_id="planner-a", control_token=token_a)
        handoff = runtime.claim_agent_handoff(opened.session_id, checkpoint.handoff_token, "planner-b")
        with pytest.raises(StatefulSessionError):
            runtime.execute_operation(opened.session_id, final, agent_id="planner-a", control_token=token_a)
        committed = runtime.commit_operation(opened.session_id, prepared.token, agent_id="planner-b", control_token=handoff.control_token)
        assert committed.committed
        assert committed.receipt.verdict.value == "VERIFIED"
        assert committed.receipt.quorum_verification["achieved"] == 2
        assert verify_receipt_chain(runtime.receipt_chain(opened.session_id)).valid
        assert runtime.inspect_pages(opened.session_id)[0]["page_id"] == nav.page_state[0]["page_id"]
    finally:
        runtime.close_session(opened.session_id, agent_id="planner-b" if 'handoff' in locals() else "planner-a", control_token=handoff.control_token if 'handoff' in locals() else token_a)


def test_governed_frame_action_uses_resolved_child_origin_not_top_level_origin(fixture_url):
    host_url = fixture_url.replace("index.html", "iframe_host.html")
    parsed = urlsplit(host_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    runtime = StatefulSessionRuntime()
    opened = runtime.open_session(
        authority_envelope=AuthorityEnvelope(
            policy_id="frame-origin-e2e",
            granted_authorities=(ProvenanceClass.HOST_POLICY,),
            allowed_origins=(origin,),
            allowed_action_types=("navigate", "click"),
            allow_frame_actions=True,
        ),
    )
    try:
        nav = runtime.execute_operation(
            opened.session_id, Operation("nav-host", host_url, Action(ActionType.NAVIGATE)),
        )
        assert nav.receipt.action_executed_successfully
        attempted = runtime.execute_operation(
            opened.session_id,
            Operation(
                "cross-origin-click", host_url,
                Action(
                    ActionType.CLICK,
                    locator=Locator(LocatorStrategy.TEST_ID, "frame-click"),
                    frame=Locator(LocatorStrategy.TEST_ID, "cross-origin-frame"),
                ),
            ),
        )
        assert attempted.receipt.authority_decision["outcome"] == "ORIGIN_NOT_ALLOWED"
        assert attempted.receipt.action_evidence["dispatch_attempted"] is False
    finally:
        runtime.close_session(opened.session_id)


def test_prepared_commit_rejects_external_reverted_dom_and_control_value_changes(fixture_url):
    parsed = urlsplit(fixture_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    runtime = StatefulSessionRuntime()
    opened = runtime.open_session(
        authority_envelope=AuthorityEnvelope(
            policy_id="external-interference-e2e",
            granted_authorities=(ProvenanceClass.HOST_POLICY,),
            allowed_origins=(origin,), allowed_action_types=("navigate", "click"),
            require_preparation_for=("click",),
        )
    )
    try:
        runtime.execute_operation(opened.session_id, Operation("nav", fixture_url, Action(ActionType.NAVIGATE)))
        click = Operation(
            "click", fixture_url,
            Action(ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "target-control")),
        )
        prepared = runtime.prepare_operation(opened.session_id, click)
        backend = runtime._records[opened.session_id].backend
        assert backend is not None
        # A human/another automation/page script can make and revert markup
        # before commit. The installed mutation epoch retains that fact.
        backend.page.evaluate("""() => {
            const marker = document.createElement('div'); marker.id = 'external-marker';
            document.body.appendChild(marker); marker.remove();
        }""")
        assert runtime.commit_operation(opened.session_id, prepared.token).rejection_reason is CommitRejectedReason.PREPARED_STATE_CHANGED

        prepared = runtime.prepare_operation(opened.session_id, click)
        # Property-only control mutation does not need to alter outerHTML; it
        # is captured separately as material form state.
        backend.page.evaluate("() => { document.querySelector('[data-testid=text-input]').value = 'external'; }")
        assert runtime.commit_operation(opened.session_id, prepared.token).rejection_reason is CommitRejectedReason.PREPARED_STATE_CHANGED
    finally:
        runtime.close_session(opened.session_id)


def test_mutation_arbitration_detects_out_of_band_page_change_before_commit(fixture_url):
    parsed = urlsplit(fixture_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    runtime = StatefulSessionRuntime()
    opened = runtime.open_session(
        authority_envelope=AuthorityEnvelope(
            policy_id="arbitration-e2e", granted_authorities=(ProvenanceClass.HOST_POLICY,),
            allowed_origins=(origin,), allowed_action_types=("navigate", "click"),
            require_preparation_for=("click",),
        ),
        mutation_policy=MutationArbitrationPolicy.REQUIRE_REPREPARE,
    )
    try:
        runtime.execute_operation(opened.session_id, Operation("nav", fixture_url, Action(ActionType.NAVIGATE)))
        action = Operation("submit", fixture_url, Action(ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "target-control")))
        prepared = runtime.prepare_operation(opened.session_id, action)
        backend = runtime._records[opened.session_id].backend
        assert backend is not None
        # This bypasses DingDong dispatch entirely, exactly like a manual or
        # second-automation DOM change. Its actor is intentionally unknown.
        backend.page.evaluate("() => { document.querySelector('[data-testid=text-input]').value = '10'; }")
        result = runtime.commit_operation(opened.session_id, prepared.token)
        assert result.rejection_reason is CommitRejectedReason.PREPARATION_INVALIDATED
        status = runtime.mutation_status(opened.session_id)
        assert status["last_evidence"]["actor"] == "external_unknown"
        assert runtime.prepare_operation(opened.session_id, action).mutation_epoch > prepared.mutation_epoch
    finally:
        runtime.close_session(opened.session_id)
