"""Black-box MCP stdio smoke against an installed DingDongDitch wheel."""

from __future__ import annotations

import anyio
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def test_installed_wheel_serves_governed_mcp_stdio_to_external_client(tmp_path, fixture_url):
    """An external MCP client discovers, executes, receives, and disconnects.

    The test deliberately starts ``python -m dingdongditch`` from an installed
    wheel and imports the host bootstrap from a separate temporary directory.
    It never imports the source checkout in the server child.
    """
    pytest.importorskip("mcp")
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from dingdongditch.mcp import MCP_PROTOCOL_REVISION

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

    origin = fixture_url.rsplit("/", 1)[0]
    bootstrap = tmp_path / "external_mcp_host.py"
    bootstrap.write_text(
        "from __future__ import annotations\n"
        "import os\n"
        "from dingdongditch import AuthorityEnvelope, GovernedAgentSession, ProvenanceClass, TrustedHostRuntime\n"
        "def build(principal: str) -> GovernedAgentSession:\n"
        "    origin = os.environ['DINGDONG_MCP_TEST_ORIGIN']\n"
        "    return TrustedHostRuntime().open_governed_agent_session(\n"
        "        authority_envelope=AuthorityEnvelope(\n"
        "            policy_id='installed-mcp-smoke',\n"
        "            granted_authorities=(ProvenanceClass.HOST_POLICY,),\n"
        "            allowed_origins=(origin,),\n"
        "            allowed_action_types=('navigate',),\n"
        "        ),\n"
        "        agent_id=principal,\n"
        "    )\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(tmp_path)
    environment["DINGDONG_MCP_TEST_ORIGIN"] = origin

    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=str(python),
            args=[
                "-m", "dingdongditch", "mcp-stdio",
                "--bootstrap", "external_mcp_host:build",
                "--principal", "installed-mcp-agent",
            ],
            env=environment,
            cwd=str(tmp_path),
        )
        async with Client(stdio_client(parameters), mode=MCP_PROTOCOL_REVISION) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert {"dingdong.get_contract", "dingdong.observe", "dingdong.execute"} <= names
            contract = await client.call_tool("dingdong.get_contract", {})
            assert not contract.is_error
            assert contract.structured_content["machine_contract"]["title"] == "DingDongDitch PlanDocument"
            spoof = await client.call_tool(
                "dingdong.observe",
                {"authenticated_agent_id": "spoofed-principal"},
            )
            assert spoof.is_error
            assert spoof.structured_content["error"]["code"] == "invalid_arguments"
            raw = await client.call_tool("dingdong.raw_execute_plan", {})
            assert raw.is_error
            assert raw.structured_content["error"]["code"] == "unknown_tool"
            result = await client.call_tool(
                "dingdong.execute",
                {
                    "operation": {
                        "operation_id": "installed-mcp-navigation",
                        "url": fixture_url,
                        "action": {"type": "navigate"},
                        "expectations": [
                            {
                                "type": "url",
                                "url_value": fixture_url,
                                "expectation_id": "destination",
                            }
                        ],
                    }
                },
            )
            assert not result.is_error
            assert result.structured_content["verdict"] == "VERIFIED"
            assert "session_id" not in result.structured_content
            assert result.structured_content["receipt"]["receipt_chain"]["session_id"]

    anyio.run(exercise)
