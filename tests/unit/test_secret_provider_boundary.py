from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from dingdongditch.authentication import (
    AuthenticationCapability,
    AuthenticationError,
    AuthenticationFailureKind,
    MappingSecretProvider,
    SecretProvider,
    SecretReference,
    SecretValue,
)
from dingdongditch.contract.operation import Action, ActionType, Locator, LocatorStrategy


def test_secret_reference_is_resolved_ephemerally_without_receipt_value():
    capability = AuthenticationCapability(
        secrets=MappingSecretProvider({"host://login/password": "very-secret"})
    )
    locator = MagicMock()
    receipt = capability.inject(locator, SecretReference("host://login/password"))
    locator.fill.assert_called_once_with("very-secret")
    assert "very-secret" not in json.dumps(receipt.to_dict())


class _FailureProvider(SecretProvider):
    def resolve(self, reference):
        raise RuntimeError("provider should not leak a secret")


class _SlowProvider(SecretProvider):
    def resolve(self, reference):
        time.sleep(0.2)
        return SecretValue("late-secret")


def test_provider_failure_timeout_and_missing_reference_are_structured():
    locator = MagicMock()
    with pytest.raises(AuthenticationError) as failed:
        AuthenticationCapability(secrets=_FailureProvider()).inject(locator, "provider/failure")
    assert failed.value.kind is AuthenticationFailureKind.SECRET_PROVIDER_FAILED
    assert "should not leak" not in str(failed.value)

    with pytest.raises(AuthenticationError) as timed_out:
        AuthenticationCapability(secrets=_SlowProvider()).inject(
            locator, "provider/slow", timeout_ms=10
        )
    assert timed_out.value.kind is AuthenticationFailureKind.SECRET_PROVIDER_TIMEOUT

    with pytest.raises(AuthenticationError) as missing:
        AuthenticationCapability(secrets=MappingSecretProvider({})).inject(locator, "missing")
    assert missing.value.kind is AuthenticationFailureKind.SECRET_NOT_FOUND


def test_secret_fill_contract_contains_only_opaque_reference():
    action = Action(
        type=ActionType.FILL,
        locator=Locator(strategy=LocatorStrategy.TEST_ID, value="password"),
        secret_reference=SecretReference("host://login/password"),
    )
    action.validate()
    serialized = action.describe()
    assert serialized["secret_reference"] == {"reference_id": "host://login/password"}
    assert "text" not in serialized

    with pytest.raises(ValueError):
        Action(
            type=ActionType.FILL,
            locator=Locator(strategy=LocatorStrategy.TEST_ID, value="password"),
            text="plaintext-secret",
            secret_reference=SecretReference("host://login/password"),
        ).validate()
