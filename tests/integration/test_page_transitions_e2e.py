from __future__ import annotations

from urllib.parse import urljoin

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.expectation import Expectation, ExpectationType, UrlMatchMode
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.page import NewPageExpectation, PageTransition, PageTransitionPolicy
from dingdongditch.contract.plan import ExecutionPlan, PlanVerdict
from dingdongditch.contract.verdict import Verdict
from dingdongditch.inspection import inspect_known_page, list_known_pages
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan


def _url(base: str, name: str) -> str:
    return urljoin(base, name)


def _tid(value: str) -> Locator:
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def _nav(url: str) -> Operation:
    return Operation(
        operation_id="navigate-popup-fixture",
        url=url,
        action=Action(type=ActionType.NAVIGATE),
        expectations=[
            Expectation(
                type=ExpectationType.URL,
                url_value="popup_fixture.html",
                url_match=UrlMatchMode.CONTAINS,
            )
        ],
    )


def _transition(
    policy: PageTransitionPolicy,
    *,
    target: str = "popup_target.html",
    timeout_ms: int = 2_000,
) -> PageTransition:
    return PageTransition(
        policy=policy,
        timeout_ms=timeout_ms,
        new_page_expectations=(
            NewPageExpectation(
                url_value=target,
                url_match=UrlMatchMode.CONTAINS,
                visible_locator=_tid("popup-heading"),
            ),
        ),
    )


def _click(url: str, test_id: str, transition: PageTransition) -> Operation:
    return Operation(
        operation_id=f"click-{test_id}",
        url=url,
        action=Action(type=ActionType.CLICK, locator=_tid(test_id)),
        page_transition=transition,
    )


