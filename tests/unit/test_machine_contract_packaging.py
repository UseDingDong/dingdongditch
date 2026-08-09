from __future__ import annotations

import subprocess
import sys
import zipfile
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _venv_cli(venv: Path) -> Path:
    return venv / (
        "Scripts/dingdongditch.exe" if sys.platform == "win32" else "bin/dingdongditch"
    )


def test_machine_contract_resources_work_from_installed_wheel(tmp_path):
    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(ROOT),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("dingdongditch-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "dingdongditch/schemas/plan-document.schema.json" in names
    assert "dingdongditch/adapters/openai.py" in names
    assert "dingdongditch/adapters/anthropic.py" in names
    assert "dingdongditch/adapters/gemini.py" in names

    venv = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    python = _venv_python(venv)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel)],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    probe = (
        "import dingdongditch as d; "
        "assert d.execution_schema()['title'] == 'DingDongDitch PlanDocument'; "
        "assert d.execution_plan_tool()['name'] == 'execute_browser_plan'; "
        "assert d.published_schema_resource('operation')['title'] == 'DingDongDitch Operation'"
    )
    subprocess.run([str(python), "-c", probe], check=True, cwd=tmp_path)
    schema_cli = subprocess.run(
        [str(_venv_cli(venv)), "schema", "operation"],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert json.loads(schema_cli.stdout)["title"] == "DingDongDitch Operation"
