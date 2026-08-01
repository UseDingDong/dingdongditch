"""Read-only, one-shot evaluation of declared current-page preconditions."""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from dingdongditch.backends.playwright_backend import monotonic_ms
from dingdongditch.contract.page_precondition import (
    FragmentPolicy,
    PageCondition,
    PageConditionResult,
    PageConditionResultValue,
    PageConditionType,
    PagePrecondition,
    PagePreconditionEvaluation,
    normalize_origin,
)
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.evidence.models import SignalAvailability, SignalKind


def _without_fragment(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
    )


def _same_document_url(current: str, declared: str) -> bool:
    if current == declared or current.rstrip("/") == declared.rstrip("/"):
        return True
    current_parts = urlsplit(current)
    declared_parts = urlsplit(declared)
    current_path = current_parts.path.rstrip("/") or "/"
    declared_path = declared_parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            current_parts.scheme,
            current_parts.netloc,
            current_path,
            current_parts.query,
            "",
        )
    ) == urlunsplit(
        (
            declared_parts.scheme,
            declared_parts.netloc,
            declared_path,
            declared_parts.query,
            "",
        )
    )


def _expected(condition: PageCondition) -> dict[str, Any]:
    described = condition.describe()
    described.pop("condition_id", None)
    described.pop("type", None)
    return described


