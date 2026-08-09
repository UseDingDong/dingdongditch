from __future__ import annotations

from examples.governed_hot_handoff_demo import run_demo


def test_deterministic_governed_hot_handoff_demo():
    result = run_demo()
    assert result == {
        "same_page_preserved": True,
        "old_agent_rejected": True,
        "commit_succeeded": True,
        "quorum_verdict": "VERIFIED",
        "receipt_chain_valid": True,
        "handoff_epoch": 1,
    }
