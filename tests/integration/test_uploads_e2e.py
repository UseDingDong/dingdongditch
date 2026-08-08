from __future__ import annotations

from pathlib import Path

import pytest

from dingdongditch import (
    Action, ActionType, BrowserConfig, Expectation, ExpectationType, Locator,
    LocatorStrategy, Operation, UploadAuthorization, Verdict, execute_operation,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


FIXTURES = Path(__file__).parents[1] / "fixtures" / "local_test_app"
ONE = (FIXTURES / "upload-one.txt").resolve()
TWO = (FIXTURES / "upload-two.txt").resolve()


@pytest.fixture
def upload_backend(fixture_url):
    url = fixture_url.replace("index.html", "upload_fixture.html")
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    backend.start()
    backend.page.goto(url)
    yield backend, url
    backend.stop()


def _upload(url, testid, files, *, allowed_root=FIXTURES):
    locator = Locator(strategy=LocatorStrategy.TEST_ID, value=testid)
    return Operation(
        operation_id=f"upload-{testid}", url=url,
        action=Action(
            type=ActionType.UPLOAD_FILE, locator=locator,
            upload_authorization=UploadAuthorization(
                tuple(str(path) for path in files),
                allowed_roots=(str(allowed_root.resolve()),),
            ),
        ),
        expectations=[
            Expectation(type=ExpectationType.UPLOAD_FILE_NAMES, locator=locator, file_names=tuple(path.name for path in files)),
            Expectation(type=ExpectationType.UPLOAD_FILE_COUNT, locator=locator, file_count=len(files)),
        ],
        locate_retry_ms=50,
    )


def test_successful_single_upload_and_redacted_receipt(upload_backend):
    backend, url = upload_backend
    receipt = execute_operation(_upload(url, "single-upload", [ONE]), backend=backend)
    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.action_evidence["upload"]["verification_result"] == "pass"
    assert receipt.action_evidence["upload"]["file_count"] == 1
    assert str(FIXTURES.resolve()) not in repr(receipt.to_dict())


def test_successful_multiple_upload(upload_backend):
    backend, url = upload_backend
    receipt = execute_operation(_upload(url, "multi-upload", [ONE, TWO]), backend=backend)
    assert receipt.verdict == Verdict.VERIFIED
    assert receipt.action_evidence["upload"]["observed_file_count"] == 2


@pytest.mark.parametrize("testid,files,failure", [
    ("single-upload", [ONE, TWO], "upload_multiple_not_allowed"),
    ("not-file", [ONE], "upload_target_not_file_input"),
    ("missing", [ONE], "zero_after_primary"),
])
def test_upload_target_failures(upload_backend, testid, files, failure):
    backend, url = upload_backend
    receipt = execute_operation(_upload(url, testid, files), backend=backend)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.failure_kind == failure


def test_upload_ambiguous_locator(upload_backend):
    backend, url = upload_backend
    operation = _upload(url, "single-upload", [ONE])
    operation.action = Action(
        type=ActionType.UPLOAD_FILE,
        locator=Locator(strategy=LocatorStrategy.CSS, value=".ambiguous-upload"),
        upload_authorization=operation.action.upload_authorization,
    )
    receipt = execute_operation(operation, backend=backend)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.failure_kind == "multiple_after_primary"


def test_upload_accept_mismatch(upload_backend, tmp_path):
    backend, url = upload_backend
    image = tmp_path / "image.png"
    image.write_bytes(b"not really an image")
    receipt = execute_operation(_upload(url, "single-upload", [image], allowed_root=tmp_path), backend=backend)
    assert receipt.verdict == Verdict.EXECUTION_FAILED
    assert receipt.failure_kind == "upload_accept_mismatch"


@pytest.mark.parametrize("testid,signal", [
    ("replace-upload", "file_list_match"),
    ("remove-upload", "fresh_visible_filename"),
    ("chip-upload", "attachment_control"),
])
def test_upload_survives_replacement_and_attachment_states(upload_backend, testid, signal):
    backend, url = upload_backend
    receipt = execute_operation(_upload(url, testid, [ONE]), backend=backend)
    upload = receipt.action_evidence["upload"]
    assert upload["execution_result"] == "verified"
    assert upload["verification_result"] == "pass"
    assert upload["verification_signals"][signal] is True
    assert str(ONE.parent) not in repr(receipt.to_dict())


def test_preexisting_filename_is_not_accepted_as_fresh_upload_evidence(upload_backend):
    backend, url = upload_backend
    receipt = execute_operation(_upload(url, "stale-upload", [ONE]), backend=backend)
    assert receipt.failure_kind == "upload_verification_failed"
    assert receipt.action_evidence["upload"]["verification_signals"]["fresh_visible_filename"] is False
