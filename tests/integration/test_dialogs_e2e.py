from dingdongditch.contract.dialog import DialogAction, DialogContract, DialogRequirement, DialogType
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy, Operation
from dingdongditch.contract.plan import ExecutionPlan, PlanVerdict
from dingdongditch.runtime.plan_executor import execute_plan
from urllib.parse import urljoin
import pytest


def _tid(value):
    return Locator(strategy=LocatorStrategy.TEST_ID, value=value)


def _nav(url):
    return Operation(operation_id="nav-dialog", url=url, action=Action(type=ActionType.NAVIGATE), expectations=[Expectation(type=ExpectationType.ELEMENT_VISIBLE, locator=_tid("dialog-heading"), visible=True)])


def _click(url, target, contract):
    return Operation(operation_id=f"click-{target}", url=url, action=Action(type=ActionType.CLICK, locator=_tid(target)), dialog_contract=contract, expectations=[Expectation(type=ExpectationType.ELEMENT_VISIBLE, locator=_tid("dialog-heading"), visible=True)])


def test_alert_accept_and_history(fixture_url):
    url = urljoin(fixture_url, "dialog_fixture.html")
    receipt = execute_plan(ExecutionPlan(plan_id="alert", operations=[_nav(url), _click(url, "alert-button", DialogContract(requirement=DialogRequirement.REQUIRED, dialog_type=DialogType.ALERT, message="hello alert", action=DialogAction.ACCEPT))]))
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    evidence = receipt.steps[1].receipt.action_evidence
    assert evidence["dialog_appeared"] is True and evidence["dialogs"][0]["contract_authorized"] is True


def test_prompt_accept_and_redact(fixture_url):
    url = urljoin(fixture_url, "dialog_fixture.html")
    receipt = execute_plan(ExecutionPlan(plan_id="prompt", operations=[_nav(url), _click(url, "prompt-button", DialogContract(requirement=DialogRequirement.REQUIRED, dialog_type=DialogType.PROMPT, action=DialogAction.ACCEPT, prompt_text="secret", redact_prompt_text=True))]))
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.steps[1].receipt.action_evidence["dialogs"][0]["prompt_text"] == "[REDACTED]"


def test_confirm_dismiss(fixture_url):
    url = urljoin(fixture_url, "dialog_fixture.html")
    receipt = execute_plan(ExecutionPlan(plan_id="confirm", operations=[_nav(url), _click(url, "confirm-button", DialogContract(requirement=DialogRequirement.REQUIRED, dialog_type=DialogType.CONFIRM, message="confirm me", action=DialogAction.DISMISS))]))
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.steps[1].receipt.action_evidence["dialogs"][0]["action_taken"] == "dismiss"


@pytest.mark.xfail(reason="Playwright Chromium does not consistently surface beforeunload as a Dialog event", strict=False)
def test_beforeunload_is_contract_handled(fixture_url):
    source = urljoin(fixture_url, "dialog_fixture.html")
    target = urljoin(fixture_url, "popup_target.html")
    receipt = execute_plan(ExecutionPlan(plan_id="beforeunload", operations=[_nav(source), Operation(operation_id="leave", url=target, action=Action(type=ActionType.NAVIGATE), dialog_contract=DialogContract(requirement=DialogRequirement.REQUIRED, dialog_type=DialogType.BEFOREUNLOAD, action=DialogAction.DISMISS), expectations=[Expectation(type=ExpectationType.ELEMENT_VISIBLE, locator=_tid("popup-heading"), visible=True)])]))
    assert receipt.plan_verdict == PlanVerdict.VERIFIED
    assert receipt.steps[1].receipt.action_evidence["dialogs"][0]["dialog_type"] == "beforeunload"


def test_unexpected_dialog_fails_without_hanging(fixture_url):
    url = urljoin(fixture_url, "dialog_fixture.html")
    receipt = execute_plan(ExecutionPlan(plan_id="unexpected-dialog", operations=[_nav(url), _click(url, "alert-button", DialogContract())]))
    failed = receipt.steps[1].receipt
    assert failed.failure_kind == "unexpected_dialog"
    assert failed.action_evidence["dialogs"][0]["cleanup_only"] is True


def test_missing_required_dialog(fixture_url):
    url = urljoin(fixture_url, "dialog_fixture.html")
    receipt = execute_plan(ExecutionPlan(plan_id="missing-dialog", operations=[_nav(url), _click(url, "no-dialog-button", DialogContract(requirement=DialogRequirement.REQUIRED, dialog_type=DialogType.ALERT, timeout_ms=200))]))
    assert receipt.steps[1].receipt.failure_kind == "expected_dialog_not_appeared"


def test_wrong_message_and_multiple_dialogs(fixture_url):
    url = urljoin(fixture_url, "dialog_fixture.html")
    wrong = execute_plan(ExecutionPlan(plan_id="wrong-message", operations=[_nav(url), _click(url, "alert-button", DialogContract(requirement=DialogRequirement.REQUIRED, dialog_type=DialogType.ALERT, message="wrong"))]))
    assert wrong.steps[1].receipt.failure_kind == "dialog_message_mismatch"
    two = execute_plan(ExecutionPlan(plan_id="two-dialogs", operations=[_nav(url), _click(url, "two-dialog-button", DialogContract(requirement=DialogRequirement.REQUIRED, dialog_type=DialogType.ALERT))]))
    assert two.steps[1].receipt.failure_kind == "multiple_dialogs_opened"
