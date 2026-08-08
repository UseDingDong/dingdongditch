from __future__ import annotations

import json

from dingdongditch import ActionType, ExpectationType
from dingdongditch.plan_json import load_plan_json_text


def test_upload_json_schema_round_trip(tmp_path):
    file = tmp_path / "authorized.txt"
    file.write_text("safe", encoding="utf-8")
    document = {
        "plan_id": "upload-json",
        "operations": [{
            "operation_id": "upload",
            "url": "https://example.test/upload",
            "action": {
                "type": "upload_file",
                "locator": {"strategy": "test_id", "value": "file"},
                "file_paths": [str(file.resolve())],
                "allowed_files": [str(file.resolve())],
            },
            "expectations": [{
                "type": "upload_file_count",
                "locator": {"strategy": "test_id", "value": "file"},
                "file_count": 1,
            }],
        }],
    }
    plan = load_plan_json_text(json.dumps(document))
    assert plan.operations[0].action.type == ActionType.UPLOAD_FILE
    assert plan.operations[0].expectations[0].type == ExpectationType.UPLOAD_FILE_COUNT


def test_existing_plan_schema_is_unchanged():
    plan = load_plan_json_text(json.dumps({
        "plan_id": "existing",
        "operations": [{
            "operation_id": "nav",
            "url": "https://example.test/",
            "action": {"type": "navigate"},
            "expectations": [],
        }],
    }))
    assert plan.operations[0].action.type == ActionType.NAVIGATE
