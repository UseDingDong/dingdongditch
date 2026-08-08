"""Browser coverage for bounded failed-expectation receipt evidence."""

from __future__ import annotations

import json
from unittest.mock import patch

from dingdongditch import (
    Action,
    ActionType,
    Expectation,
    ExpectationType,
    Locator,
    LocatorStrategy,
    Operation,
    Verdict,
    execute_operation,
)


def _tid(value: str) -> Locator:
    return Locator(LocatorStrategy.TEST_ID, value)


def _noop(url: str, expectations: list[Expectation]) -> Operation:
    return Operation(
        "evidence", url,
        Action(ActionType.CLICK, locator=_tid("noop-control")),
        expectations=expectations,
        timeout_ms=500,
    )


def test_failed_expectations_publish_bounded_structured_evidence(fixture_url):
    receipt = execute_operation(
        _noop(
            fixture_url,
            [Expectation(
                ExpectationType.TEXT,
                locator=_tid("state-indicator"),
                text_value="never-observed",
            )],
        )
    )
    assert receipt.verdict is Verdict.NOT_VERIFIED
    assert len(receipt.expectation_evidence or []) == 1
    evidence = receipt.expectation_evidence[0]
    assert evidence["expectation_type"] == "text"
    assert evidence["target"]["resolved_uniquely"] is True
    assert evidence["target"]["structural_fingerprint"]
    assert evidence["structural_evidence"]["tag"] == "div"
    assert evidence["evidence_fresh"] is True


def test_missing_ambiguous_secret_and_large_values_remain_bounded(fixture_url):
    from dingdongditch.backends.playwright_backend import PlaywrightBackend

    backend = PlaywrightBackend()
    backend.start()
    try:
        backend.ensure_on_url(fixture_url, 10_000)
        backend.page.locator('[data-testid="noop-control"]').evaluate(
            """el => { el.setAttribute('data-secret', 'Bearer abcdefghijklmnopqrstuvwxyz');
                            document.querySelector('[data-testid=state-indicator]').textContent = 'x'.repeat(12000); }"""
        )
        secret = execute_operation(
            _noop(
                fixture_url,
                [Expectation(
                    ExpectationType.ATTRIBUTE,
                    locator=_tid("noop-control"),
                    attribute_name="data-secret",
                    attribute_value="not-the-secret",
                )],
            ),
            backend=backend,
        )
        assert secret.verdict is Verdict.NOT_VERIFIED
        secret_evidence = secret.expectation_evidence[0]
        assert secret_evidence["target"]["safe_attributes"]["data-secret"] == "<redacted>"
        assert "abcdefghijkl" not in json.dumps(secret.to_dict())

        missing = execute_operation(
            _noop(
                fixture_url,
                [Expectation(ExpectationType.ELEMENT_VISIBLE, locator=_tid("no-such-target"), visible=True)],
            ),
            backend=backend,
        )
        assert missing.verdict is Verdict.NOT_VERIFIED
        assert missing.expectation_evidence[0]["target"]["resolved_uniquely"] is False

        ambiguous = execute_operation(
            _noop(
                fixture_url,
                [Expectation(
                    ExpectationType.ELEMENT_VISIBLE,
                    locator=Locator(LocatorStrategy.CSS, ".ambiguous-target"),
                    visible=True,
                )],
            ),
            backend=backend,
        )
        assert ambiguous.verdict is Verdict.INDETERMINATE
        assert ambiguous.expectation_evidence[0]["target"]["resolved_uniquely"] is False

        text = execute_operation(
            _noop(
                fixture_url,
                [Expectation(ExpectationType.TEXT, locator=_tid("state-indicator"), text_value="never")],
            ),
            backend=backend,
        )
        serialized = json.dumps(text.to_dict())
        assert "<truncated:" in serialized
        assert len(serialized) < 100_000
    finally:
        backend.stop()


def test_stale_failed_expectation_evidence_is_rejected(fixture_url):
    with patch(
        "dingdongditch.runtime.verifier.is_signal_fresh_for_verification",
        return_value=False,
    ):
        receipt = execute_operation(
            _noop(
                fixture_url,
                [Expectation(ExpectationType.TEXT, locator=_tid("state-indicator"), text_value="idle")],
            )
        )
    assert receipt.verdict is Verdict.INDETERMINATE
    evidence = receipt.expectation_evidence[0]
    assert evidence["evidence_fresh"] is False
