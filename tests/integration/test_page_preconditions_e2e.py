"""Deterministic local-fixture integration coverage for PagePrecondition V1."""
from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from dingdongditch import (
    Action,
    ActionType,
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
    Expectation,
    ExpectationType,
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
    PageCondition,
    PageConditionType,
    PagePrecondition,
    Verdict,
    execute_operation,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


ENGINES = [
    BrowserEngine.CHROMIUM,
    BrowserEngine.FIREFOX,
    BrowserEngine.WEBKIT,
]


def config(engine):
    return BrowserConfig(
        provider=BrowserProvider.PLAYWRIGHT,
        engine=engine,
        channel=BrowserChannel.BUNDLED,
        headless=True,
    )


def origin_of(url):
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def stable_search_precondition(fixture_url, landmark="already-visible"):
    return PagePrecondition(
        (
            PageCondition(
                "origin",
                PageConditionType.ORIGIN_EQUALS,
                origin_value=origin_of(fixture_url),
            ),
            PageCondition(
                "path", PageConditionType.PATH_EQUALS, path_value="/index.html"
            ),
            PageCondition(
                "query",
                PageConditionType.QUERY_PARAM_EQUALS,
                query_name="q",
                query_value="stable value",
            ),
            PageCondition(
                "landmark",
                PageConditionType.ELEMENT_VISIBLE,
                locator=Locator(LocatorStrategy.TEST_ID, landmark),
            ),
        )
    )


@pytest.mark.parametrize("engine", ENGINES, ids=lambda item: item.value)
def test_transient_query_and_visible_landmark_dispatch_across_engines(
    fixture_url, engine
):
    current = f"{fixture_url}?q=stable+value&token={engine.value}-generated"
    backend = PlaywrightBackend(config(engine))
    backend.start()
    try:
        nav = execute_operation(
            Operation("nav", current, Action(type=ActionType.NAVIGATE)),
            backend=backend,
        )
        assert nav.action_executed_successfully
        fill = execute_operation(
            Operation(
                "fill",
                fixture_url,
                Action(
                    type=ActionType.FILL,
                    locator=Locator(LocatorStrategy.TEST_ID, "text-input"),
                    text=engine.value,
                ),
                expectations=[
                    Expectation(
                        type=ExpectationType.ATTRIBUTE,
                        locator=Locator(LocatorStrategy.TEST_ID, "text-input"),
                        attribute_name="value",
                        attribute_value=engine.value,
                    )
                ],
                page_precondition=stable_search_precondition(fixture_url),
            ),
            backend=backend,
        )
        assert fill.verdict == Verdict.VERIFIED
        assert fill.page_precondition["result"] == "pass"
        assert fill.action_executed_successfully
    finally:
        backend.stop()


@pytest.mark.parametrize("engine", ENGINES, ids=lambda item: item.value)
def test_generated_path_suffix_passes_literal_prefix(fixture_url, engine):
    generated = f"{origin_of(fixture_url)}/generated/{engine.value}-token"
    backend = PlaywrightBackend(config(engine))
    backend.start()
    try:
        nav = execute_operation(
            Operation("nav-generated", generated, Action(type=ActionType.NAVIGATE)),
            backend=backend,
        )
        assert nav.action_executed_successfully
        receipt = execute_operation(
            Operation(
                "prefix",
                fixture_url,
                Action(
                    type=ActionType.PRESS_KEY,
                    key="Escape",
                    key_scope=KeyPressScope.ACTIVE_PAGE,
                ),
                page_precondition=PagePrecondition(
                    (
                        PageCondition(
                            "origin",
                            PageConditionType.ORIGIN_EQUALS,
                            origin_value=origin_of(fixture_url),
                        ),
                        PageCondition(
                            "prefix",
                            PageConditionType.PATH_STARTS_WITH,
                            path_value="/generated/",
                        ),
                    )
                ),
            ),
            backend=backend,
        )
        assert receipt.action_executed_successfully
        assert receipt.page_precondition["result"] == "pass"
    finally:
        backend.stop()


@pytest.mark.parametrize(
    ("precondition", "expected_result"),
    [
        (
            PagePrecondition(
                (
                    PageCondition(
                        "origin",
                        PageConditionType.ORIGIN_EQUALS,
                        origin_value="https://wrong.example",
                    ),
                )
            ),
            "fail",
        ),
    ],
)
def test_wrong_origin_blocks_dispatch(fixture_url, precondition, expected_result):
    backend = PlaywrightBackend(config(BrowserEngine.CHROMIUM))
    backend.start()
    try:
        execute_operation(
            Operation("nav", fixture_url, Action(type=ActionType.NAVIGATE)),
            backend=backend,
        )
        receipt = execute_operation(
            Operation(
                "blocked",
                fixture_url,
                Action(
                    type=ActionType.PRESS_KEY,
                    key="Escape",
                    key_scope=KeyPressScope.ACTIVE_PAGE,
                ),
                page_precondition=precondition,
            ),
            backend=backend,
        )
        assert receipt.action_executed_successfully is False
        assert receipt.page_precondition["result"] == expected_result
    finally:
        backend.stop()


def test_missing_visible_landmark_blocks_dispatch(fixture_url):
    backend = PlaywrightBackend(config(BrowserEngine.CHROMIUM))
    backend.start()
    try:
        current = f"{fixture_url}?q=stable+value&token=transient"
        execute_operation(
            Operation("nav", current, Action(type=ActionType.NAVIGATE)),
            backend=backend,
        )
        receipt = execute_operation(
            Operation(
                "missing",
                fixture_url,
                Action(
                    type=ActionType.PRESS_KEY,
                    key="Escape",
                    key_scope=KeyPressScope.ACTIVE_PAGE,
                ),
                page_precondition=stable_search_precondition(
                    fixture_url, landmark="does-not-exist"
                ),
            ),
            backend=backend,
        )
        assert receipt.action_executed_successfully is False
        assert receipt.page_precondition["result"] == "fail"
    finally:
        backend.stop()
