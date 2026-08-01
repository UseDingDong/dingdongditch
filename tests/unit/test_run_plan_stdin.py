"""CLI stdin plan loading tests."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dingdongditch.cli import (
    EXIT_INVALID_INPUT,
    EXIT_SUCCESS,
    main,
)
from dingdongditch.plan_json import PlanLoadError, load_plan_json_text, load_plan_stdin


def _minimal_doc(url: str) -> dict:
    return {
        "browser": {
            "provider": "playwright",
            "engine": "chromium",
            "channel": "bundled",
            "headless": True,
        },
        "plan": {
            "plan_id": "stdin-plan",
            "failure_policy": "stop_on_failure",
            "operations": [
                {
                    "operation_id": "nav",
                    "url": url,
                    "action": {"type": "navigate"},
                    "expectations": [
                        {
                            "type": "url",
                            "url_value": "index.html",
                            "url_match": "contains",
                        }
                    ],
                }
            ],
        },
    }


def test_valid_stdin_plan_parses():
    doc = _minimal_doc("https://example.com/index.html")
    plan = load_plan_stdin(io.StringIO(json.dumps(doc)))
    assert plan.plan_id == "stdin-plan"
    assert plan.operations[0].action.type.value == "navigate"


def test_invalid_stdin_json():
    with pytest.raises(PlanLoadError) as excinfo:
        load_plan_stdin(io.StringIO("{nope"))
    assert excinfo.value.code == "invalid_json"


def test_invalid_stdin_contract():
    doc = _minimal_doc("https://example.com/index.html")
    doc["plan"]["operations"][0]["action"] = {"type": "teleport"}
    with pytest.raises(PlanLoadError, match="ActionType|teleport"):
        load_plan_stdin(io.StringIO(json.dumps(doc)))


def test_empty_stdin_fails():
    with pytest.raises(PlanLoadError) as excinfo:
        load_plan_stdin(io.StringIO("   "))
    assert excinfo.value.code == "invalid_json"


def test_stdin_and_file_identical_receipts(tmp_path, fixture_url, monkeypatch):
    doc = _minimal_doc(fixture_url)
    text = json.dumps(doc)
    path = tmp_path / "plan.json"
    path.write_text(text, encoding="utf-8")

    out_file = tmp_path / "file.json"
    out_stdin = tmp_path / "stdin.json"

    assert (
        main(
            [
                "run-plan",
                str(path),
                "--headless",
                "--output",
                str(out_file),
            ]
        )
        == EXIT_SUCCESS
    )

    monkeypatch.setattr(
        "dingdongditch.cli.load_plan_stdin",
        lambda: load_plan_json_text(text, source="stdin"),
    )
    assert (
        main(
            [
                "run-plan",
                "-",
                "--headless",
                "--output",
                str(out_stdin),
            ]
        )
        == EXIT_SUCCESS
    )

    file_data = json.loads(out_file.read_text(encoding="utf-8"))
    stdin_data = json.loads(out_stdin.read_text(encoding="utf-8"))
    assert file_data["plan_verdict"] == "VERIFIED"
    assert stdin_data["plan_verdict"] == "VERIFIED"
    assert file_data["declared_step_count"] == stdin_data["declared_step_count"]
    assert file_data["verified_step_count"] == stdin_data["verified_step_count"]
    assert file_data["schema_version"] == stdin_data["schema_version"]
    # Distinct owned sessions across independent runs.
    assert file_data["browser_session_id"] != stdin_data["browser_session_id"]


def test_stdin_invalid_json_before_browser(monkeypatch, capsys):
    monkeypatch.setattr(
        "dingdongditch.cli.load_plan_stdin",
        lambda: (_ for _ in ()).throw(
            PlanLoadError("invalid JSON in stdin: Expecting value (line 1)", code="invalid_json")
        ),
    )
    code = main(["run-plan", "-"])
    assert code == EXIT_INVALID_INPUT
    err = capsys.readouterr().err
    assert "invalid_json" in err


def test_repeated_stdin_runs_cleanup(tmp_path, fixture_url, monkeypatch):
    doc = _minimal_doc(fixture_url)
    text = json.dumps(doc)
    monkeypatch.setattr(
        "dingdongditch.cli.load_plan_stdin",
        lambda: load_plan_json_text(text, source="stdin"),
    )
    sessions = []
    for i in range(3):
        out = tmp_path / f"r{i}.json"
        assert main(["run-plan", "-", "--output", str(out)]) == EXIT_SUCCESS
        data = json.loads(out.read_text(encoding="utf-8"))
        sessions.append(data["browser_session_id"])
        assert data["context_id"]
        assert data["page_id"]
    assert len(set(sessions)) == 3
