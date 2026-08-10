from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from dingdongditch import ActionType, BrowserConfig, Locator, LocatorStrategy, SessionStatus, TypingSession, TypingSessionConfig
import dingdongditch.runtime.typing_session as typing_module


class FakeBackend:
    is_started = True
    browser_config = BrowserConfig()
    browser_session_id = "session"
    page_id = "page"

    def exclusive_use(self, scope):
        return nullcontext()


def receipt(operation):
    return SimpleNamespace(
        execution_error=None,
        failure_kind=None,
        operation_id=operation.operation_id,
        action_started_at_ms=1,
        started_at_ms=1,
        finished_at_ms=2,
        action_executed_successfully=True,
        browser={"browser_session_id": "session", "page_id": "page"},
        to_dict=lambda: {"operation_id": operation.operation_id},
    )


def config(text="abc"):
    return TypingSessionConfig(
        session_id="typing",
        url="https://example.test/",
        text=text,
        target_locator=Locator(LocatorStrategy.CSS, value="#editor"),
        max_text_chunk_characters=2,
    )


def test_generic_typing_declares_one_exact_target_and_ordered_input():
    operations = []

    def execute(operation):
        operations.append(operation)
        return receipt(operation)

    result = TypingSession(config(), backend=FakeBackend(), operation_executor=execute).run()

    assert result.status is SessionStatus.COMPLETED
    assert result.typed_characters == 3
    assert operations[0].action.type is ActionType.CLICK
    assert operations[0].action.locator.value == "#editor"
    assert [item.action.type for item in operations[1:]] == [ActionType.PRESS_KEY] * 3
    assert [item.action.key for item in operations[1:]] == ["a", "b", "c"]


def test_generic_typing_does_not_infer_or_recover_unsupported_input():
    result = TypingSession(config("a\x00b"), backend=FakeBackend(), operation_executor=receipt).run()

    assert result.status is SessionStatus.FAILED
    assert result.failure_kind == "unsupported_character"
    assert result.typed_characters == 1


def test_fast_text_dispatch_is_ordered_and_bounded():
    calls = []

    class Keyboard:
        def type(self, text, *, delay):
            calls.append((text, delay))

    backend = FakeBackend()
    backend.page = SimpleNamespace(keyboard=Keyboard())
    result = typing_module.dispatch_typing_text(backend, "batch", "abcdef")

    assert result.dispatched is True
    assert calls == [("abcdef", 0)]
