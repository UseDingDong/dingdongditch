from __future__ import annotations

import pytest

from dingdongditch.runtime.session import (
    ManagedSession,
    SessionLifecycleState,
    SessionStatus,
)


class ExampleSession(ManagedSession):
    def run(self):
        self.begin()
        self.finish(SessionStatus.COMPLETED)


def test_managed_session_has_explicit_single_use_lifecycle():
    session = ExampleSession()
    assert session.lifecycle_state == SessionLifecycleState.NEW
    session.run()
    assert session.lifecycle_state == SessionLifecycleState.COMPLETED
    with pytest.raises(RuntimeError, match="cannot start"):
        session.run()


def test_session_cannot_finish_without_ownership():
    session = ExampleSession()
    with pytest.raises(RuntimeError, match="cannot finish"):
        session.finish(SessionStatus.FAILED)
