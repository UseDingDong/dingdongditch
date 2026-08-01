from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from dingdongditch import (
    Action,
    ActionType,
    BrowserConfig,
    Locator,
    LocatorStrategy,
    SessionStatus,
    TypingFocusPolicy,
    TypingSession,
    TypingSessionConfig,
)
from dingdongditch.evidence.models import SignalKind
import dingdongditch.runtime.typing_session as typing_module
from experiments.gemini_live_20260731.live_conversation import load_message


class FakeBackend:
    is_started = True
    browser_config = BrowserConfig()

    def __init__(self, focus_states: list[bool]):
        self.focus_states = iter(focus_states)

    def exclusive_use(self, scope):
        return nullcontext()

    def read_element_state(self, locator, frame=None):
        return {
            "match_count": 1,
            "visible": True,
            "focused": next(self.focus_states),
        }

    def read_page_focus_state(self):
        return {
            "focused": True,
            "active_element": {"tag": "body", "contenteditable": False},
        }

    def read_focus_containment(self, locator):
        return True


def successful_receipt(operation, **kwargs):
    return SimpleNamespace(
        execution_error=None,
        failure_kind=None,
        operation_id=operation.operation_id,
        to_dict=lambda: {"operation_id": operation.operation_id},
    )


def successful_key_receipt(backend, operation):
    return SimpleNamespace(
        error=None,
        failure_kind=None,
        operation_id=operation.operation_id,
        to_dict=lambda: {"operation_id": operation.operation_id},
    )


def successful_text_receipt(backend, operation_id, text):
    return SimpleNamespace(
        error=None,
        failure_kind=None,
        operation_id=operation_id,
        key=text,
        to_dict=lambda: {"operation_id": operation_id, "text": text},
    )


def config(text: str = "ab") -> TypingSessionConfig:
    return TypingSessionConfig(
        session_id="typing",
        url="https://example.test/",
        text=text,
        focus_locator=Locator(LocatorStrategy.CSS, value="#editor"),
        verify_every_characters=1,
    )


def test_typing_session_inserts_printable_text(monkeypatch):
    operations = []
    texts = []

    def record(operation, **kwargs):
        operations.append(operation)
        return successful_receipt(operation)

    monkeypatch.setattr(typing_module, "execute_operation", record)
    def record_text(backend, operation_id, text):
        texts.append(text)
        return successful_text_receipt(backend, operation_id, text)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", record_text)
    result = TypingSession(
        config(),
        backend=FakeBackend([True, True]),
    ).run()

    assert result.status == SessionStatus.COMPLETED
    assert result.typed_characters == 2
    assert [item.action.type.value for item in operations] == ["click"]
    assert texts == ["a", "b"]


@pytest.mark.parametrize(
    "message",
    [
        "Hello Gemini.",
        "I'm not a human—I'm another AI assistant.",
        "“Smart quotes”",
        "– en dash",
        "— em dash",
        "Café",
        "こんにちは",
        "مرحبا",
    ],
)
def test_printable_unicode_is_inserted_as_text(message, monkeypatch):
    inserted = []
    pressed = []

    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)

    def record_text(backend, operation_id, text):
        inserted.append(text)
        return successful_text_receipt(backend, operation_id, text)

    def record_key(backend, operation):
        pressed.append(operation.action.key)
        return successful_key_receipt(backend, operation)

    monkeypatch.setattr(typing_module, "dispatch_typing_text", record_text)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", record_key)
    result = TypingSession(
        config(message),
        backend=FakeBackend([True] * (len(message) + 1)),
    ).run()

    assert result.status == SessionStatus.COMPLETED
    assert "".join(inserted) == message
    assert pressed == []


def test_control_character_is_dispatched_as_key(monkeypatch):
    inserted = []
    pressed = []

    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)

    def record_text(backend, operation_id, text):
        inserted.append(text)
        return successful_text_receipt(backend, operation_id, text)

    def record_key(backend, operation):
        pressed.append(operation.action.key)
        return successful_key_receipt(backend, operation)

    monkeypatch.setattr(typing_module, "dispatch_typing_text", record_text)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", record_key)
    result = TypingSession(
        config("a\nb"),
        backend=FakeBackend([True] * 4),
    ).run()

    assert result.status == SessionStatus.COMPLETED
    assert inserted == ["a", "b"]
    assert pressed == ["Enter"]


