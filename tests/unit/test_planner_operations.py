from dingdongditch import PlannerAdapter, click_operation, navigate_operation, scroll_operation


class _Transport:
    def __init__(self):
        self.calls = []

    def call_tool(self, tool, arguments):
        self.calls.append((tool, arguments))
        return False, {"receipt": {"verdict": "VERIFIED"}}


def _planner():
    planner = PlannerAdapter.__new__(PlannerAdapter)
    planner._transport = _Transport()
    return planner


def test_canonical_navigation_succeeds_through_planner_adapter():
    planner = _planner()
    response = planner.navigate("open-example", "https://example.com/")
    assert response.ok
    operation = planner._transport.calls[0][1]["operation"]
    assert operation == navigate_operation("open-example", "https://example.com/")


def test_unsupported_navigation_fields_are_caught_at_planner_boundary():
    planner = _planner()
    response = planner.execute({
        "operation_id": "bad-nav",
        "url": "https://example.com/",
        "action": {"type": "navigate"},
        "delta_y": 600,
    })
    assert not response.ok
    assert response.error["code"] == "planner_invalid_operation"
    assert response.error["details"]["errors"][0]["code"] == "unknown_field"
    assert "properties" in response.error["details"]["allowed_shape"]
    assert planner._transport.calls == []


def test_supported_builders_emit_operations_accepted_by_canonical_parser():
    from dingdongditch import parse_operation

    for operation in (
        navigate_operation("n", "https://example.com/"),
        click_operation("c", "https://example.com/", {"strategy": "css", "value": "a"}),
        scroll_operation("s", "https://example.com/", {"strategy": "css", "value": "body"}),
    ):
        parse_operation(operation)
