from __future__ import annotations

import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
import pytest

import dingdongditch as dingdong
from dingdongditch.adapters import anthropic, gemini, openai


ROOT = Path(__file__).resolve().parents[2]


def _canonical(url: str = "https://example.com") -> dict[str, object]:
    return {
        "schema_version": dingdong.MACHINE_CONTRACT_VERSION,
        "browser": {"engine": "chromium", "channel": "bundled", "headless": True},
        "plan": {
            "plan_id": "machine-contract-test",
            "operations": [
                {
                    "operation_id": "navigate",
                    "url": url,
                    "action": {"type": "navigate"},
                    "expectations": [],
                }
            ],
        },
    }


def _assert_schema_valid(schema: dict[str, object], value: object) -> None:
    errors = list(Draft202012Validator(schema).iter_errors(value))
    assert not errors, errors[0].message


def test_every_public_schema_is_valid_draft_2020_12_and_matches_resource():
    for name in dingdong.public_schema_names():
        generated = {
            "plan-document": dingdong.plan_document_schema,
            "execution-plan": dingdong.execution_plan_schema,
            "operation": dingdong.operation_schema,
            "observation": dingdong.observation_schema,
            "execution-receipt": dingdong.execution_receipt_schema,
            "plan-receipt": dingdong.plan_receipt_schema,
        }[name]()
        Draft202012Validator.check_schema(generated)
        assert dingdong.published_schema_resource(name) == generated


def test_receipt_schema_versions_match_the_runtime_contracts():
    from dingdongditch.contract.plan import PLAN_RECEIPT_SCHEMA_VERSION
    from dingdongditch.contract.receipt import RECEIPT_SCHEMA_VERSION

    assert dingdong.execution_receipt_schema()["properties"]["schema_version"] == {"const": RECEIPT_SCHEMA_VERSION}
    assert dingdong.plan_receipt_schema()["properties"]["schema_version"] == {"const": PLAN_RECEIPT_SCHEMA_VERSION}


def test_public_plan_fixtures_validate_and_parse_against_canonical_contract(tmp_path):
    for path in (ROOT / "examples" / "plans").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema_version"] = dingdong.MACHINE_CONTRACT_VERSION
        _assert_schema_valid(dingdong.execution_schema(), payload)
        # This checked-in document intentionally contains illustrative POSIX
        # paths.  Parser validation also proves host-local upload authorization,
        # so substitute a real temporary file for the parse/round-trip portion.
        if path.name == "upload_file.json":
            upload = tmp_path / "fixture-upload.txt"
            upload.write_text("fixture", encoding="utf-8")
            action = payload["plan"]["operations"][1]["action"]
            action["file_paths"] = [str(upload)]
            action["allowed_files"] = [str(upload)]
            action.pop("allowed_roots", None)
        document = dingdong.parse_plan_document(payload, plan_path=path)
        serialized = dingdong.serialize_plan_document(document)
        _assert_schema_valid(dingdong.execution_schema(), serialized)
        assert dingdong.parse_plan_document(serialized).plan.plan_id == document.plan.plan_id


def test_schema_and_parser_fail_closed_for_unknown_or_irrelevant_action_fields():
    payload = _canonical()
    action = payload["plan"]["operations"][0]["action"]  # type: ignore[index]
    action["text"] = "not-valid-for-navigate"  # type: ignore[index]
    assert list(Draft202012Validator(dingdong.execution_schema()).iter_errors(payload))
    with pytest.raises(dingdong.ContractValidationError) as excinfo:
        dingdong.parse_plan_document(payload)
    assert excinfo.value.errors[0].code in {"invalid_contract", "invalid_plan"}


def test_fill_variants_constraints_and_structured_version_errors():
    payload = _canonical()
    operation = payload["plan"]["operations"][0]  # type: ignore[index]
    operation.update(
        {
            "action": {
                "type": "fill",
                "locator": {"strategy": "test_id", "value": "field"},
                "text": "safe value",
            }
        }
    )
    _assert_schema_valid(dingdong.execution_schema(), payload)
    assert dingdong.parse_plan_document(payload).plan.operations[0].action.text == "safe value"
    operation["action"]["secret_reference"] = {"reference_id": "host-secret"}  # type: ignore[index]
    assert list(Draft202012Validator(dingdong.execution_schema()).iter_errors(payload))

    bad = {"browser": {}, "plan": {}}
    with pytest.raises(dingdong.ContractValidationError) as excinfo:
        dingdong.parse_plan_document(bad)
    errors = excinfo.value.to_dict()["errors"]
    assert {item["code"] for item in errors} >= {"missing_field"}
    assert any(item["pointer"] == "/schema_version" for item in errors)