def test_bom_prefixed_message_dispatches_h_first(tmp_path, monkeypatch):
    message_path = tmp_path / "message.txt"
    message_path.write_bytes(b"\xef\xbb\xbfHello Gemini.")
    texts = []

    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)

    def record_text(backend, operation_id, text):
        texts.append(text)
        return successful_text_receipt(backend, operation_id, text)

    monkeypatch.setattr(typing_module, "dispatch_typing_text", record_text)
    result = TypingSession(
        config(load_message(message_path)),
        backend=FakeBackend([True] * 14),
    ).run()

    assert result.status == SessionStatus.COMPLETED
    assert texts[0] == "H"


def test_typing_session_stops_immediately_when_focus_drifts(monkeypatch):
    operations = []

    def record(operation, **kwargs):
        operations.append(operation)
        return successful_receipt(operation)

    monkeypatch.setattr(typing_module, "execute_operation", record)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", successful_key_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", successful_text_receipt)
    result = TypingSession(
        config("abc"),
        backend=FakeBackend([True, False]),
    ).run()

    assert result.status == SessionStatus.STOPPED
    assert result.failure_kind == "typing_context_lost"
    assert result.typed_characters == 1
    assert len(operations) == 1


def test_page_focus_policy_allows_global_keyboard_listener(monkeypatch):
    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", successful_key_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", successful_text_receipt)
    cfg = TypingSessionConfig(
        **{
            **config("!").__dict__,
            "focus_policy": TypingFocusPolicy.PAGE_FOCUSED_TARGET_VISIBLE,
        }
    )
    result = TypingSession(cfg, backend=FakeBackend([False, False])).run()
    assert result.status == SessionStatus.COMPLETED
    assert result.typed_characters == 1


def test_target_contains_focus_policy_allows_descendant_keyboard_sink(monkeypatch):
    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", successful_key_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", successful_text_receipt)
    cfg = TypingSessionConfig(
        **{
            **config("x").__dict__,
            "focus_policy": TypingFocusPolicy.TARGET_CONTAINS_FOCUS,
        }
    )
    result = TypingSession(cfg, backend=FakeBackend([False, False])).run()
    assert result.status == SessionStatus.COMPLETED
    assert result.typed_characters == 1


def test_acquire_redirected_focus_policy_allows_new_keyboard_sink(monkeypatch):
    class RedirectBackend(FakeBackend):
        def __init__(self):
            super().__init__([False, False])
            self.focus_reads = 0

        def read_page_focus_state(self):
            self.focus_reads += 1
            active = (
                {"tag": "body", "id": "", "contenteditable": False}
                if self.focus_reads == 1
                else {"tag": "textarea", "id": "sink", "contenteditable": False}
            )
            return {"focused": True, "active_element": active}

    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", successful_key_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", successful_text_receipt)
    cfg = TypingSessionConfig(
        **{
            **config("z").__dict__,
            "focus_policy": TypingFocusPolicy.ACQUIRE_REDIRECTED_FOCUS,
        }
    )
    result = TypingSession(cfg, backend=RedirectBackend()).run()
    assert result.status == SessionStatus.COMPLETED
    assert result.typed_characters == 1


def test_keyboard_sink_focused_policy_allows_existing_sink(monkeypatch):
    class SinkBackend(FakeBackend):
        def read_page_focus_state(self):
            return {
                "focused": True,
                "active_element": {
                    "tag": "textarea", "id": "sink", "contenteditable": False
                },
            }

    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", successful_key_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", successful_text_receipt)
    cfg = TypingSessionConfig(
        **{
            **config("q").__dict__,
            "focus_policy": TypingFocusPolicy.KEYBOARD_SINK_FOCUSED,
        }
    )
    result = TypingSession(cfg, backend=SinkBackend([False, False])).run()
    assert result.status == SessionStatus.COMPLETED
    assert result.typed_characters == 1


def test_final_separator_handshake_proves_acceptance(monkeypatch):
    class HandshakeBackend(FakeBackend):
        def __init__(self):
            super().__init__([True, True])
            self.observations = iter([
                SimpleNamespace(
                    observation_id="before",
                    visible_text=[{"text": "49/50"}],
                ),
                SimpleNamespace(
                    observation_id="after",
                    visible_text=[
                        {"text": "wpm"}, {"text": "220"},
                        {"text": "acc"}, {"text": "100%"},
                        {"text": "characters"}, {"text": "2/0/0/0"},
                    ],
                ),
            ])
            self.page = SimpleNamespace(wait_for_timeout=lambda milliseconds: None)

        def observe_page(self):
            return next(self.observations)

    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", successful_key_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", successful_text_receipt)
    cfg = TypingSessionConfig(
        **{
            **config("a ").__dict__,
            "verify_every_characters": 20,
            "final_separator_handshake": True,
        }
    )
    result = TypingSession(cfg, backend=HandshakeBackend()).run()
    assert result.status == SessionStatus.COMPLETED
    assert result.typed_characters == 2
    acceptance = [
        checkpoint for checkpoint in result.checkpoints
        if checkpoint.detail.get("event") == "post_final_separator_acceptance"
    ]
    assert acceptance[0].passed is True
    assert result.completion_evidence == {
        "observation_id": "after",
        "counters": [],
        "has_wpm": True,
        "has_accuracy": True,
        "results_visible": True,
        "results_verified": True,
        "wpm": "220",
        "accuracy": "100",
        "errors": 0,
        "character_breakdown": {
            "correct": 2,
            "incorrect": 0,
            "extra": 0,
            "missed": 0,
            "raw": "2/0/0/0",
        },
    }


