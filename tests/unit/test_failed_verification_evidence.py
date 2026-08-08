"""Bounded failure-evidence contracts independent of browser timing."""

from __future__ import annotations

import json

from dingdongditch.evidence.bounded import (
    MAX_DOM_TEXT_CHARS,
    failed_expectation_evidence,
)


def _state(**overrides):
    base = {
        "match_count": 1,
        "exists": True,
        "visible": True,
        "enabled": True,
        "text": "Observed text",
        "tag": "button",
        "role": "button",
        "ancestor_tags": ["section", "main"],
        "child_element_count": 0,
        "attributes": {"id": "submit", "data-testid": "submit"},
        "target_resolution": {"final_candidate_count": 1, "failure_kind": None},
    }
    base.update(overrides)
    return base


def test_text_mismatch_includes_bounded_machine_first_target_evidence():
    evidence = failed_expectation_evidence(
        expectation_type="text",
        expected={"text_value": "Expected text"},
        observed=_state(),
        freshness_ok=True,
    )
    assert evidence["expectation_type"] == "text"
    assert evidence["target"]["resolved_uniquely"] is True
    assert evidence["target"]["structural_fingerprint"]
    assert evidence["structural_evidence"] == {
        "tag": "button", "role": "button", "ancestor_tags": ["section", "main"],
        "child_element_count": 0,
    }
    assert evidence["evidence_fresh"] is True


def test_attribute_secret_and_local_path_are_redacted_and_large_text_truncated():
    evidence = failed_expectation_evidence(
        expectation_type="attribute",
        expected={"attribute_name": "data-secret", "attribute_value": "Bearer abcdefghijklmnopqrstuvwxyz"},
        observed=_state(
            text="x" * (MAX_DOM_TEXT_CHARS * 8),
            attributes={"data-secret": "Bearer abcdefghijklmnopqrstuvwxyz", "data-path": r"C:\\Users\\person\\resume.pdf"},
        ),
        freshness_ok=True,
    )
    attrs = evidence["target"]["safe_attributes"]
    assert attrs["data-secret"] == "<redacted>"
    assert attrs["data-path"] == "<redacted>"
    assert "<truncated:" in evidence["observed"]["text"]
    assert len(json.dumps(evidence)) < 4_000


def test_url_failure_has_no_irrelevant_dom_structure():
    evidence = failed_expectation_evidence(
        expectation_type="url",
        expected={"url_value": "https://expected.test/"},
        observed={"url": "https://actual.test/"},
        freshness_ok=True,
    )
    assert evidence["target"]["resolved_uniquely"] is False
    assert evidence["structural_evidence"] is None


def test_missing_ambiguous_and_stale_evidence_are_explicit():
    missing = failed_expectation_evidence(
        expectation_type="element_visible",
        expected={"visible": True},
        observed={"match_count": 0, "exists": False, "target_resolution": {"failure_kind": "zero_after_primary"}},
        freshness_ok=True,
    )
    ambiguous = failed_expectation_evidence(
        expectation_type="element_visible",
        expected={"visible": True},
        observed={"match_count": 2, "exists": True, "ambiguous": True, "target_resolution": {"failure_kind": "multiple_after_primary"}},
        freshness_ok=True,
    )
    stale = failed_expectation_evidence(
        expectation_type="text",
        expected={"text_value": "x"},
        observed=_state(),
        freshness_ok=False,
    )
    assert missing["target"]["resolved_uniquely"] is False
    assert ambiguous["target"]["resolved_uniquely"] is False
    assert stale["evidence_fresh"] is False
