"""Deterministic no-key local MCP stdio demonstration using the official SDK.

The browser runtime lives in the child MCP server process.  That is both the
real transport boundary and necessary because Playwright's synchronous API
must not run in the async client event loop.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import anyio

from dingdongditch.mcp import MCP_PROTOCOL_REVISION


class _Fixture(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        body = b"<!doctype html><title>DingDong MCP demo</title><button data-testid='ready'>Ready</button>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


def run_demo() -> dict:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Fixture)
    Thread(target=httpd.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{httpd.server_port}"
    try:
        with TemporaryDirectory(prefix="dingdong-mcp-demo-") as directory:
            bootstrap = Path(directory) / "demo_host.py"
            bootstrap.write_text(
                "from __future__ import annotations\n"
                "import os\n"
                "from dingdongditch import AuthorityEnvelope, GovernedAgentSession, ProvenanceClass, TrustedHostRuntime\n"
                "def build(principal: str) -> GovernedAgentSession:\n"
                "    origin = os.environ['DINGDONG_MCP_DEMO_ORIGIN']\n"
                "    return TrustedHostRuntime().open_governed_agent_session(\n"
                "        authority_envelope=AuthorityEnvelope(\n"
                "            policy_id='local-mcp-demo',\n"
                "            granted_authorities=(ProvenanceClass.HOST_POLICY,),\n"
                "            allowed_origins=(origin,),\n"
                "            allowed_action_types=('navigate',),\n"
                "        ),\n"
                "        agent_id=principal,\n"
                "    )\n",
                encoding="utf-8",
            )
            child_environment = dict(os.environ)
            child_environment["DINGDONG_MCP_DEMO_ORIGIN"] = origin
            child_environment["PYTHONPATH"] = directory + os.pathsep + child_environment.get("PYTHONPATH", "")

            async def exercise() -> dict:
                from mcp.client import Client
                from mcp.client.stdio import StdioServerParameters, stdio_client

                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m", "dingdongditch", "mcp-stdio",
                        "--bootstrap", "demo_host:build",
                        "--principal", "local-demo-agent",
                    ],
                    env=child_environment,
                    cwd=str(Path(__file__).resolve().parents[1]),
                )
                async with Client(stdio_client(parameters), mode=MCP_PROTOCOL_REVISION) as client:
                    tools = await client.list_tools()
                    result = await client.call_tool(
                        "dingdong.execute",
                        {
                            "operation": {
                                "operation_id": "local-navigation",
                                "url": origin + "/",
                                "action": {"type": "navigate"},
                                "expectations": [
                                    {"type": "url", "url_value": origin + "/", "expectation_id": "destination"}
                                ],
                            }
                        },
                    )
                    return {
                        "discovered_governed_tools": [tool.name for tool in tools.tools],
                        "mcp_error": result.is_error,
                        "result": result.structured_content,
                    }

            return anyio.run(exercise)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    print(json.dumps(run_demo(), sort_keys=True))
