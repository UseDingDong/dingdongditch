from __future__ import annotations

import json

from dingdongditch import (
    Action, ActionType, Expectation, ExpectationType, Locator, LocatorStrategy,
    NetworkArtifactRequest, NetworkUrlMatchMode, Operation, TrustedDownloadConfig,
    Verdict, execute_operation,
)


def test_post_network_assertion_and_opt_in_artifact_are_verified(fixture_url, tmp_path):
    operation = Operation(
        operation_id="post-network",
        url=fixture_url,
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="network-post-control"),
        ),
        expectations=[Expectation(
            type=ExpectationType.NETWORK,
            network_url_substring="/api/checkout",
            network_url_match=NetworkUrlMatchMode.PATH_EXACT,
            network_method="POST",
            network_status=200,
            network_max_elapsed_ms=5_000,
        )],
        network_artifact=NetworkArtifactRequest(max_records=8),
    )
    receipt = execute_operation(
        operation,
        trusted_download_config=TrustedDownloadConfig(artifact_root=str(tmp_path)),
    )
    assert receipt.verdict is Verdict.VERIFIED, receipt.to_dict()
    artifact = receipt.artifacts[0]
    assert str(tmp_path) not in json.dumps(artifact)
    trace = json.loads((tmp_path / "network-traces" / artifact["filename"]).read_text())
    assert "fixture-secret" not in json.dumps(trace)
    assert trace["headers_included"] is False
    assert trace["bodies_included"] is False