def test_canonical_document_is_accepted_by_the_existing_file_loader_and_accumulates_root_errors(tmp_path):
    from dingdongditch.plan_json import load_plan_file

    path = tmp_path / "canonical.json"
    path.write_text(json.dumps(_canonical()), encoding="utf-8")
    assert load_plan_file(path).plan_id == "machine-contract-test"

    with pytest.raises(dingdong.ContractValidationError) as excinfo:
        dingdong.parse_plan_document({"schema_version": "not-supported", "extra": True})
    errors = excinfo.value.to_dict()["errors"]
    assert {item["pointer"] for item in errors} >= {"/schema_version", "/browser", "/plan", "/extra"}


def test_action_schema_covers_the_runtime_action_enum():
    from dingdongditch.contract.operation import ActionType

    action = dingdong.operation_schema()["$defs"]["Action"]
    encoded = json.dumps(action)
    for value in ActionType:
        assert value.value in encoded


def test_machine_contract_covers_nested_frames_network_combobox_webauthn_and_upload(tmp_path):
    upload = tmp_path / "safe.txt"
    upload.write_text("safe", encoding="utf-8")
    payload = _canonical()
    payload["plan"]["screenshot_config"] = {
        "policy": "on_failure",
        "mandatory_redaction": True,
        "sensitive_selectors": ["[data-secret]"],
    }
    operations = payload["plan"]["operations"]  # type: ignore[index]
    operations.extend(  # type: ignore[union-attr]
        [
            {
                "operation_id": "nested-fill",
                "url": "https://example.com",
                "action": {
                    "type": "fill",
                    "locator": {"strategy": "test_id", "value": "field"},
                    "frame_path": [{"strategy": "test_id", "value": "frame"}],
                    "text": "ok",
                },
                "expectations": [
                    {
                        "type": "network",
                        "network_url_substring": "/api/save",
                        "network_method": "POST",
                        "network_response_observed": True,
                    }
                ],
                "webauthn": {"request_id": "request-1", "timeout_ms": 100},
            },
            {
                "operation_id": "combo",
                "url": "https://example.com",
                "action": {
                    "type": "select_combobox_option",
                    "locator": {"strategy": "test_id", "value": "combo"},
                    "combobox": {"query": "a", "expected_option": "Alpha"},
                },
                "expectations": [],
                "network_artifact": {"kind": "sanitized_trace", "max_records": 1},
            },
            {
                "operation_id": "upload",
                "url": "https://example.com",
                "action": {
                    "type": "upload_file",
                    "locator": {"strategy": "test_id", "value": "upload"},
                    "file_paths": [str(upload)],
                    "allowed_files": [str(upload)],
                },
                "expectations": [],
            },
        ]
    )
    _assert_schema_valid(dingdong.execution_schema(), payload)
    document = dingdong.parse_plan_document(payload)
    assert len(document.plan.operations) == 4
    assert document.plan.screenshot_config.mandatory_redaction is True


def test_generic_and_vendor_tools_are_lossless_projections_of_canonical_schema():
    generic = dingdong.execution_plan_tool()
    assert generic["input_schema"] == dingdong.execution_schema()
    assert anthropic.execution_plan_tool() == generic
    assert openai.execution_plan_tool()["function"]["parameters"] == generic["input_schema"]
    assert gemini.execution_plan_tool()["parametersJsonSchema"] == generic["input_schema"]
    assert gemini.execution_plan_tool(api_style="python")["parameters_json_schema"] == generic["input_schema"]
    with pytest.raises(ValueError, match="not a lossless projection"):
        openai.execution_plan_tool(strict=True)


def test_vendor_adapter_modules_have_no_vendor_sdk_or_execution_dependencies():
    adapter_dir = ROOT / "dingdongditch" / "adapters"
    source = "\n".join(path.read_text(encoding="utf-8") for path in adapter_dir.glob("*.py"))
    assert not re.search(r"^\\s*(?:from|import)\\s+openai(?:\\s|\\.|$)", source, re.MULTILINE)
    assert not re.search(r"^\\s*(?:from|import)\\s+anthropic(?:\\s|\\.|$)", source, re.MULTILINE)
    assert "google.genai" not in source
    assert "execute_plan" not in source


def test_public_operation_parser_and_schema_need_no_internal_parser_import():
    operation = {
        "operation_id": "one",
        "url": "https://example.com",
        "action": {"type": "wait_for", "wait_condition": {"type": "load_state", "load_state": "load"}},
        "expectations": [],
    }
    _assert_schema_valid(dingdong.operation_schema(), operation)
    assert dingdong.parse_operation(operation).operation_id == "one"
