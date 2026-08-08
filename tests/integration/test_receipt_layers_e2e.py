"""Formal receipt/evidence/artifact boundary coverage."""

from __future__ import annotations

import json

from dingdongditch import (
    Action, ActionType, Expectation, ExpectationType, Operation,
    ScreenshotConfig, ScreenshotPolicy, Verdict, execute_operation,
)


def test_receipt_exposes_nonduplicating_three_layers(fixture_url, tmp_path):
    receipt = execute_operation(
        Operation(
            "layered", fixture_url, Action(ActionType.NAVIGATE),
            expectations=[Expectation(ExpectationType.URL, url_value=fixture_url)],
            screenshot_config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS,
                artifact_root=str(tmp_path),
            ),
        )
    )
    assert receipt.verdict is Verdict.VERIFIED
    layered = receipt.to_layered_dict()
    assert set(layered) == {"core_receipt", "bounded_evidence", "artifacts"}
    core = layered["core_receipt"]
    assert core["operation_id"] == "layered"
    assert "action_evidence" not in core
    assert core["timing"]["total_ms"] >= 0
    assert layered["bounded_evidence"]["signals"]
    artifact = layered["artifacts"][0]
    assert artifact["kind"] == "screenshot"
    assert artifact["status"] == "available"
    assert artifact["filename"].endswith(".png")
    serialized = json.dumps(receipt.to_dict())
    assert str(tmp_path) not in serialized
    assert "artifact_path" not in serialized
    assert receipt.action_evidence["artifact_ids"] == [artifact["artifact_id"]]
