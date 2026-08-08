from __future__ import annotations

from pathlib import Path

import pytest

from dingdongditch import (
    Action, ActionType, BrowserConfig, Expectation, ExpectationType,
    ExecutionPlan, Locator, LocatorStrategy, Operation, PageObservationOptions,
    PublicSessionStatus,
    SessionFailureKind, StatefulSessionError, StatefulSessionRuntime,
    UploadAuthorization, Verdict,
)
from dingdongditch.contract.page import NewPageExpectation, PageTransition, PageTransitionPolicy
from dingdongditch.contract.modes import UrlMatchMode


FIXTURES = Path(__file__).parents[1] / "fixtures" / "local_test_app"
UPLOAD = (FIXTURES / "upload-one.txt").resolve()


def _nav(url: str, op_id="nav"):
    return Operation(
        operation_id=op_id, url=url,
        action=Action(type=ActionType.NAVIGATE),
        expectations=[Expectation(type=ExpectationType.URL, url_value=url)],
    )


def _observed_test_id(observation, value: str):
    return next(
        item for item in observation.interactive_elements
        if any(
            candidate.get("locator_type") == "test_id" and candidate.get("locator_value") == value
            for candidate in item.get("locator_candidates", ())
        )
    )


def test_sequential_state_observe_upload_and_recoverable_failure(fixture_url):
    runtime = StatefulSessionRuntime()
    info = runtime.open_session(BrowserConfig(headless=True))
    try:
        nav = runtime.execute_operation(info.session_id, _nav(fixture_url))
        assert nav.verdict == Verdict.VERIFIED.value
        page_id = nav.page_state[0]["page_id"]

        observation = runtime.observe_page(info.session_id, PageObservationOptions())
        text_input = _observed_test_id(observation.observation, "text-input")
        reference = observation.reference(text_input["element_id"])
        fill = runtime.execute_operation(
            info.session_id,
            Operation(
                operation_id="fill", url=fixture_url,
                action=Action(
                    type=ActionType.FILL,
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
                    text="preserved",
                ),
                expectations=[Expectation(
                    type=ExpectationType.ATTRIBUTE,
                    locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
                    attribute_name="value", attribute_value="preserved",
                )],
            ),
            observation_reference=reference,
        )
        assert fill.verdict == Verdict.VERIFIED.value
        assert fill.page_state[0]["page_id"] == page_id

        failed = runtime.execute_operation(info.session_id, Operation(
            operation_id="missing", url=fixture_url,
            action=Action(type=ActionType.CLICK, locator=Locator(strategy=LocatorStrategy.TEST_ID, value="absent")),
            expectations=[], locate_retry_ms=10,
        ))
        assert failed.recoverable is True
        assert failed.terminal is False

        successful = runtime.execute_operation(info.session_id, Operation(
            operation_id="verify-preserved", url=fixture_url,
            action=Action(type=ActionType.FILL, locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"), text="still-open"),
            expectations=[Expectation(type=ExpectationType.ATTRIBUTE, locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"), attribute_name="value", attribute_value="still-open")],
        ))
        assert successful.verdict == Verdict.VERIFIED.value

        upload_url = fixture_url.replace("index.html", "upload_fixture.html")
        runtime.execute_operation(info.session_id, _nav(upload_url, "nav-upload"))
        uploaded = runtime.execute_operation(info.session_id, Operation(
            operation_id="upload", url=upload_url,
            action=Action(
                type=ActionType.UPLOAD_FILE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="single-upload"),
                upload_authorization=UploadAuthorization((str(UPLOAD),), allowed_files=(str(UPLOAD),)),
            ),
            expectations=[Expectation(type=ExpectationType.UPLOAD_FILE_COUNT, locator=Locator(strategy=LocatorStrategy.TEST_ID, value="single-upload"), file_count=1)],
        ))
        assert uploaded.verdict == Verdict.VERIFIED.value
        assert str(FIXTURES.resolve()) not in repr(uploaded.to_dict())
    finally:
        runtime.close_session(info.session_id)


def test_stale_observation_popup_pages_selection_and_terminal_state(fixture_url):
    runtime = StatefulSessionRuntime()
    info = runtime.open_session()
    try:
        runtime.execute_operation(info.session_id, _nav(fixture_url))
        observed = runtime.observe_page(info.session_id)
        target = _observed_test_id(observed.observation, "text-input")
        stale = observed.reference(target["element_id"])
        runtime.execute_operation(info.session_id, _nav(fixture_url + "?changed", "change-doc"))
        rejected = runtime.execute_operation(info.session_id, Operation(
            operation_id="stale", url=fixture_url + "?changed",
            action=Action(type=ActionType.FILL, locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"), text="x"),
            expectations=[],
        ), observation_reference=stale)
        assert rejected.receipt.failure_kind == "stale_observation_reference"
        assert rejected.recoverable is True

        popup_url = fixture_url.replace("index.html", "popup_fixture.html")
        runtime.execute_operation(info.session_id, _nav(popup_url, "nav-popup"))
        popup = runtime.execute_operation(info.session_id, Operation(
            operation_id="popup", url=popup_url,
            action=Action(type=ActionType.CLICK, locator=Locator(strategy=LocatorStrategy.TEST_ID, value="popup-button")),
            expectations=[],
            page_transition=PageTransition(
                policy=PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT,
                new_page_expectations=(NewPageExpectation(
                    url_value="popup_target.html",
                    url_match=UrlMatchMode.CONTAINS,
                    visible_locator=Locator(strategy=LocatorStrategy.TEST_ID, value="popup-heading"),
                ),),
            ),
        ))
        assert popup.verdict == Verdict.VERIFIED.value, popup.receipt.to_dict()
        assert len(popup.events["new_pages"]) == 1
        created_id = popup.events["new_pages"][0]["page_id"]
        pages = runtime.inspect_pages(info.session_id)
        assert len([page for page in pages if page["lifecycle_state"] == "open"]) >= 2
        runtime.select_page(info.session_id, created_id)
        assert runtime.observe_page(info.session_id).page_id == created_id

        record = runtime._records[info.session_id]
        record.backend.page.close()
        with pytest.raises(StatefulSessionError) as terminal:
            runtime.inspect_pages(info.session_id)
        assert terminal.value.failure_kind == SessionFailureKind.TERMINAL_BROWSER_FAILURE
        assert runtime.get_session(info.session_id).status == PublicSessionStatus.TERMINAL
    finally:
        runtime.close_session(info.session_id)


def test_two_sessions_are_isolated_and_batch_path_unchanged(fixture_url):
    runtime = StatefulSessionRuntime()
    first = runtime.open_session()
    second = runtime.open_session()
    try:
        runtime.execute_operation(first.session_id, _nav(fixture_url))
        assert runtime.inspect_pages(second.session_id)[0]["current_url"] == "about:blank"
        with pytest.raises(StatefulSessionError) as wrong:
            runtime.inspect_pages("00000000-0000-0000-0000-000000000000")
        assert wrong.value.failure_kind == SessionFailureKind.SESSION_NOT_FOUND
    finally:
        runtime.close_session(first.session_id)
        runtime.close_session(second.session_id)

    from dingdongditch import execute_plan
    batch = execute_plan(ExecutionPlan(plan_id="batch-unchanged", operations=[_nav(fixture_url)]))
    assert batch.verified_step_count == 1