def test_link_opens_new_tab_and_switches(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    receipt = execute_plan(
        ExecutionPlan(
            plan_id="new-tab-switch",
            operations=[
                _nav(opener),
                _click(
                    opener,
                    "new-tab-link",
                    _transition(PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH),
                ),
            ],
        )
    )
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    evidence = receipt.steps[1].receipt.action_evidence
    assert evidence["switching_occurred"] is True
    assert len(evidence["created_page_ids"]) == 1
    assert evidence["selected_active_page_id"] == evidence["created_page_ids"][0]
    assert receipt.steps[0].page_id != receipt.steps[1].page_id


def test_popup_keeps_original_active_and_registry_is_read_only(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    backend = PlaywrightBackend()
    backend.start()
    try:
        assert execute_operation(_nav(opener), backend=backend).verdict == Verdict.VERIFIED
        opener_id = backend.page_id
        receipt = execute_operation(
            _click(
                opener,
                "popup-button",
                _transition(PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT),
            ),
            backend=backend,
        )
        assert receipt.verdict == Verdict.VERIFIED
        assert backend.page_id == opener_id
        pages = list_known_pages(backend)
        assert len(pages) == 2
        created_id = receipt.action_evidence["created_page_ids"][0]
        assert inspect_known_page(backend, created_id)["opener_page_id"] == opener_id
    finally:
        backend.stop()


def test_switch_back_to_opener(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    target = _url(fixture_url, "popup_target.html")
    receipt = execute_plan(
        ExecutionPlan(
            plan_id="switch-opener",
            operations=[
                _nav(opener),
                _click(
                    opener,
                    "new-tab-link",
                    _transition(PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH),
                ),
                Operation(
                    operation_id="switch-back",
                    url=target,
                    action=Action(type=ActionType.SWITCH_TO_OPENER),
                ),
            ],
        )
    )
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.steps[2].page_id == receipt.steps[0].page_id
    assert receipt.steps[2].receipt.action_evidence["switching_occurred"] is True


def test_close_popup_and_continue_on_original(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    backend = PlaywrightBackend()
    backend.start()
    try:
        execute_operation(_nav(opener), backend=backend)
        popup = execute_operation(
            _click(
                opener,
                "popup-button",
                _transition(PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT),
            ),
            backend=backend,
        )
        created_id = popup.action_evidence["created_page_ids"][0]
        closed = execute_operation(
            Operation(
                operation_id="close-popup",
                url=opener,
                action=Action(type=ActionType.CLOSE_PAGE, page_id=created_id),
            ),
            backend=backend,
        )
        assert closed.verdict == Verdict.VERIFIED
        assert inspect_known_page(backend, created_id)["lifecycle_state"] == "closed"
        assert backend.page.url == opener
    finally:
        backend.stop()


def test_expected_new_page_never_opens(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    receipt = execute_plan(
        ExecutionPlan(
            plan_id="missing-popup",
            operations=[
                _nav(opener),
                _click(
                    opener,
                    "no-popup-button",
                    _transition(
                        PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH,
                        timeout_ms=200,
                    ),
                ),
            ],
        )
    )
    failed = receipt.steps[1].receipt
    assert failed.verdict == Verdict.EXECUTION_FAILED
    assert failed.failure_kind == "expected_new_page_not_opened"
    assert failed.action_evidence["popup_event_fired"] is False


def test_unexpected_popup_fails_closed(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    receipt = execute_plan(
        ExecutionPlan(
            plan_id="unexpected-popup",
            operations=[
                _nav(opener),
                Operation(
                    operation_id="unexpected",
                    url=opener,
                    action=Action(type=ActionType.CLICK, locator=_tid("popup-button")),
                    expectations=[
                        Expectation(
                            type=ExpectationType.ELEMENT_VISIBLE,
                            locator=_tid("opener-heading"),
                            visible=True,
                        )
                    ],
                ),
            ],
        )
    )
    failed = receipt.steps[1].receipt
    assert failed.failure_kind == "unexpected_new_page", (
        failed.failure_kind,
        failed.execution_error,
        failed.action_evidence,
    )
    assert failed.action_evidence["unexpected_page_classification"] == "unexpected_new_page"


def test_two_pages_when_one_expected(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    receipt = execute_plan(
        ExecutionPlan(
            plan_id="two-popups",
            operations=[
                _nav(opener),
                _click(
                    opener,
                    "two-pages-button",
                    _transition(PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT),
                ),
            ],
        )
    )
    failed = receipt.steps[1].receipt
    assert failed.failure_kind == "multiple_new_pages_opened"
    assert len(failed.action_evidence["created_page_ids"]) == 2


def test_popup_closes_before_verification(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    receipt = execute_plan(
        ExecutionPlan(
            plan_id="closing-popup",
            operations=[
                _nav(opener),
                _click(
                    opener,
                    "closing-popup-button",
                    _transition(PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT),
                ),
            ],
        )
    )
    failed = receipt.steps[1].receipt
    assert failed.failure_kind == "new_page_closed_before_verification", (
        failed.failure_kind,
        failed.execution_error,
        failed.action_evidence,
    )


def test_new_page_redirects_before_verification(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    receipt = execute_plan(
        ExecutionPlan(
            plan_id="redirect-popup",
            operations=[
                _nav(opener),
                _click(
                    opener,
                    "redirect-popup-button",
                    _transition(PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH),
                ),
            ],
        )
    )
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    result = receipt.steps[1].receipt.action_evidence["new_page_verification_results"]
    assert all(item["passed"] for item in result)


def test_deadline_expires_while_waiting_and_cleanup_retains_pages(fixture_url):
    opener = _url(fixture_url, "popup_fixture.html")
    receipt = execute_plan(
        ExecutionPlan(
            plan_id="popup-deadline",
            initial_plan_timeout_ms=3_000,
            operations=[
                _nav(opener),
                _click(
                    opener,
                    "delayed-popup-button",
                    _transition(
                        PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH,
                        timeout_ms=2_000,
                    ),
                ),
            ],
        )
    )
    failed = receipt.steps[1].receipt
    assert failed.failure_kind in {"plan_deadline_expired", "expected_new_page_not_opened"}
    assert receipt.lifecycle["state"] == "stopped"
    terminal_pages = receipt.lifecycle["terminal_session_identity"]["pages"]
    assert terminal_pages
    assert all(page["closed_at_ms"] is not None for page in terminal_pages)
