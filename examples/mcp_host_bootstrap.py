"""Minimal trusted-host bootstrap for ``dingdongditch mcp-stdio``.

Run with:
    dingdongditch mcp-stdio --bootstrap examples.mcp_host_bootstrap:build --principal local-agent

The values below are host configuration, not MCP tool arguments. Replace the
example origin and policy with the application owner's reviewed policy.
"""

from __future__ import annotations

from dingdongditch import AuthorityEnvelope, GovernedAgentSession, ProvenanceClass, TrustedHostRuntime


def build(principal: str) -> GovernedAgentSession:
    policy = AuthorityEnvelope(
        policy_id="example-mcp-policy",
        granted_authorities=(ProvenanceClass.HOST_POLICY, ProvenanceClass.AGENT_REASONING),
        allowed_origins=("https://example.com",),
        allowed_action_types=("navigate", "click", "fill"),
        require_preparation_for=("click",),
        max_action_count=20,
    )
    return TrustedHostRuntime().open_governed_agent_session(
        authority_envelope=policy,
        agent_id=principal,
    )
