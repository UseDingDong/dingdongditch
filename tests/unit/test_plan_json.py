"""Unit tests: JSON plan loading into real typed contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserEngine,
    BrowserProvider,
)
from dingdongditch.contract.operation import ActionType, LocatorStrategy
from dingdongditch.contract.plan import ExecutionPlan, FailurePolicy
from dingdongditch.contract.target import ConstraintType, NameMatchMode
from dingdongditch.contract.wait import LoadState, WaitConditionType
from dingdongditch.plan_json import (
    PlanLoadError,
    apply_browser_overrides,
    load_plan_file,
    plan_document_from_dict,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples" / "plans" / "basic_navigation.json"


def _minimal_doc(**overrides):
    doc = {
        "browser": {
            "provider": "playwright",
            "engine": "chromium",
            "channel": "bundled",
            "headless": True,
        },
        "plan": {
            "plan_id": "unit-plan",
            "failure_policy": "stop_on_failure",
            "operations": [
                {
                    "operation_id": "nav",
                    "url": "https://example.com/",
                    "action": {"type": "navigate"},
                    "expectations": [],
                }
            ],
        },
    }
    doc.update(overrides)
    return doc


def test_valid_json_parses_into_execution_plan():
    plan = load_plan_file(SAMPLE)
    assert isinstance(plan, ExecutionPlan)
    assert plan.plan_id == "basic-navigation-local-fixture"
    assert plan.failure_policy == FailurePolicy.STOP_ON_FAILURE
    assert plan.browser_config.provider == BrowserProvider.PLAYWRIGHT
    assert plan.browser_config.engine == BrowserEngine.CHROMIUM
    assert plan.browser_config.channel == BrowserChannel.BUNDLED
    assert plan.browser_config.headless is True
    assert len(plan.operations) >= 5
    assert plan.operations[0].action.type == ActionType.NAVIGATE
    assert plan.operations[0].url.startswith("file:")


def test_guarded_operation_parses_current_expectation_contract():
    doc = _minimal_doc()
    operation = doc["plan"]["operations"][0]
    operation["action"] = {
        "type": "click",
        "locator": {"strategy": "css", "value": "#optional"},
    }
    operation["expectations"] = [
        {"type": "element_exists", "locator": {"strategy": "css", "value": "#done"}, "exists": True}
    ]
    operation["guard"] = {
        "when_target_absent": {
            "expectations": [
                {"type": "element_exists", "locator": {"strategy": "css", "value": "#done"}, "exists": True}
            ]
        }
    }
    plan = plan_document_from_dict(doc)
    assert plan.operations[0].guard is not None
    assert len(plan.operations[0].guard.when_target_absent.expectations) == 1


@pytest.mark.parametrize(
    "guard",
    [
        {},
        {"when_target_absent": {}},
        {"when_target_absent": {"expectations": []}},
        {"when_target_absent": {"expectations": [], "unsupported": True}},
        {"unsupported": {}},
    ],
)
def test_malformed_guard_is_rejected(guard):
    doc = _minimal_doc()
    operation = doc["plan"]["operations"][0]
    operation["action"] = {
        "type": "click",
        "locator": {"strategy": "css", "value": "#optional"},
    }
    operation["guard"] = guard
    with pytest.raises(PlanLoadError):
        plan_document_from_dict(doc)


def test_unguarded_plan_remains_backward_compatible():
    plan = plan_document_from_dict(_minimal_doc())
    assert plan.operations[0].guard is None


def test_guard_is_rejected_for_non_target_action():
    doc = _minimal_doc()
    doc["plan"]["operations"][0]["guard"] = {
        "when_target_absent": {
            "expectations": [
                {"type": "url", "url_value": "https://example.com/"}
            ]
        }
    }
    with pytest.raises(PlanLoadError, match="target-based"):
        plan_document_from_dict(doc)


def test_unknown_action_fails_before_browser(tmp_path):
    path = tmp_path / "bad.json"
    doc = _minimal_doc()
    doc["plan"]["operations"][0]["action"] = {"type": "teleport"}
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(PlanLoadError, match="invalid ActionType|teleport"):
        load_plan_file(path)


def test_invalid_engine_fails_before_browser():
    doc = _minimal_doc()
    doc["browser"]["engine"] = "safari"
    with pytest.raises(PlanLoadError, match="invalid BrowserEngine|safari"):
        plan_document_from_dict(doc)


def test_invalid_channel_fails_before_browser():
    doc = _minimal_doc()
    doc["browser"]["channel"] = "chrome"
    with pytest.raises(Exception) as excinfo:
        plan_document_from_dict(doc)
    # BrowserConfig.validate rejects unsupported channel.
    assert "channel" in str(excinfo.value).lower() or "unsupported" in str(
        excinfo.value
    ).lower()


def test_missing_required_fields_fail():
    with pytest.raises(PlanLoadError, match="missing plan"):
        plan_document_from_dict({"browser": {"engine": "chromium"}})
    with pytest.raises(PlanLoadError, match="missing plan_id"):
        plan_document_from_dict(
            {"plan": {"operations": [{"operation_id": "x", "url": "https://a", "action": {"type": "navigate"}}]}}
        )
    with pytest.raises(PlanLoadError, match="missing action"):
        plan_document_from_dict(
            {
                "plan": {
                    "plan_id": "p",
                    "operations": [{"operation_id": "x", "url": "https://a"}],
                }
            }
        )


def test_unknown_fields_fail_closed():
    doc = _minimal_doc()
    doc["extra"] = True
    with pytest.raises(PlanLoadError, match="unknown fields"):
        plan_document_from_dict(doc)
    doc = _minimal_doc()
    doc["plan"]["operations"][0]["action"]["guess"] = True
    with pytest.raises(PlanLoadError, match="unknown fields"):
        plan_document_from_dict(doc)


def test_wait_for_conditions_deserialize():
    doc = _minimal_doc()
    doc["plan"]["operations"] = [
        {
            "operation_id": "w1",
            "url": "https://example.com/",
            "action": {
                "type": "wait_for",
                "wait_condition": {
                    "type": "load_state",
                    "load_state": "load",
                },
            },
        },
        {
            "operation_id": "w2",
            "url": "https://example.com/",
            "action": {
                "type": "wait_for",
                "wait_condition": {
                    "type": "text_present",
                    "locator": {"strategy": "test_id", "value": "x"},
                    "text_value": "hi",
                    "text_match": "exact",
                },
            },
        },
        {
            "operation_id": "w3",
            "url": "https://example.com/",
            "action": {
                "type": "wait_for",
                "wait_condition": {
                    "type": "attribute_equals",
                    "locator": {"strategy": "css", "value": "#a"},
                    "attribute_name": "data-x",
                    "attribute_value": "1",
                },
            },
        },
    ]
    plan = plan_document_from_dict(doc)
    assert plan.operations[0].action.wait_condition.type == WaitConditionType.LOAD_STATE
    assert plan.operations[0].action.wait_condition.load_state == LoadState.LOAD
    assert plan.operations[1].action.wait_condition.type == WaitConditionType.TEXT_PRESENT
    assert (
        plan.operations[2].action.wait_condition.type
        == WaitConditionType.ATTRIBUTE_EQUALS
    )


def test_target_types_deserialize():
    doc = _minimal_doc()
    doc["plan"]["operations"] = [
        {
            "operation_id": "click",
            "url": "https://example.com/",
            "action": {
                "type": "click",
                "locator": {
                    "strategy": "role_name",
                    "role": "button",
                    "name": "Go",
                    "name_match": "exact",
                    "constraints": [
                        {"type": "visible", "visible": True},
                        {
                            "type": "within",
                            "within": {"strategy": "test_id", "value": "nav"},
                        },
                    ],
                },
            },
        }
    ]
    plan = plan_document_from_dict(doc)
    loc = plan.operations[0].action.locator
    assert loc.strategy == LocatorStrategy.ROLE_NAME
    assert loc.name_match == NameMatchMode.EXACT
    assert loc.constraints[0].type == ConstraintType.VISIBLE
    assert loc.constraints[1].type == ConstraintType.WITHIN


def test_cli_engine_override():
    plan = plan_document_from_dict(_minimal_doc())
    assert plan.browser_config.engine == BrowserEngine.CHROMIUM
    overridden = apply_browser_overrides(plan, engine="firefox")
    assert overridden.browser_config.engine == BrowserEngine.FIREFOX
    assert overridden.browser_config.channel == BrowserChannel.BUNDLED


def test_headed_headless_override():
    plan = plan_document_from_dict(_minimal_doc())
    assert plan.browser_config.headless is True
    headed = apply_browser_overrides(plan, headless=False)
    assert headed.browser_config.headless is False
    headless = apply_browser_overrides(headed, headless=True)
    assert headless.browser_config.headless is True


def test_no_silent_browser_fallback_on_bad_override():
    plan = plan_document_from_dict(_minimal_doc())
    with pytest.raises(PlanLoadError, match="BrowserEngine"):
        apply_browser_overrides(plan, engine="safari")


def test_invalid_json_structured_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PlanLoadError) as excinfo:
        load_plan_file(path)
    assert excinfo.value.code == "invalid_json"
    assert "invalid JSON" in str(excinfo.value)


def test_missing_file_structured_error(tmp_path):
    path = tmp_path / "absent.json"
    with pytest.raises(PlanLoadError) as excinfo:
        load_plan_file(path)
    assert excinfo.value.code == "missing_file"
