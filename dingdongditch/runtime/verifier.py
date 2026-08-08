from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from dingdongditch.backends.playwright_backend import PlaywrightBackend, monotonic_ms
from dingdongditch.contract.expectation import (
    Expectation,
    ExpectationType,
    TextMatchMode,
    UrlMatchMode,
)
from dingdongditch.contract.operation import FreshnessPolicy
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.bounded import (
    failed_expectation_evidence,
    sanitize_evidence_value,
)
from dingdongditch.evidence.models import ExpectationResult, SignalKind
from dingdongditch.evidence.network import safe_network_record
from dingdongditch.runtime.freshness import is_signal_fresh_for_verification


def _network_url_matches(expectation: Expectation, value: object) -> bool:
    assert expectation.network_url_substring is not None
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    url_without_query = parsed._replace(query="", fragment="").geturl()
    needle = expectation.network_url_substring
    match = expectation.network_url_match
    if match.value == "contains":
        return needle in url_without_query
    if match.value == "exact":
        return needle == url_without_query
    if match.value == "path_exact":
        return needle == parsed.path
    if match.value == "path_contains":
        return needle in parsed.path
    return False


def _network_matches(
    expectation: Expectation,
    records: list[dict[str, Any]],
    *,
    action_started_at_ms: int,
) -> tuple[str, dict[str, Any]]:
    """Return pass/fail/indeterminate with compact evidence.

    Exactly one post-action record must satisfy a declared assertion.  Picking
    one among multiple requests would be evidence healing, so ambiguity is
    indeterminate instead.
    """
    response_required = expectation.network_response_observed
    if response_required is None:
        response_required = (
            expectation.network_status is not None
            or expectation.network_max_elapsed_ms is not None
        )
    candidates: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    post_matches: list[dict[str, Any]] = []
    for record in records:
        if not _network_url_matches(expectation, record.get("url")):
            continue
        if expectation.network_method and record.get("method") != expectation.network_method:
            continue
        candidates.append(record)
        request_seen = record.get("request_observed") is not False
        response_seen = isinstance(record.get("response_observed_at_ms"), int)
        if expectation.network_request_observed and not request_seen:
            continue
        if response_required is True and not response_seen:
            continue
        if response_required is False and response_seen:
            continue
        if expectation.network_status is not None and record.get("status") != expectation.network_status:
            continue
        if expectation.network_max_elapsed_ms is not None:
            request_at = record.get("request_observed_at_ms")
            response_at = record.get("response_observed_at_ms")
            if (
                not request_seen
                or not isinstance(request_at, int)
                or not isinstance(response_at, int)
                or max(0, response_at - request_at) > expectation.network_max_elapsed_ms
            ):
                continue
        matches.append(record)
        event_at = (
            record.get("request_observed_at_ms")
            if expectation.network_request_observed
            else record.get("response_observed_at_ms")
        )
        if isinstance(event_at, int) and event_at >= action_started_at_ms:
            post_matches.append(record)

    detail = {
        "scanned_count": len(records),
        "candidate_count": len(candidates),
        "matching_count": len(matches),
        "post_action_match_count": len(post_matches),
        "response_required": response_required,
        "matches": [safe_network_record(item) for item in post_matches[:4]],
        "candidates": [safe_network_record(item) for item in candidates[:4]],
        "candidate_evidence_truncated": len(candidates) > 4,
    }
    if len(post_matches) > 1:
        detail["failure_reason"] = "ambiguous_network_evidence"
        return "indeterminate", detail
    if len(post_matches) == 1:
        return "pass", detail
    if not candidates:
        detail["failure_reason"] = "no_matching_request"
    elif matches:
        detail["failure_reason"] = "matching_network_activity_not_post_action"
    elif expectation.network_status is not None and any(
        item.get("response_observed_at_ms") is not None for item in candidates
    ):
        detail["failure_reason"] = "response_status_mismatch"
    elif response_required is True:
        detail["failure_reason"] = "response_not_observed"
    else:
        detail["failure_reason"] = "network_assertion_not_satisfied"
    return "fail", detail


