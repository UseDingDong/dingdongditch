from examples.complete_governance_demo import run_demo


def test_complete_all_ten_governance_demo():
    assert run_demo() == {
        "signed_speculation_selected": True,
        "parent_committed_once": True,
        "human_mutation_rejected_stale_commit": True,
        "reprepared_commit_verified": True,
        "same_identity_across_models": True,
        "old_controller_rejected": True,
        "receipt_chain_checkpointed": True,
        "offline_independent_attestation_verified": True,
        "altered_receipt_rejected": True,
    }