def test_results_before_terminal_separator_still_dispatches_full_payload(monkeypatch):
    result_blocks = [
        {"text": "wpm\n240\nacc\n99%\ncharacters\n258/1/0/0"}
    ]

    class EarlyResultsBackend(FakeBackend):
        def __init__(self):
            super().__init__([True, True])
            self.observations = iter([
                SimpleNamespace(observation_id="results-before", visible_text=result_blocks),
                SimpleNamespace(observation_id="results-after", visible_text=result_blocks),
            ])
            self.page = SimpleNamespace(wait_for_timeout=lambda milliseconds: None)

        def observe_page(self):
            return next(self.observations)

    dispatched = []

    def record_text(backend, operation_id, text):
        dispatched.append(text)
        return successful_text_receipt(backend, operation_id, text)

    monkeypatch.setattr(typing_module, "execute_operation", successful_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_key", successful_key_receipt)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", record_text)
    cfg = TypingSessionConfig(
        **{
            **config("a ").__dict__,
            "verify_every_characters": 20,
            "final_separator_handshake": True,
        }
    )
    result = TypingSession(cfg, backend=EarlyResultsBackend()).run()
    assert result.status == SessionStatus.COMPLETED
    assert result.typed_characters == result.requested_characters == 2
    assert dispatched == ["a", " "]
    assert result.completion_evidence["observation_id"] == "results-after"
    assert result.completion_evidence["wpm"] == "240"
    assert result.completion_evidence["accuracy"] == "99"
    assert result.completion_evidence["errors"] == 1
    assert result.completion_evidence["character_breakdown"]["incorrect"] == 1
    handshakes = [
        checkpoint for checkpoint in result.checkpoints
        if checkpoint.detail.get("event") == "end_page_handshake"
    ]
    assert len(handshakes) == 1
    assert handshakes[0].passed is True


def test_typing_session_can_acquire_on_visible_surface_and_verify_sink(monkeypatch):
    operations = []

    def record(operation, **kwargs):
        operations.append(operation)
        return successful_receipt(operation)

    monkeypatch.setattr(typing_module, "execute_operation", record)
    texts = []
    def record_text(backend, operation_id, text):
        texts.append(text)
        return successful_text_receipt(backend, operation_id, text)
    monkeypatch.setattr(typing_module, "dispatch_typing_text", record_text)
    cfg = TypingSessionConfig(
        **{
            **config("a").__dict__,
            "acquire_locator": Locator(LocatorStrategy.CSS, value="#surface"),
        }
    )
    result = TypingSession(cfg, backend=FakeBackend([True])).run()
    assert result.status == SessionStatus.COMPLETED
    assert operations[0].action.locator.value == "#surface"
    assert texts[0] == "a"


def test_fast_key_dispatch_keeps_action_evidence_without_page_observation():
    backend = FakeBackend([True])
    backend.browser_session_id = "session"
    backend.page_id = "page"

    def dispatch(operation, *, collector):
        collector.add(
            kind=SignalKind.ACTION_RESULT,
            collected_at_ms=2,
            payload={"ok": True, "key": operation.action.key},
        )
        return SimpleNamespace(
            ok=True,
            error=None,
            failure_kind=None,
            started_at_ms=1,
            completed_at_ms=2,
            recovery_attempts=[],
        )

    backend.dispatch = dispatch
    receipt = typing_module.dispatch_typing_key(
        backend,
        typing_module.TypingSession(config("a"), backend=backend)._operation(
            "key",
            Action(
                type=ActionType.PRESS_KEY,
                key="a",
                key_scope=typing_module.KeyPressScope.ACTIVE_PAGE,
            ),
        ),
    )
    assert receipt.dispatched is True
    assert receipt.evidence[0]["kind"] == "action_result"
    assert receipt.browser_session_id == "session"
