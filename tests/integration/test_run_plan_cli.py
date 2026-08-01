"""Integration tests: website-neutral run-plan CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dingdongditch.cli import (
    EXIT_EXECUTION_FAILED,
    EXIT_INVALID_INPUT,
    EXIT_NOT_VERIFIED,
    EXIT_SUCCESS,
    main,
)
from dingdongditch.contract.browser import BrowserEngine
from dingdongditch.plan_json import load_plan_file

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples" / "plans" / "basic_navigation.json"


def _write_plan(tmp_path: Path, *, url: str, **plan_tweaks) -> Path:
    doc = {
        "browser": {
            "provider": "playwright",
            "engine": "chromium",
            "channel": "bundled",
            "headless": True,
        },
        "plan": {
            "plan_id": plan_tweaks.get("plan_id", "cli-fixture-plan"),
            "failure_policy": "stop_on_failure",
            "operations": plan_tweaks.get(
                "operations",
                [
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
                    },
                    {
                        "operation_id": "fill",
                        "url": url,
                        "action": {
                            "type": "fill",
                            "locator": {"strategy": "test_id", "value": "text-input"},
                            "text": "cli",
                        },
                        "expectations": [
                            {
                                "type": "attribute",
                                "locator": {
                                    "strategy": "test_id",
                                    "value": "text-input",
                                },
                                "attribute_name": "value",
                                "attribute_value": "cli",
                            }
                        ],
                    },
                ],
            ),
        },
    }
    if "browser" in plan_tweaks:
        doc["browser"].update(plan_tweaks["browser"])
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
    ids=["chromium", "firefox", "webkit"],
)
def test_valid_local_fixture_plan_executes(tmp_path, fixture_url, engine):
    plan_path = _write_plan(tmp_path, url=fixture_url)
    out = tmp_path / f"receipt-{engine.value}.json"
    code = main(
        [
            "run-plan",
            str(plan_path),
            "--engine",
            engine.value,
            "--headless",
            "--output",
            str(out),
        ]
    )
    assert code == EXIT_SUCCESS
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["plan_verdict"] == "VERIFIED"
    assert data["browser_session_id"]
    assert data["context_id"]
    assert data["page_id"]
    assert data["browser"]["engine"] == engine.value
    ids = {
        (s["browser_session_id"], s["context_id"], s["page_id"])
        for s in data["steps"]
        if s["attempted"]
    }
    assert len(ids) == 1


def test_sample_basic_navigation_json_executes_chromium():
    code = main(["run-plan", str(SAMPLE), "--engine", "chromium", "--headless"])
    assert code == EXIT_SUCCESS


def test_receipt_output_contains_stable_lifecycle_ids(tmp_path, fixture_url):
    plan_path = _write_plan(tmp_path, url=fixture_url)
    out = tmp_path / "receipt.json"
    assert main(["run-plan", str(plan_path), "--output", str(out)]) == EXIT_SUCCESS
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.2.0"
    assert data["browser_session_id"]
    assert data["context_id"]
    assert data["page_id"]
    attempted = [s for s in data["steps"] if s["attempted"]]
    assert attempted
    assert all(
        s["browser_session_id"] == data["browser_session_id"]
        and s["context_id"] == data["context_id"]
        and s["page_id"] == data["page_id"]
        for s in attempted
    )


def test_headed_and_headless_override(tmp_path, fixture_url):
    plan_path = _write_plan(
        tmp_path, url=fixture_url, browser={"headless": True}
    )
    out_h = tmp_path / "headed.json"
    # Headed may be slow in CI; still exercise override path on chromium.
    code = main(
        [
            "run-plan",
            str(plan_path),
            "--headed",
            "--output",
            str(out_h),
        ]
    )
    assert code == EXIT_SUCCESS
    headed = json.loads(out_h.read_text(encoding="utf-8"))
    assert headed["browser"]["headless"] is False

    out_l = tmp_path / "headless.json"
    code = main(
        [
            "run-plan",
            str(plan_path),
            "--headless",
            "--output",
            str(out_l),
        ]
    )
    assert code == EXIT_SUCCESS
    headless = json.loads(out_l.read_text(encoding="utf-8"))
    assert headless["browser"]["headless"] is True


def test_engine_override_in_receipt(tmp_path, fixture_url):
    plan_path = _write_plan(
        tmp_path, url=fixture_url, browser={"engine": "chromium"}
    )
    out = tmp_path / "ff.json"
    code = main(
        [
            "run-plan",
            str(plan_path),
            "--engine",
            "firefox",
            "--output",
            str(out),
        ]
    )
    assert code == EXIT_SUCCESS
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["browser"]["engine"] == "firefox"


def test_not_verified_returns_documented_code(tmp_path, fixture_url):
    plan_path = _write_plan(
        tmp_path,
        url=fixture_url,
        operations=[
            {
                "operation_id": "nav",
                "url": fixture_url,
                "action": {"type": "navigate"},
                "expectations": [
                    {
                        "type": "url",
                        "url_value": "index.html",
                        "url_match": "contains",
                    }
                ],
            },
            {
                "operation_id": "wait-never",
                "url": fixture_url,
                "action": {
                    "type": "wait_for",
                    "wait_timeout_ms": 200,
                    "wait_condition": {
                        "type": "text_present",
                        "locator": {"strategy": "test_id", "value": "result-item"},
                        "text_value": "this-text-never-appears-xyz",
                        "text_match": "exact",
                    },
                },
                "expectations": [],
            },
        ],
    )
    code = main(["run-plan", str(plan_path)])
    assert code == EXIT_NOT_VERIFIED


def test_execution_failed_returns_documented_code(tmp_path, fixture_url):
    plan_path = _write_plan(
        tmp_path,
        url=fixture_url,
        operations=[
            {
                "operation_id": "nav",
                "url": fixture_url,
                "action": {"type": "navigate"},
                "expectations": [
                    {
                        "type": "url",
                        "url_value": "index.html",
                        "url_match": "contains",
                    }
                ],
            },
            {
                "operation_id": "ambiguous-click",
                "url": fixture_url,
                "action": {
                    "type": "click",
                    "locator": {
                        "strategy": "test_id",
                        "value": "ambiguous-target",
                    },
                },
                "expectations": [],
            },
        ],
    )
    code = main(["run-plan", str(plan_path)])
    assert code == EXIT_EXECUTION_FAILED


def test_execution_failed_from_setup_invalid_channel(tmp_path, fixture_url):
    """Unsupported channel fails closed before/at setup with non-success code."""
    doc = {
        "browser": {
            "provider": "playwright",
            "engine": "chromium",
            "channel": "msedge",
            "headless": True,
        },
        "plan": {
            "plan_id": "bad-channel",
            "operations": [
                {
                    "operation_id": "nav",
                    "url": fixture_url,
                    "action": {"type": "navigate"},
                    "expectations": [],
                }
            ],
        },
    }
    path = tmp_path / "bad-channel.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    code = main(["run-plan", str(path)])
    assert code == EXIT_INVALID_INPUT


def test_invalid_json_concise_error(tmp_path, capsys):
    path = tmp_path / "x.json"
    path.write_text("{", encoding="utf-8")
    code = main(["run-plan", str(path)])
    assert code == EXIT_INVALID_INPUT
    err = capsys.readouterr().err
    assert "invalid_json" in err
    assert "Traceback" not in err


def test_missing_file_concise_error(tmp_path, capsys):
    code = main(["run-plan", str(tmp_path / "nope.json")])
    assert code == EXIT_INVALID_INPUT
    err = capsys.readouterr().err
    assert "missing_file" in err
    assert "Traceback" not in err


def test_unknown_action_fails_before_browser(tmp_path, fixture_url, capsys):
    path = _write_plan(
        tmp_path,
        url=fixture_url,
        operations=[
            {
                "operation_id": "bad",
                "url": fixture_url,
                "action": {"type": "explode"},
            }
        ],
    )
    code = main(["run-plan", str(path)])
    assert code == EXIT_INVALID_INPUT
    err = capsys.readouterr().err
    assert "explode" in err or "ActionType" in err


def test_repeated_cli_executions_no_leak(tmp_path, fixture_url):
    plan_path = _write_plan(tmp_path, url=fixture_url)
    session_ids = []
    for i in range(3):
        out = tmp_path / f"r{i}.json"
        code = main(["run-plan", str(plan_path), "--output", str(out)])
        assert code == EXIT_SUCCESS
        data = json.loads(out.read_text(encoding="utf-8"))
        session_ids.append(data["browser_session_id"])
    assert len(set(session_ids)) == 3


def test_subprocess_cli_module_entry(tmp_path, fixture_url):
    plan_path = _write_plan(tmp_path, url=fixture_url)
    proc = subprocess.run(
        [sys.executable, "-m", "dingdongditch", "run-plan", str(plan_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == EXIT_SUCCESS
    assert "VERIFIED" in proc.stdout


def test_sample_plan_loads_without_browser():
    plan = load_plan_file(SAMPLE)
    assert plan.browser_config.engine == BrowserEngine.CHROMIUM
    assert all(op.url.startswith("file:") for op in plan.operations)
