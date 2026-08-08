from pathlib import Path
from unittest.mock import patch

from dingdongditch import (
    Action, ActionType, BrowserConfig, ExecutionPlan, Expectation, GuardBranch,
    Locator, LocatorStrategy, Operation, OperationGuard, TargetAbsentGuard,
    execute_plan,
)
from dingdongditch.authentication import AuthenticationCapability, ProfileManager
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.expectation import ExpectationType
from dingdongditch.contract.plan import PlanVerdict
from dingdongditch.contract.verdict import Verdict
from dingdongditch.evidence.models import ExpectationResult


def _exists(selector: str, expected: bool) -> Expectation:
    return Expectation(
        type=ExpectationType.ELEMENT_EXISTS,
        locator=Locator(strategy=LocatorStrategy.CSS, value=selector),
        exists=expected,
    )


def _guarded_click(url: str, target: str, normal: Expectation, absent: Expectation) -> Operation:
    return Operation(
        operation_id="guarded-click",
        url=url,
        action=Action(
            type=ActionType.CLICK,
            locator=Locator(strategy=LocatorStrategy.CSS, value=target),
        ),
        expectations=[normal],
        guard=OperationGuard(TargetAbsentGuard((absent,))),
    )


def _navigate(url: str) -> Operation:
    return Operation(
        "navigate",
        url,
        Action(type=ActionType.NAVIGATE),
        expectations=[
            Expectation(
                type=ExpectationType.URL,
                url_value=url,
            )
        ],
    )


def test_cookie_fixture_persists_and_exercises_both_guard_branches(tmp_path, fixture_url):
    url = fixture_url.replace("index.html", "consent_fixture.html")
    manager = ProfileManager(tmp_path / "profiles")
    manager.create("consent")
    config = BrowserConfig(profile="consent")
    operation = _guarded_click(
        url, "#accept-consent", _exists("#consent-banner", False),
        _exists("#consent-banner", False),
    )
    plan = ExecutionPlan("guarded-consent", [_navigate(url), operation], browser_config=config)

    first_backend = PlaywrightBackend(
        config, authentication=AuthenticationCapability(profiles=manager)
    )
    first_backend.start()
    try:
        first = execute_plan(plan, backend=first_backend)
    finally:
        first_backend.stop()
    assert first.plan_verdict is PlanVerdict.VERIFIED
    first_guard = first.steps[1].receipt.action_evidence
    assert first_guard["branch"] == "target_present"
    assert first_guard["dispatched"] is True
    assert first_guard["skipped"] is False

    second_backend = PlaywrightBackend(
        config, authentication=AuthenticationCapability(profiles=manager)
    )
    second_backend.start()
    try:
        second = execute_plan(plan, backend=second_backend)
    finally:
        second_backend.stop()
    assert second.plan_verdict is PlanVerdict.VERIFIED
    second_guard = second.steps[1].receipt.action_evidence
    assert second_guard["branch"] == "target_absent"
    assert second_guard["dispatched"] is False
    assert second_guard["skipped"] is True
    assert second_guard["already_satisfied"] is True
    assert second_guard["guard_expectation_results"][0]["result"] == "pass"
    serialized = second.steps[1].receipt.to_dict()["action_evidence"]
    assert serialized["guarded"] is True
    assert serialized["branch"] == "target_absent"
    assert serialized["target_resolution_result"]["final_candidate_count"] == 0


def test_absent_target_with_failed_guard_condition_is_structured(fixture_url):
    op = _guarded_click(
        fixture_url, "#does-not-exist", _exists("#does-not-exist", False),
        _exists("#text-input", False),
    )
    receipt = execute_plan(ExecutionPlan("guard-fail", [_navigate(fixture_url), op]))
    guarded = receipt.steps[1].receipt
    assert guarded.verdict is Verdict.NOT_VERIFIED
    assert guarded.failure_kind == "guarded_target_absent_condition_not_proven"
    assert guarded.action_evidence["branch"] == "target_absent"
    assert guarded.action_evidence["already_satisfied"] is False


