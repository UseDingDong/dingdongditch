from __future__ import annotations

from copy import deepcopy

from dingdongditch import chain_receipt, hash_receipt, verify_receipt_chain, verify_receipt_hash


def _receipt(identifier: str) -> dict:
    return {
        "schema_version": "1.8.0", "operation_id": identifier, "verdict": "VERIFIED",
        "action_type": "click", "target_locator": {"strategy": "test_id", "value": "send"},
        "target_resolution": {"final_candidate_count": 1}, "target_url": "https://example.test/form",
        "execution_status": "completed", "failure_kind": None, "action_executed_successfully": True,
        "action_evidence": {"dispatch": "ok"}, "page_precondition": None,
        "authority_decision": {"policy_id": "host", "policy_hash": "policy-digest", "outcome": "AUTHORIZED"},
        "transaction": None, "quorum_verification": None,
        "expectation_results": [{"expectation_id": "dom", "result": "pass"}],
        "freshness": {"policy_max_age_ms": 1, "stale_signal_ids": []},
        "expectation_evidence": [], "evidence": [{"signal_id": "dom", "payload": {"text": "ok"}}],
        "artifacts": [{"artifact_id": "download-1", "sha256": "artifact-checksum"}],
        "runtime_version": "0.4.1", "browser": {"engine": "chromium", "channel": "bundled", "browser_session_id": "s", "context_id": "c", "page_id": "p"},
    }


def test_receipt_hash_is_deterministic_and_chain_is_tamper_evident():
    first = _receipt("one")
    assert hash_receipt(first) == hash_receipt(deepcopy(first))
    first = chain_receipt(first)
    second = chain_receipt(_receipt("two"), previous_receipt_hash=first["receipt_chain"]["receipt_hash"])
    assert verify_receipt_hash(first) and verify_receipt_hash(second)
    verified = verify_receipt_chain([first, second])
    assert verified.valid and verified.head == second["receipt_chain"]["receipt_hash"]

    altered_first = deepcopy(first)
    altered_first["evidence"][0]["payload"]["text"] = "tampered"
    assert not verify_receipt_chain([altered_first, second]).valid


def test_policy_and_artifact_changes_participate_and_legacy_is_explicit():
    receipt = chain_receipt(_receipt("one"))
    changed_policy = deepcopy(receipt)
    changed_policy["authority_decision"]["policy_hash"] = "changed"
    assert not verify_receipt_hash(changed_policy)

    changed_artifact = deepcopy(receipt)
    changed_artifact["artifacts"][0]["sha256"] = "changed"
    assert not verify_receipt_hash(changed_artifact)

    legacy = _receipt("legacy")
    assert not verify_receipt_chain([legacy]).valid
    assert verify_receipt_chain([legacy], allow_legacy=True).valid
