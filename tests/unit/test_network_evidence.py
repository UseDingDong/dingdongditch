from __future__ import annotations

import json

from dingdongditch.backends.playwright_backend import NetworkRecord, PlaywrightBackend
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.network import NetworkArtifactRequest, NetworkUrlMatchMode
from dingdongditch.contract.download import TrustedDownloadConfig
from dingdongditch.contract.operation import FreshnessPolicy
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.runtime.verifier import evaluate_expectations


class _UnusedBackend:
    pass


def _result(expectation: Expectation, records: list[dict], *, start: int = 100):
    collector = EvidenceCollector("network-test", window_started_at_ms=start)
    return evaluate_expectations(
        backend=_UnusedBackend(),
        expectations=[expectation],
        collector=collector,
        action_started_at_ms=start,
        verification_completed_at_ms=start + 20,
        freshness=FreshnessPolicy(max_age_ms=1_000),
        post_network_payload={"records": records},
        post_url="http://fixture.test/",
    )[0], collector


def _record(*, status: int | None = 200, request_at: int = 101, response_at: int | None = 106):
    return {
        "method": "POST",
        "url": "http://fixture.test/api/checkout?access_token=super-secret",
        "status": status,
        "request_observed": True,
        "request_observed_at_ms": request_at,
        "response_observed_at_ms": response_at,
    }


def _checkout_expectation(**kwargs):
    return Expectation(
        type=ExpectationType.NETWORK,
        network_url_substring="/api/checkout",
        network_url_match=NetworkUrlMatchMode.PATH_EXACT,
        network_method="POST",
        network_status=200,
        **kwargs,
    )


def test_network_response_assertion_is_bounded_and_redacts_query_secrets():
    result, collector = _result(_checkout_expectation(), [_record()])
    assert result.result == "pass"
    signal = collector.signals[-1].payload
    assert signal["matches"][0]["url"] == "http://fixture.test/api/checkout"
    assert "super-secret" not in json.dumps(signal)
    assert "access_token" not in json.dumps(signal)


def test_network_wrong_status_and_missing_request_are_not_verified():
    wrong_status, _ = _result(_checkout_expectation(), [_record(status=500)])
    assert wrong_status.result == "fail"
    assert wrong_status.observed["failure_reason"] == "response_status_mismatch"

    missing, _ = _result(_checkout_expectation(), [])
    assert missing.result == "fail"
    assert missing.observed["failure_reason"] == "no_matching_request"


def test_network_ambiguous_matches_are_indeterminate_instead_of_selecting_one():
    result, _ = _result(_checkout_expectation(), [_record(), _record(request_at=102, response_at=107)])
    assert result.result == "indeterminate"
    assert result.observed["failure_reason"] == "ambiguous_network_evidence"


def test_requested_network_trace_is_external_safe_reference(tmp_path):
    backend = PlaywrightBackend(
        trusted_download_config=TrustedDownloadConfig(artifact_root=str(tmp_path))
    )
    backend._network = [
        NetworkRecord(
            method="POST",
            url="http://fixture.test/api/checkout?authorization=super-secret",
            status=200,
            request_observed_at_ms=100,
            response_observed_at_ms=105,
        )
    ]
    artifact = backend.capture_network_artifact(
        operation_id="checkout",
        action_started_at_ms=99,
        request=NetworkArtifactRequest(max_records=4),
    )
    assert artifact["status"] == "available"
    assert str(tmp_path) not in json.dumps(artifact)
    payload = json.loads((tmp_path / "network-traces" / artifact["filename"]).read_text())
    assert payload["bodies_included"] is False
    assert payload["headers_included"] is False
    assert "super-secret" not in json.dumps(payload)