def evaluate_page_precondition(
    precondition: PagePrecondition,
    *,
    backend: Any,
    collector: EvidenceCollector,
) -> PagePreconditionEvaluation:
    """Evaluate every declared condition exactly once, in declaration order."""
    precondition.validate()
    evaluation_started = monotonic_ms()
    actual_url = backend.page.url
    url_observed_at = monotonic_ms()
    try:
        parsed = urlsplit(actual_url)
        if not parsed.scheme:
            raise ValueError("current URL is not an absolute URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("current URL contains userinfo")
        if parsed.scheme.lower() in {"http", "https"} and not parsed.hostname:
            raise ValueError("current http(s) URL has no host")
        parsed_port = parsed.port
        decoded_path = unquote(parsed.path)
        decoded_query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=False,
        )
        url_error: str | None = None
    except Exception as exc:
        parsed = None
        decoded_path = ""
        decoded_query = []
        url_error = f"{type(exc).__name__}: {exc}"
    url_payload: dict[str, Any] = {"url": actual_url}
    if url_error is None and parsed is not None:
        url_payload["parsed"] = {
            "scheme": parsed.scheme.lower(),
            "host": parsed.hostname.lower() if parsed.hostname else None,
            "port": parsed_port,
            "decoded_path": decoded_path,
            "decoded_query": [
                {"key": key, "value": value}
                for key, value in decoded_query
            ],
            "fragment": parsed.fragment,
        }
    else:
        url_payload["observation_error"] = url_error
    url_signal = collector.add(
        kind=SignalKind.URL,
        collected_at_ms=url_observed_at,
        payload=url_payload,
        notes="explicit page precondition URL snapshot",
    )
    try:
        actual_origin = normalize_origin(
            urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        ) if parsed is not None else ""
        origin_error: str | None = None
    except Exception as exc:
        actual_origin = ""
        origin_error = f"{type(exc).__name__}: {exc}"

    results: list[PageConditionResult] = []
    for condition in precondition.conditions:
        evaluated_at = monotonic_ms()
        expected = _expected(condition)
        observed: dict[str, Any] = {}
        refs: tuple[str, ...] = (url_signal.signal_id,)
        result = PageConditionResultValue.INDETERMINATE
        explanation = "condition evaluator did not produce a result"
        try:
            if condition.type == PageConditionType.ELEMENT_VISIBLE:
                assert condition.locator is not None
                try:
                    state = backend.read_element_state(
                        condition.locator, frame=condition.frame
                    )
                    availability = SignalAvailability.OBSERVED
                    notes = "element_visible page precondition"
                except Exception as exc:
                    state = {
                        "observation_error": f"{type(exc).__name__}: {exc}"
                    }
                    availability = SignalAvailability.UNAVAILABLE
                    notes = "element_visible page precondition observation unavailable"
                dom_signal = collector.add(
                    kind=SignalKind.DOM_STATE,
                    collected_at_ms=evaluated_at,
                    payload={
                        "locator": condition.locator.describe(),
                        "frame": (
                            condition.frame.describe()
                            if condition.frame is not None
                            else None
                        ),
                        "state": state,
                    },
                    availability=availability,
                    notes=notes,
                )
                refs = (dom_signal.signal_id,)
                observed = state
                if availability == SignalAvailability.UNAVAILABLE:
                    result = PageConditionResultValue.INDETERMINATE
                    explanation = "DOM observation was unavailable"
                elif state.get("ambiguous") or (
                    isinstance(state.get("match_count"), int)
                    and state["match_count"] > 1
                ):
                    result = PageConditionResultValue.INDETERMINATE
                    explanation = "locator matched multiple elements"
                elif state.get("match_count") == 0 or not state.get("exists"):
                    result = PageConditionResultValue.FAIL
                    explanation = "locator matched no elements"
                elif state.get("match_count") != 1:
                    result = PageConditionResultValue.INDETERMINATE
                    explanation = "DOM observation did not establish unique cardinality"
                elif state.get("visible") is True:
                    result = PageConditionResultValue.PASS
                    explanation = "exactly one visible element matched"
                else:
                    result = PageConditionResultValue.FAIL
                    explanation = "exactly one element matched but it was hidden"
            elif url_error is not None:
                observed = {"url": actual_url, "observation_error": url_error}
                result = PageConditionResultValue.INDETERMINATE
                explanation = "current URL could not be parsed deterministically"
            elif condition.type == PageConditionType.EXACT_URL:
                assert condition.url_value is not None
                observed = {"url": actual_url}
                if condition.fragment_policy == FragmentPolicy.IGNORE:
                    passed = _same_document_url(actual_url, condition.url_value)
                    explanation = (
                        "URL matched with fragment ignored"
                        if passed
                        else "URL did not match with fragment ignored"
                    )
                else:
                    actual_parts = urlsplit(actual_url)
                    expected_parts = urlsplit(condition.url_value)
                    passed = (
                        actual_parts.fragment == expected_parts.fragment
                        and _same_document_url(
                            _without_fragment(actual_url),
                            _without_fragment(condition.url_value),
                        )
                    )
                    explanation = (
                        "URL matched exactly"
                        if passed
                        else "URL did not match exactly"
                    )
                result = (
                    PageConditionResultValue.PASS
                    if passed
                    else PageConditionResultValue.FAIL
                )
            elif condition.type == PageConditionType.ORIGIN_EQUALS:
                assert condition.origin_value is not None
                if origin_error is not None:
                    observed = {
                        "url": actual_url,
                        "observation_error": origin_error,
                    }
                    result = PageConditionResultValue.INDETERMINATE
                    explanation = "current origin was unavailable"
                else:
                    expected_origin = normalize_origin(condition.origin_value)
                    observed = {"origin": actual_origin, "url": actual_url}
                    passed = actual_origin == expected_origin
                    result = (
                        PageConditionResultValue.PASS
                        if passed
                        else PageConditionResultValue.FAIL
                    )
                    explanation = (
                        "origin matched" if passed else "origin did not match"
                    )
            elif condition.type == PageConditionType.PATH_EQUALS:
                assert condition.path_value is not None
                observed = {"decoded_path": decoded_path, "url": actual_url}
                passed = decoded_path == condition.path_value
                result = (
                    PageConditionResultValue.PASS
                    if passed
                    else PageConditionResultValue.FAIL
                )
                explanation = "path matched" if passed else "path did not match"
            elif condition.type == PageConditionType.PATH_STARTS_WITH:
                assert condition.path_value is not None
                observed = {"decoded_path": decoded_path, "url": actual_url}
                passed = decoded_path.startswith(condition.path_value)
                result = (
                    PageConditionResultValue.PASS
                    if passed
                    else PageConditionResultValue.FAIL
                )
                explanation = (
                    "path had the declared literal prefix"
                    if passed
                    else "path lacked the declared literal prefix"
                )
            elif condition.type == PageConditionType.QUERY_PARAM_EQUALS:
                assert condition.query_name is not None
                assert condition.query_value is not None
                occurrences = [
                    value
                    for key, value in decoded_query
                    if key == condition.query_name
                ]
                observed = {
                    "query_name": condition.query_name,
                    "decoded_occurrence_count": len(occurrences),
                    "decoded_values": occurrences,
                    "url": actual_url,
                }
                if len(occurrences) != 1:
                    result = PageConditionResultValue.FAIL
                    explanation = (
                        "query key was absent"
                        if not occurrences
                        else "query key occurred more than once"
                    )
                else:
                    passed = occurrences[0] == condition.query_value
                    result = (
                        PageConditionResultValue.PASS
                        if passed
                        else PageConditionResultValue.FAIL
                    )
                    explanation = (
                        "query value matched"
                        if passed
                        else "query value did not match"
                    )
            else:
                observed = {"url": actual_url}
                result = PageConditionResultValue.INDETERMINATE
                explanation = "unsupported condition type"
        except Exception as exc:
            observed = {
                **observed,
                "evaluator_error": f"{type(exc).__name__}: {exc}",
            }
            result = PageConditionResultValue.INDETERMINATE
            explanation = "condition evaluator error"
        results.append(
            PageConditionResult(
                condition_id=condition.condition_id,
                condition_type=condition.type.value,
                expected=expected,
                observed=observed,
                result=result,
                evidence_refs=refs,
                evaluated_at_ms=evaluated_at,
                explanation=explanation,
            )
        )

    if any(item.result == PageConditionResultValue.INDETERMINATE for item in results):
        aggregate = PageConditionResultValue.INDETERMINATE
    elif any(item.result == PageConditionResultValue.FAIL for item in results):
        aggregate = PageConditionResultValue.FAIL
    else:
        aggregate = PageConditionResultValue.PASS
    exact_conditions = [
        condition
        for condition in precondition.conditions
        if condition.type == PageConditionType.EXACT_URL
    ]
    expected_url = (
        exact_conditions[0].url_value if len(exact_conditions) == 1 else None
    )
    fragment_ignored = (
        exact_conditions[0].fragment_policy == FragmentPolicy.IGNORE
        if len(exact_conditions) == 1
        else None
    )
    return PagePreconditionEvaluation(
        mode="explicit_conditions",
        logic=precondition.logic,
        result=aggregate,
        evaluated_at_ms=evaluation_started,
        actual_url=actual_url,
        condition_results=tuple(results),
        expected_url=expected_url,
        fragment_differences_ignored=fragment_ignored,
    )