def test_present_target_dispatch_failure_is_not_absent_branch(fixture_url):
    op = _guarded_click(
        fixture_url, '[data-testid="disabled-proceed"]',
        _exists('[data-testid="disabled-proceed"]', True),
        _exists('[data-testid="disabled-proceed"]', False),
    )
    receipt = execute_plan(ExecutionPlan("dispatch-fail", [_navigate(fixture_url), op]))
    guarded = receipt.steps[1].receipt
    assert guarded.verdict is Verdict.EXECUTION_FAILED
    assert guarded.action_evidence["branch"] == "target_present"
    assert guarded.action_evidence["dispatched"] is False


def test_present_target_postcondition_failure_stays_normal(fixture_url):
    op = _guarded_click(
        fixture_url, "#target-control", _exists("#never-created", True),
        _exists("#target-control", False),
    )
    receipt = execute_plan(ExecutionPlan("post-fail", [_navigate(fixture_url), op]))
    guarded = receipt.steps[1].receipt
    assert guarded.verdict is Verdict.NOT_VERIFIED
    assert guarded.action_evidence["branch"] == "target_present"
    assert guarded.failure_kind is None


def test_ambiguous_guard_target_never_enters_absent_branch(fixture_url):
    op = _guarded_click(
        fixture_url, "button", _exists("#target-control", True),
        _exists("#target-control", False),
    )
    receipt = execute_plan(ExecutionPlan("ambiguous", [_navigate(fixture_url), op]))
    guarded = receipt.steps[1].receipt
    assert guarded.verdict is Verdict.EXECUTION_FAILED
    assert guarded.failure_kind.startswith("multiple_after_")
    assert guarded.action_evidence["branch"] is None


def test_backend_guard_probe_failure_never_enters_absent_branch(fixture_url):
    backend = PlaywrightBackend()
    backend.start()
    try:
        backend.ensure_on_url(fixture_url, 10_000)
        op = _guarded_click(
            fixture_url, "#target-control", _exists("#target-control", True),
            _exists("#target-control", False),
        )
        with patch.object(backend, "probe_guarded_action_target", side_effect=RuntimeError("boom")):
            receipt = execute_plan(ExecutionPlan("backend-fail", [op]), backend=backend)
    finally:
        backend.stop()
    guarded = receipt.steps[0].receipt
    assert guarded.verdict is Verdict.EXECUTION_FAILED
    assert guarded.failure_kind == "guard_target_resolution_error"
    assert guarded.action_evidence["branch"] is None


def test_unguarded_missing_target_behavior_is_unchanged(fixture_url):
    op = Operation(
        "missing", fixture_url,
        Action(type=ActionType.CLICK, locator=Locator(LocatorStrategy.CSS, "#missing")),
        expectations=[_exists("#missing", False)],
    )
    receipt = execute_plan(ExecutionPlan("unguarded", [_navigate(fixture_url), op]))
    assert receipt.steps[1].receipt.failure_kind == "zero_after_primary"
    assert "guarded" not in receipt.steps[1].receipt.action_evidence


def _generic_guarded_operation(url: str, guard: OperationGuard) -> Operation:
    return Operation(
        "declared-branches",
        url,
        Action(type=ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "noop-control")),
        expectations=[
            Expectation(
                type=ExpectationType.ELEMENT_VISIBLE,
                locator=Locator(LocatorStrategy.TEST_ID, "result-item"),
                visible=True,
            )
        ],
        guard=guard,
    )


def _present(target: str, expected: bool = True) -> Expectation:
    return Expectation(
        type=ExpectationType.ELEMENT_EXISTS,
        locator=Locator(LocatorStrategy.TEST_ID, target),
        exists=expected,
    )


def _click_target() -> Action:
    return Action(type=ActionType.CLICK, locator=Locator(LocatorStrategy.TEST_ID, "target-control"))


