"""Structural tests for the generic host ExecutionPlan example."""

from __future__ import annotations

import ast
from pathlib import Path

from dingdongditch.contract.browser import BrowserChannel, BrowserEngine, BrowserProvider
from dingdongditch.contract.plan import ExecutionPlan, FailurePolicy
from examples.host_execution_plan import build_host_plan

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "host_execution_plan.py"


def _calls_of(path: Path, name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                count += 1
            elif isinstance(func, ast.Attribute) and func.attr == name:
                count += 1
    return count


def test_host_example_builds_execution_plan():
    plan = build_host_plan("http://127.0.0.1:9/index.html")
    assert isinstance(plan, ExecutionPlan)
    assert plan.plan_id == "host-execution-plan-example"
    assert plan.failure_policy == FailurePolicy.STOP_ON_FAILURE
    assert [o.action.type.value for o in plan.operations] == ["navigate", "fill"]
    assert plan.operations[1].action.text == "host-authored"
    assert plan.browser_config.provider == BrowserProvider.PLAYWRIGHT
    assert plan.browser_config.engine == BrowserEngine.CHROMIUM
    assert plan.browser_config.channel == BrowserChannel.BUNDLED
    plan.validate()


def test_host_example_source_uses_execute_plan_not_operation_chain():
    assert _calls_of(EXAMPLE, "execute_plan") >= 1
    assert _calls_of(EXAMPLE, "execute_operation") == 0
    src = EXAMPLE.read_text(encoding="utf-8")
    assert "ExecutionPlan" in src
    assert "PlaywrightBackend" not in src
    assert "amazon" not in src.lower()
    assert "youtube" not in src.lower()
    assert "filetron" not in src.lower()


def test_no_site_specific_visible_demos_remain():
    examples = ROOT / "examples"
    forbidden = {
        "amazon_visible_demo.py",
        "youtube_visible_demo.py",
        "youtube_constrained_locator_demo.py",
        "live_demo_support.py",
    }
    present = {p.name for p in examples.glob("*.py")}
    assert forbidden.isdisjoint(present)
