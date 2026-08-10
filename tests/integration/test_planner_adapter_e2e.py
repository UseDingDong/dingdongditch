"""Planner facade coverage against the deterministic dynamic-page fixture."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from dingdongditch import (
    AuthorityEnvelope,
    PlannerAdapter,
    ProvenanceClass,
    SessionFailureKind,
    StatefulSessionError,
    TrustedHostRuntime,
)


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _operation(operation_id: str, url: str, action: dict, expectations: list[dict] | None = None) -> dict:
    return {
        "operation_id": operation_id,
        "url": url,
        "action": action,
        "expectations": expectations or [],
    }


def _element_id(observation: dict, test_id: str) -> str:
    return next(
        element["element_id"]
        for element in observation["interactive_elements"]
        if any(
            candidate.get("locator_type") == "test_id" and candidate.get("locator_value") == test_id
            for candidate in element.get("locator_candidates", [])
        )
    )


def test_planner_loop_reobserves_and_rebinds_after_a_dynamic_document_change(fixture_url):
    host = TrustedHostRuntime()
    try:
        agent = host.open_governed_agent_session(
            authority_envelope=AuthorityEnvelope(
                policy_id="planner-adapter-fixture",
                granted_authorities=(ProvenanceClass.HOST_POLICY,),
                allowed_origins=(_origin(fixture_url),),
                allowed_action_types=("navigate", "fill", "click", "press_key"),
            ),
            agent_id="unfamiliar-planner",
        )
    except StatefulSessionError as exc:
        if exc.failure_kind is SessionFailureKind.BROWSER_STARTUP_FAILURE:
            pytest.skip("Playwright browser binary is unavailable")
        raise
    planner = PlannerAdapter.from_governed_session(agent)
    try:
        capabilities = planner.available_actions()
        assert capabilities.ok
        assert capabilities.result["primary_calls"]["observe"] == "dingdong.observe"

        opened = planner.execute(
            _operation(
                "open-fixture",
                fixture_url,
                {"type": "navigate"},
                [{"type": "url", "url_value": fixture_url, "expectation_id": "fixture-open"}],
            )
        )
        assert opened.ok and opened.result["receipt"]["verdict"] == "VERIFIED"

        observation = planner.observe()
        assert observation.ok
        old_handle = observation.result["observation_handle"]
        old_element_id = _element_id(observation.result["observation"], "text-input")

        changed_url = fixture_url + "?dynamic-page-change"
        changed = planner.execute(_operation("change-document", changed_url, {"type": "navigate"}))
        assert changed.ok

        stale = planner.execute(
            _operation(
                "fill-stale-target",
                changed_url,
                {
                    "type": "fill",
                    "locator": {"strategy": "test_id", "value": "text-input"},
                    "text": "stale",
                },
            ),
            observation_handle=old_handle,
            element_id=old_element_id,
        )
        # The default mutation-arbitration policy rejects the pre-change
        # observation before dispatch. It returns the same bounded recovery
        # path as an execution receipt with stale_observation_reference.
        assert not stale.ok
        assert stale.error["code"] == "mutation_conflict"
        assert stale.recovery["tool"] == "dingdong.reobserve"
        assert stale.recovery["arguments"] == {
            "previous_observation_handle": old_handle,
            "previous_element_id": old_element_id,
        }

        rebound = planner.reobserve(
            previous_observation_handle=old_handle,
            previous_element_id=old_element_id,
        )
        assert rebound.ok
        new_handle = rebound.result["observation_handle"]
        new_element_id = _element_id(rebound.result["observation"], "text-input")
        assert rebound.result["recovery"]["rebind_required"] is True

        filled = planner.execute(
            _operation(
                "fill-rebound-target",
                changed_url,
                {
                    "type": "fill",
                    "locator": {"strategy": "test_id", "value": "text-input"},
                    "text": "fresh",
                },
                [
                    {
                        "type": "attribute",
                        "locator": {"strategy": "test_id", "value": "text-input"},
                        "attribute_name": "value",
                        "attribute_value": "fresh",
                        "expectation_id": "fresh-value",
                    }
                ],
            ),
            observation_handle=new_handle,
            element_id=new_element_id,
        )
        assert filled.ok and filled.result["receipt"]["verdict"] == "VERIFIED"

    finally:
        agent.close()