def test_declared_guard_selects_exactly_one_branch_and_retains_plan_session(fixture_url):
    guard = OperationGuard(
        branches=(
            GuardBranch("banner-a", (_present("target-control"),), (_click_target(),)),
            GuardBranch("banner-b", (_present("not-present"),)),
        )
    )
    receipt = execute_plan(
        ExecutionPlan("declared-branch", [_navigate(fixture_url), _generic_guarded_operation(fixture_url, guard)])
    )
    assert receipt.plan_verdict is PlanVerdict.VERIFIED
    step = receipt.steps[1].receipt
    assert step is not None
    evidence = step.action_evidence["guard"]
    assert evidence["selected_branch"] == "banner-a"
    assert evidence["matched_branch_ids"] == ["banner-a"]
    assert evidence["skipped_branches"] == ["banner-b"]
    assert evidence["branch_actions"][0]["dispatched"] is True
    assert receipt.steps[0].browser_session_id == receipt.steps[1].browser_session_id


def test_declared_guard_uses_explicit_otherwise_only(fixture_url):
    guard = OperationGuard(
        branches=(GuardBranch("never", (_present("not-present"),)),),
        otherwise=(_click_target(),),
    )
    receipt = execute_plan(
        ExecutionPlan("guard-fallback", [_navigate(fixture_url), _generic_guarded_operation(fixture_url, guard)])
    )
    step = receipt.steps[1].receipt
    assert step is not None and step.verdict is Verdict.VERIFIED
    evidence = step.action_evidence["guard"]
    assert evidence["selected_branch"] == "otherwise"
    assert evidence["fallback_used"] is True


def test_declared_guard_no_match_is_structured_and_never_dispatches(fixture_url):
    guard = OperationGuard(branches=(GuardBranch("never", (_present("not-present"),)),))
    receipt = execute_plan(
        ExecutionPlan("guard-none", [_navigate(fixture_url), _generic_guarded_operation(fixture_url, guard)])
    )
    step = receipt.steps[1].receipt
    assert step is not None and step.verdict is Verdict.NOT_VERIFIED
    assert step.failure_kind == "guard_no_branch_matched"
    evidence = step.action_evidence["guard"]
    assert evidence["selected_branch"] is None
    assert evidence["primary_action_dispatched"] is False


def test_declared_guard_multiple_matches_fail_closed(fixture_url):
    guard = OperationGuard(
        branches=(
            GuardBranch("one", (_present("target-control"),)),
            GuardBranch("two", (_present("noop-control"),)),
        )
    )
    receipt = execute_plan(
        ExecutionPlan("guard-ambiguous", [_navigate(fixture_url), _generic_guarded_operation(fixture_url, guard)])
    )
    step = receipt.steps[1].receipt
    assert step is not None and step.verdict is Verdict.INDETERMINATE
    assert step.failure_kind == "guard_ambiguous_matches"
    assert step.action_evidence["guard"]["ambiguous_matches"] == ["one", "two"]


def test_declared_guard_stale_condition_fails_closed(fixture_url):
    guard = OperationGuard(
        branches=(GuardBranch("present", (_present("target-control"),), (_click_target(),)),)
    )
    stale = ExpectationResult(
        expectation_id="stale",
        expectation_type="element_exists",
        expected={"exists": True},
        observed={},
        result="indeterminate",
        freshness_ok=False,
    )
    backend = PlaywrightBackend()
    backend.start()
    try:
        backend.ensure_on_url(fixture_url, 10_000)
        with patch("dingdongditch.runtime.executor.evaluate_expectations", return_value=[stale]):
            receipt = execute_plan(
                ExecutionPlan("guard-stale", [_generic_guarded_operation(fixture_url, guard)]),
                backend=backend,
            )
    finally:
        backend.stop()
    step = receipt.steps[0].receipt
    assert step is not None and step.verdict is Verdict.INDETERMINATE
    assert step.failure_kind == "guard_condition_indeterminate"
    assert step.action_evidence["guard"]["failure_reason"] == "guard_condition_indeterminate"