def evaluate_expectations(
    *,
    backend: PlaywrightBackend,
    expectations: list[Expectation],
    collector: EvidenceCollector,
    action_started_at_ms: int,
    verification_completed_at_ms: int,
    freshness: FreshnessPolicy,
    post_network_payload: dict[str, Any],
    post_url: str,
) -> list[ExpectationResult]:
    results: list[ExpectationResult] = []

    for index, expectation in enumerate(expectations):
        eid = expectation.expectation_id or f"exp-{index + 1}"
        expected = expectation.describe()
        observed: dict[str, Any] = {}
        evidence_refs: list[str] = []
        result = "indeterminate"
        explanation = ""
        evidence_ts: int | None = None
        freshness_ok: bool | None = None

        if expectation.type == ExpectationType.URL:
            now = monotonic_ms()
            signal = collector.add(
                kind=SignalKind.URL,
                collected_at_ms=now,
                payload={"url": post_url},
                notes="url expectation check",
            )
            evidence_refs.append(signal.signal_id)
            evidence_ts = signal.collected_at_ms
            freshness_ok = is_signal_fresh_for_verification(
                signal,
                action_started_at_ms=action_started_at_ms,
                verification_completed_at_ms=verification_completed_at_ms,
                policy=freshness,
            )
            observed = {"url": post_url}
            assert expectation.url_value is not None
            if expectation.url_match == UrlMatchMode.EXACT:
                ok = post_url == expectation.url_value
            else:
                ok = expectation.url_value in post_url
            if not freshness_ok:
                result = "indeterminate"
                explanation = "url evidence failed freshness policy"
            else:
                result = "pass" if ok else "fail"
                explanation = "url matched" if ok else "url did not match"

        elif expectation.type in (
            ExpectationType.ELEMENT_EXISTS,
            ExpectationType.ELEMENT_VISIBLE,
            ExpectationType.ELEMENT_IN_VIEWPORT,
            ExpectationType.TEXT,
            ExpectationType.ATTRIBUTE,
            ExpectationType.UPLOAD_FILE_NAMES,
            ExpectationType.UPLOAD_FILE_COUNT,
        ):
            assert expectation.locator is not None
            now = monotonic_ms()
            state = backend.read_element_state(
                expectation.locator,
                frame=expectation.frame,
                frame_path=expectation.frame_path,
                attribute_names=(
                    (expectation.attribute_name,)
                    if expectation.type == ExpectationType.ATTRIBUTE
                    and expectation.attribute_name is not None
                    else ()
                ),
            )
            signal = collector.add(
                kind=SignalKind.DOM_STATE,
                collected_at_ms=now,
                payload={"locator": expectation.locator.describe(), "state": state},
                notes=f"{expectation.type.value} check",
            )
            evidence_refs.append(signal.signal_id)
            evidence_ts = signal.collected_at_ms
            freshness_ok = is_signal_fresh_for_verification(
                signal,
                action_started_at_ms=action_started_at_ms,
                verification_completed_at_ms=verification_completed_at_ms,
                policy=freshness,
            )
            observed = state

            if state.get("ambiguous"):
                result = "indeterminate"
                explanation = "locator matched multiple elements during verification"
            elif not freshness_ok:
                result = "indeterminate"
                explanation = "dom evidence failed freshness policy"
            elif expectation.type == ExpectationType.ELEMENT_EXISTS:
                actual = bool(state.get("exists"))
                ok = actual == bool(expectation.exists)
                result = "pass" if ok else "fail"
                explanation = f"exists={actual}, expected={expectation.exists}"
            elif expectation.type == ExpectationType.ELEMENT_VISIBLE:
                if not state.get("exists"):
                    result = "fail"
                    explanation = "element does not exist"
                else:
                    actual = bool(state.get("visible"))
                    ok = actual == bool(expectation.visible)
                    result = "pass" if ok else "fail"
                    explanation = f"visible={actual}, expected={expectation.visible}"
            elif expectation.type == ExpectationType.ELEMENT_IN_VIEWPORT:
                if not state.get("exists"):
                    result = "fail"
                    explanation = "element does not exist"
                elif state.get("in_viewport") is None:
                    result = "indeterminate"
                    explanation = "viewport state not observable"
                else:
                    actual = bool(state.get("in_viewport"))
                    ok = actual == bool(expectation.in_viewport)
                    result = "pass" if ok else "fail"
                    explanation = (
                        f"in_viewport={actual}, expected={expectation.in_viewport}"
                    )
            elif expectation.type == ExpectationType.TEXT:
                if not state.get("exists"):
                    result = "fail"
                    explanation = "element does not exist"
                else:
                    text = state.get("text") or ""
                    assert expectation.text_value is not None
                    if expectation.text_match == TextMatchMode.EXACT:
                        ok = text == expectation.text_value
                    else:
                        ok = expectation.text_value in text
                    result = "pass" if ok else "fail"
                    explanation = f"text observed={text!r}"
            elif expectation.type == ExpectationType.ATTRIBUTE:
                if not state.get("exists"):
                    result = "fail"
                    explanation = "element does not exist"
                else:
                    attrs = state.get("attributes") or {}
                    actual = attrs.get(expectation.attribute_name)
                    ok = actual == expectation.attribute_value
                    result = "pass" if ok else "fail"
                    explanation = (
                        f"attribute {expectation.attribute_name}={actual!r}, "
                        f"expected={expectation.attribute_value!r}"
                    )
            elif expectation.type == ExpectationType.UPLOAD_FILE_NAMES:
                actual = list(state.get("file_names") or [])
                expected_names = list(expectation.file_names or ())
                ok = actual == expected_names
                result = "pass" if ok else "fail"
                explanation = f"file_names={actual!r}, expected={expected_names!r}"
            elif expectation.type == ExpectationType.UPLOAD_FILE_COUNT:
                actual = state.get("file_count")
                ok = actual == expectation.file_count
                result = "pass" if ok else "fail"
                explanation = f"file_count={actual!r}, expected={expectation.file_count!r}"

        elif expectation.type == ExpectationType.NETWORK:
            now = monotonic_ms()
            records = post_network_payload.get("records", [])
            network_result, detail = _network_matches(
                expectation, records, action_started_at_ms=action_started_at_ms
            )
            signal = collector.add(
                kind=SignalKind.NETWORK,
                collected_at_ms=now,
                payload=detail,
                notes="network expectation check",
            )
            evidence_refs.append(signal.signal_id)
            evidence_ts = signal.collected_at_ms
            freshness_ok = is_signal_fresh_for_verification(
                signal,
                action_started_at_ms=action_started_at_ms,
                verification_completed_at_ms=verification_completed_at_ms,
                policy=freshness,
            )
            observed = {
                "candidate_count": detail["candidate_count"],
                "match_count": detail["matching_count"],
                "post_action_match_count": detail["post_action_match_count"],
                "failure_reason": detail.get("failure_reason"),
            }
            if not freshness_ok:
                result = "indeterminate"
                explanation = "network evidence failed freshness policy"
            else:
                result = network_result
                explanation = (
                    "exactly one matching network activity observed after action start"
                    if result == "pass"
                    else str(detail.get("failure_reason", "network assertion not satisfied"))
                )

        failure_evidence = (
            failed_expectation_evidence(
                expectation_type=expectation.type.value,
                expected=expected,
                observed=observed,
                freshness_ok=freshness_ok,
            )
            if result != "pass"
            else None
        )
        results.append(
            ExpectationResult(
                expectation_id=eid,
                expectation_type=expectation.type.value,
                expected=sanitize_evidence_value(expected),
                observed=sanitize_evidence_value(observed),
                result=result,
                evidence_refs=evidence_refs,
                evidence_timestamp_ms=evidence_ts,
                explanation=sanitize_evidence_value(explanation),
                freshness_ok=freshness_ok,
                failure_evidence=failure_evidence,
            )
        )

    return results
