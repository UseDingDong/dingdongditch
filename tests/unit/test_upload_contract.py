from __future__ import annotations

from pathlib import Path

import pytest

from dingdongditch import Action, ActionType, Locator, LocatorStrategy, Operation, UploadAuthorization, Verdict, execute_operation
from dingdongditch.contract.upload import UploadValidationError


def _action(auth: UploadAuthorization) -> Action:
    return Action(
        type=ActionType.UPLOAD_FILE,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="upload"),
        upload_authorization=auth,
    )


def test_upload_contract_exact_file_and_redacted_description(tmp_path):
    file = tmp_path / "safe.txt"
    file.write_text("safe", encoding="utf-8")
    action = _action(UploadAuthorization((str(file),), allowed_files=(str(file),)))
    action.validate()
    description = action.describe()
    assert description["type"] == "upload_file"
    assert description["upload"]["requested_file_names"] == ["safe.txt"]
    assert str(tmp_path) not in repr(description)


@pytest.mark.parametrize("kind", ["missing", "directory", "outside"])
def test_upload_rejects_invalid_or_unauthorized_paths(tmp_path, kind):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    if kind == "missing":
        requested = allowed / "missing.txt"
        expected = "upload_file_missing"
    elif kind == "directory":
        requested = allowed
        expected = "upload_path_not_file"
    else:
        requested = tmp_path / "outside.txt"
        requested.write_text("x", encoding="utf-8")
        other = tmp_path / "other"
        other.mkdir()
        allowed = other
        expected = "upload_path_not_authorized"
    with pytest.raises(UploadValidationError) as raised:
        _action(UploadAuthorization((str(requested),), allowed_roots=(str(allowed),))).validate()
    assert raised.value.failure_kind == expected


def test_upload_requires_absolute_paths(tmp_path):
    with pytest.raises(UploadValidationError) as raised:
        _action(UploadAuthorization(("relative.txt",), allowed_roots=(str(tmp_path),))).validate()
    assert raised.value.failure_kind == "upload_path_not_absolute"


def test_non_upload_actions_remain_unchanged():
    Action(type=ActionType.NAVIGATE).validate()


def test_invalid_upload_returns_structured_receipt_before_browser_start(tmp_path):
    missing = tmp_path / "missing.txt"
    receipt = execute_operation(Operation(
        operation_id="missing-upload",
        url="https://example.test/upload",
        action=_action(UploadAuthorization((str(missing),), allowed_roots=(str(tmp_path),))),
    ))
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.execution_status == "validation_failed"
    assert receipt.failure_kind == "upload_file_missing"
    assert str(tmp_path) not in repr(receipt.to_dict())
