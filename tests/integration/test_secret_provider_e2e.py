from __future__ import annotations

import json

from dingdongditch import (
    Action, ActionType, AuthenticationCapability, Expectation, ExpectationType,
    Locator, LocatorStrategy, MappingSecretProvider, Operation, SecretReference,
    Verdict, execute_operation,
)


def test_runtime_secret_fill_resolves_once_and_redacts_receipt(fixture_url):
    secret = "runtime-only-secret"
    receipt = execute_operation(
        Operation(
            operation_id="secret-fill",
            url=fixture_url,
            action=Action(
                type=ActionType.FILL,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="text-input"),
                secret_reference=SecretReference("host://fixture/text"),
            ),
            expectations=[Expectation(
                type=ExpectationType.ATTRIBUTE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="state-indicator"),
                attribute_name="data-state",
                attribute_value="filled",
            )],
        ),
        authentication=AuthenticationCapability(
            secrets=MappingSecretProvider({"host://fixture/text": secret})
        ),
    )
    assert receipt.verdict is Verdict.VERIFIED, receipt.to_dict()
    serialized = json.dumps(receipt.to_dict())
    assert secret not in serialized
    assert receipt.action_evidence["ephemeral_fill"]["status"] == "resolved"
