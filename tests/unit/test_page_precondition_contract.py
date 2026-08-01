from __future__ import annotations

import pytest

from dingdongditch import (
    Action,
    ActionType,
    FragmentPolicy,
    Locator,
    LocatorStrategy,
    Operation,
    PageCondition,
    PageConditionType,
    PagePrecondition,
)
from dingdongditch.contract.page_precondition import MAX_PAGE_CONDITIONS
from dingdongditch.plan_json import PlanLoadError, operation_from_dict


def condition(ctype: PageConditionType, condition_id: str = "c1", **kwargs):
    return PageCondition(condition_id=condition_id, type=ctype, **kwargs)


@pytest.mark.parametrize(
    "item",
    [
        condition(PageConditionType.EXACT_URL, url_value="https://example.test/a"),
        condition(
            PageConditionType.EXACT_URL,
            url_value="https://example.test/a#x",
            fragment_policy=FragmentPolicy.INCLUDE,
        ),
        condition(PageConditionType.ORIGIN_EQUALS, origin_value="https://EXAMPLE.test:443"),
        condition(PageConditionType.PATH_EQUALS, path_value="/search"),
        condition(PageConditionType.PATH_STARTS_WITH, path_value="/documents/"),
        condition(
            PageConditionType.QUERY_PARAM_EQUALS,
            query_name="q",
            query_value="",
        ),
        condition(
            PageConditionType.ELEMENT_VISIBLE,
            locator=Locator(strategy=LocatorStrategy.CSS, value="#landmark"),
            frame=Locator(strategy=LocatorStrategy.CSS, value="iframe"),
        ),
    ],
)
def test_all_six_condition_forms_validate(item):
    if item.type in {
        PageConditionType.PATH_EQUALS,
        PageConditionType.PATH_STARTS_WITH,
        PageConditionType.QUERY_PARAM_EQUALS,
    }:
        PagePrecondition(
            (
                condition(
                    PageConditionType.ORIGIN_EQUALS,
                    condition_id="origin",
                    origin_value="https://example.test",
                ),
                item,
            )
        ).validate()
    else:
        PagePrecondition((item,)).validate()


@pytest.mark.parametrize("path", ["", "relative", "/", "/a?b", "/a#b"])
def test_path_starts_with_rejects_invalid_literals(path):
    with pytest.raises(ValueError):
        condition(PageConditionType.PATH_STARTS_WITH, path_value=path).validate()


def test_path_and_query_require_declared_origin_anchor():
    with pytest.raises(ValueError, match="require exact_url or origin_equals"):
        PagePrecondition(
            (condition(PageConditionType.PATH_EQUALS, path_value="/search"),)
        ).validate()


def test_empty_duplicate_and_maximum_bounds():
    with pytest.raises(ValueError, match="must not be empty"):
        PagePrecondition(()).validate()
    duplicate = condition(
        PageConditionType.ORIGIN_EQUALS, origin_value="https://example.test"
    )
    with pytest.raises(ValueError, match="must be unique"):
        PagePrecondition((duplicate, duplicate)).validate()
    items = tuple(
        condition(
            PageConditionType.ELEMENT_VISIBLE,
            condition_id=f"c{i}",
            locator=Locator(strategy=LocatorStrategy.CSS, value=f"#x{i}"),
        )
        for i in range(MAX_PAGE_CONDITIONS + 1)
    )
    with pytest.raises(ValueError, match="at most"):
        PagePrecondition(items).validate()


def test_static_contradictions_are_rejected():
    with pytest.raises(ValueError, match="contradictory origin"):
        PagePrecondition(
            (
                condition(
                    PageConditionType.ORIGIN_EQUALS,
                    "a",
                    origin_value="https://a.test",
                ),
                condition(
                    PageConditionType.ORIGIN_EQUALS,
                    "b",
                    origin_value="https://b.test",
                ),
            )
        ).validate()


def _json_operation(page_precondition):
    return {
        "operation_id": "op",
        "url": "https://example.test/",
        "action": {"type": "click", "locator": {"strategy": "css", "value": "#x"}},
        "page_precondition": page_precondition,
    }


def test_json_is_strict_per_discriminated_condition():
    with pytest.raises(PlanLoadError, match="unknown fields"):
        operation_from_dict(
            _json_operation(
                {
                    "conditions": [
                        {
                            "condition_id": "origin",
                            "type": "origin_equals",
                            "origin_value": "https://example.test",
                            "url_value": "https://example.test/",
                        }
                    ]
                }
            )
        )
    with pytest.raises(PlanLoadError, match="invalid PageConditionType"):
        operation_from_dict(
            _json_operation(
                {"conditions": [{"condition_id": "x", "type": "url_contains"}]}
            )
        )


def test_json_rejects_empty_conditions_and_unknown_precondition_fields():
    with pytest.raises(PlanLoadError, match="must not be empty"):
        operation_from_dict(_json_operation({"conditions": []}))
    with pytest.raises(PlanLoadError, match="unknown fields"):
        operation_from_dict(
            _json_operation({"conditions": [], "unexpected": True})
        )


def test_navigate_cannot_have_explicit_precondition():
    operation = Operation(
        "nav",
        "https://example.test/",
        Action(type=ActionType.NAVIGATE),
        page_precondition=PagePrecondition(
            (
                condition(
                    PageConditionType.EXACT_URL,
                    url_value="https://example.test/",
                ),
            )
        ),
    )
    with pytest.raises(ValueError, match="navigate operations"):
        operation.validate()


def test_old_python_constructor_and_json_remain_legacy():
    operation = Operation(
        "click",
        "https://example.test/",
        Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.CSS, value="#x"),
        ),
    )
    assert operation.page_precondition is None
    loaded = operation_from_dict(
        {
            "operation_id": "click",
            "url": "https://example.test/",
            "action": {
                "type": "click",
                "locator": {"strategy": "css", "value": "#x"},
            },
        }
    )
    assert loaded.page_precondition is None
