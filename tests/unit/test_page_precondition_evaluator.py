from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dingdongditch import Locator, LocatorStrategy
from dingdongditch.contract.page_precondition import (
    FragmentPolicy,
    PageCondition,
    PageConditionResultValue,
    PageConditionType,
    PagePrecondition,
)
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.runtime.page_preconditions import evaluate_page_precondition


def evaluate(url: str, *conditions: PageCondition, state=None):
    backend = MagicMock()
    backend.page = SimpleNamespace(url=url)
    if state is not None:
        if isinstance(state, Exception):
            backend.read_element_state.side_effect = state
        else:
            backend.read_element_state.return_value = state
    collector = EvidenceCollector("pre")
    result = evaluate_page_precondition(
        PagePrecondition(tuple(conditions)),
        backend=backend,
        collector=collector,
    )
    return result, backend, collector


def c(ctype, condition_id, **kwargs):
    return PageCondition(condition_id=condition_id, type=ctype, **kwargs)


def anchor():
    return c(
        PageConditionType.ORIGIN_EQUALS,
        "origin",
        origin_value="https://example.test",
    )


def test_url_conditions_are_ordered_and_and_composed():
    result, _, _ = evaluate(
        "https://example.test/search?q=wireless+mouse&token=volatile#now",
        anchor(),
        c(PageConditionType.PATH_EQUALS, "path", path_value="/search"),
        c(
            PageConditionType.QUERY_PARAM_EQUALS,
            "query",
            query_name="q",
            query_value="wireless mouse",
        ),
    )
    assert result.result == PageConditionResultValue.PASS
    assert [item.condition_id for item in result.condition_results] == [
        "origin",
        "path",
        "query",
    ]
    assert result.expected_url is None


def test_exact_url_fragment_policy():
    ignored, _, _ = evaluate(
        "https://example.test/a#actual",
        c(
            PageConditionType.EXACT_URL,
            "exact",
            url_value="https://example.test/a#expected",
        ),
    )
    included, _, _ = evaluate(
        "https://example.test/a#actual",
        c(
            PageConditionType.EXACT_URL,
            "exact",
            url_value="https://example.test/a#expected",
            fragment_policy=FragmentPolicy.INCLUDE,
        ),
    )
    assert ignored.result == PageConditionResultValue.PASS
    assert included.result == PageConditionResultValue.FAIL


def test_origin_default_port_and_decoded_path_prefix():
    result, _, _ = evaluate(
        "https://EXAMPLE.test:443/documents/generated%20id",
        anchor(),
        c(
            PageConditionType.PATH_STARTS_WITH,
            "prefix",
            path_value="/documents/",
        ),
    )
    assert result.result == PageConditionResultValue.PASS


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.test/search?q=", PageConditionResultValue.PASS),
        ("https://example.test/search?q", PageConditionResultValue.PASS),
        ("https://example.test/search?q=x", PageConditionResultValue.FAIL),
        ("https://example.test/search", PageConditionResultValue.FAIL),
        ("https://example.test/search?q=&q=", PageConditionResultValue.FAIL),
    ],
)
def test_query_blank_missing_mismatch_and_duplicates(url, expected):
    result, _, _ = evaluate(
        url,
        anchor(),
        c(
            PageConditionType.QUERY_PARAM_EQUALS,
            "query",
            query_name="q",
            query_value="",
        ),
    )
    assert result.result == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"match_count": 0, "exists": False}, PageConditionResultValue.FAIL),
        (
            {"match_count": 1, "exists": True, "visible": False},
            PageConditionResultValue.FAIL,
        ),
        (
            {"match_count": 1, "exists": True, "visible": True},
            PageConditionResultValue.PASS,
        ),
        (
            {"match_count": 2, "exists": True, "ambiguous": True},
            PageConditionResultValue.INDETERMINATE,
        ),
        (RuntimeError("DOM unavailable"), PageConditionResultValue.INDETERMINATE),
    ],
)
def test_element_visible_fail_closed_semantics(state, expected):
    frame = Locator(strategy=LocatorStrategy.CSS, value="iframe#scope")
    locator = Locator(strategy=LocatorStrategy.CSS, value="#landmark")
    result, backend, collector = evaluate(
        "https://example.test/",
        c(
            PageConditionType.ELEMENT_VISIBLE,
            "landmark",
            locator=locator,
            frame=frame,
        ),
        state=state,
    )
    assert result.result == expected
    backend.read_element_state.assert_called_once_with(locator, frame=frame)
    assert not hasattr(backend, "dispatch") or backend.dispatch.call_count == 0
    assert len(collector.signals) == 2


def test_all_conditions_evaluated_once_even_after_failure():
    locator = Locator(strategy=LocatorStrategy.CSS, value="#landmark")
    result, backend, _ = evaluate(
        "https://wrong.test/no",
        anchor(),
        c(PageConditionType.PATH_EQUALS, "path", path_value="/search"),
        c(PageConditionType.ELEMENT_VISIBLE, "landmark", locator=locator),
        state={"match_count": 1, "exists": True, "visible": True},
    )
    assert [item.result for item in result.condition_results] == [
        PageConditionResultValue.FAIL,
        PageConditionResultValue.FAIL,
        PageConditionResultValue.PASS,
    ]
    backend.read_element_state.assert_called_once()
