"""Protocol-level hardening checks for the optional stdio adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_stdio_malformed_json_isolated_from_protocol_stdout(tmp_path):
    """A noisy host bootstrap and malformed request cannot corrupt MCP stdout."""
    bootstrap = tmp_path / "noisy_mcp_host.py"
    bootstrap.write_text(
        "from __future__ import annotations\n"
        "import sys\n"
        "from dingdongditch import AuthorityEnvelope, GovernedAgentSession, ProvenanceClass, TrustedHostRuntime\n"
        "def build(principal: str) -> GovernedAgentSession:\n"
        "    print('BOOTSTRAP_PRIVATE_SENTINEL')\n"
        "    return TrustedHostRuntime().open_governed_agent_session(\n"
        "        authority_envelope=AuthorityEnvelope(\n"
        "            policy_id='stdio-protocol',\n"
        "            granted_authorities=(ProvenanceClass.HOST_POLICY,),\n"
        "            allowed_origins=('https://example.test',),\n"
        "            allowed_action_types=('navigate',),\n"
        "        ),\n"
        "        agent_id=principal,\n"
        "    )\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(tmp_path) + os.pathsep + environment.get("PYTHONPATH", "")
    request_stream = "\n".join(
        [
            '{"jsonrpc":"2.0",',  # malformed JSON-RPC; server must recover safely.
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "mcp-adversarial-test", "version": "1"},
                    },
                }
            ),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            "",
        ]
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "dingdongditch",
            "mcp-stdio",
            "--bootstrap",
            "noisy_mcp_host:build",
            "--principal",
            "stdio-agent",
        ],
        input=request_stream,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0
    assert "BOOTSTRAP_PRIVATE_SENTINEL" not in completed.stdout
    assert "BOOTSTRAP_PRIVATE_SENTINEL" in completed.stderr
    messages = [json.loads(line) for line in completed.stdout.splitlines() if line]
    assert messages
    assert all(message["jsonrpc"] == "2.0" for message in messages)
    # SDK 2.0.0 is allowed to report the malformed record as a parse-error
    # response or to drop it before dispatch; the security invariant is that
    # the following valid request still works and no non-protocol text leaks.
    assert any(message.get("id") == 2 and "result" in message for message in messages)
