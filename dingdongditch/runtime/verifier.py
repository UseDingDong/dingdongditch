from __future__ import annotations

from typing import Any

from dingdongditch.backends.playwright_backend import PlaywrightBackend, monotonic_ms
from dingdongditch.contract.expectation import (
    Expectation,
    ExpectationType,
    TextMatchMode,
    UrlMatchMode,
)
from dingdongditch.contract.operation import FreshnessPolicy
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.models import ExpectationResult, SignalKind
from dingdongditch.runtime.freshness import is_signal_fresh_for_verification


def _network_matches(expectation: Expectation, records: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    assert expectation.network_url_substring is not None
    matches = []
    for rec in records:
        if expectation.network_url_substring not in rec.get("url", ""):
            continue
        if expectation.network_method and rec.get("method") != expectation.network_method:
            continue
        if expectation.network_status is not None and rec.get("status") != expectation.network_status:
            continue
        matches.append(rec)
    return (len(matches) > 0, {"matches": matches, "scanned": len(records)})


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
        ):
            assert expectation.locator is not None
            now = monotonic_ms()
            state = backend.read_element_state(
                expectation.locator, frame=expectation.frame
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

        elif expectation.type == ExpectationType.NETWORK:
            now = monotonic_ms()
            records = post_network_payload.get("records", [])
            ok, detail = _network_matches(expectation, records)
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
            # Also require matching records themselves to be post-action.
            post_action_matches = [
                m
                for m in detail.get("matches", [])
                if m.get("recorded_at_ms", 0) >= action_started_at_ms
            ]
            observed = {
                "match_count": len(detail.get("matches", [])),
                "post_action_match_count": len(post_action_matches),
            }
            if not freshness_ok:
                result = "indeterminate"
                explanation = "network evidence failed freshness policy"
            elif not post_action_matches:
                result = "fail" if not ok else "indeterminate"
                explanation = (
                    "no matching network activity recorded after action start"
                    if ok
                    else "no matching network activity"
                )
                if not ok:
                    result = "fail"
            else:
                result = "pass"
                explanation = "matching network activity observed after action start"

        results.append(
            ExpectationResult(
                expectation_id=eid,
                expectation_type=expectation.type.value,
                expected=expected,
                observed=observed,
                result=result,
                evidence_refs=evidence_refs,
                evidence_timestamp_ms=evidence_ts,
                explanation=explanation,
                freshness_ok=freshness_ok,
            )
        )

    return results
