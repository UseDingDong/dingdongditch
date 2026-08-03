from __future__ import annotations

from types import SimpleNamespace

import pytest

from dingdongditch.contract.application_lifecycle import ApplicationLifecycleState
from dingdongditch.runtime.application_lifecycle import (
    ChatGPTApplicationLifecycleAdapter,
    GeminiApplicationLifecycleAdapter,
    UnknownApplicationLifecycleAdapter,
    select_application_lifecycle_adapter,
)


def observation(
    text: str, *, stop: bool = False, url: str = "https://gemini.google.com/app",
    observation_id: str = "obs",
):
    elements = []
    if stop:
        elements.append({
            "visible": True,
            "accessible_name": "Stop response",
            "visible_text": "",
            "placeholder": "",
        })
    return SimpleNamespace(
        observation_id=observation_id,
        captured_at_ms=1,
        url=url,
        visible_text=[{"text": text}],
        interactive_elements=elements,
    )


def test_adapter_selection_is_exactly_application_bound():
    assert isinstance(
        select_application_lifecycle_adapter("https://gemini.google.com/app"),
        GeminiApplicationLifecycleAdapter,
    )
    assert isinstance(
        select_application_lifecycle_adapter("https://chatgpt.com/"),
        ChatGPTApplicationLifecycleAdapter,
    )
    assert isinstance(
        select_application_lifecycle_adapter("https://chat.openai.com/c/example"),
        ChatGPTApplicationLifecycleAdapter,
    )
    assert isinstance(
        select_application_lifecycle_adapter("https://example.com/gemini.google.com"),
        UnknownApplicationLifecycleAdapter,
    )
    assert isinstance(
        select_application_lifecycle_adapter("https://example.com/chatgpt.com"),
        UnknownApplicationLifecycleAdapter,
    )


def test_unknown_application_is_nonterminal_and_fails_closed():
    adapter = select_application_lifecycle_adapter("https://example.test")
    result = adapter.begin(observation("baseline", url="https://example.test"))
    assert result.state == ApplicationLifecycleState.OBSERVATION_UNAVAILABLE
    assert result.terminal is False
    assert result.fresh is False


def test_gemini_pending_active_stable_and_completed_transitions():
    adapter = GeminiApplicationLifecycleAdapter()
    assert adapter.begin(observation("before")).state == ApplicationLifecycleState.PENDING
    assert adapter.observe(observation("before response", stop=True)).state == ApplicationLifecycleState.ACTIVE
    assert adapter.observe(observation("before response", stop=True)).state == ApplicationLifecycleState.VISUALLY_STABLE
    assert adapter.observe(observation("before response", stop=False)).state == ApplicationLifecycleState.VISUALLY_STABLE
    completed = adapter.observe(observation("before response", stop=False))
    assert completed.state == ApplicationLifecycleState.COMPLETED
    assert completed.terminal is True
    with pytest.raises(TypeError):
        completed.evidence["changed"] = True


def test_persistent_active_control_never_becomes_completed():
    adapter = GeminiApplicationLifecycleAdapter()
    adapter.begin(observation("before"))
    adapter.observe(observation("response", stop=True))
    states = [adapter.observe(observation("response", stop=True)).state for _ in range(10)]
    assert set(states) == {ApplicationLifecycleState.VISUALLY_STABLE}


def test_unfresh_or_misbound_observation_is_unavailable():
    adapter = GeminiApplicationLifecycleAdapter()
    adapter.begin(observation("before"))
    assert adapter.observe(observation("response"), fresh=False).state == ApplicationLifecycleState.OBSERVATION_UNAVAILABLE
    assert adapter.observe(
        observation("response", url="https://example.test")
    ).state == ApplicationLifecycleState.OBSERVATION_UNAVAILABLE


def test_cancellation_requires_verified_dispatch():
    adapter = GeminiApplicationLifecycleAdapter()
    baseline = observation("before")
    adapter.begin(baseline)
    rejected = adapter.record_cancellation(baseline, dispatch_verified=False)
    assert rejected.state == ApplicationLifecycleState.OBSERVATION_UNAVAILABLE
    accepted = adapter.record_cancellation(baseline, dispatch_verified=True)
    assert accepted.state == ApplicationLifecycleState.CANCELLED
    assert accepted.terminal is True


def test_explicit_gemini_failure_indicator_is_terminal_failed():
    adapter = GeminiApplicationLifecycleAdapter()
    adapter.begin(observation("before"))
    failed = adapter.observe(observation("Something went wrong"))
    assert failed.state == ApplicationLifecycleState.FAILED
    assert failed.terminal is True


def test_chatgpt_pending_active_stable_and_completed_transitions():
    adapter = ChatGPTApplicationLifecycleAdapter()
    baseline = observation("before", url="https://chatgpt.com/")
    active = observation("before response", stop=False, url="https://chatgpt.com/")
    active.interactive_elements.append({
        "visible": True,
        "accessible_name": "Stop streaming",
        "visible_text": "",
        "placeholder": "",
    })

    assert adapter.begin(baseline).state == ApplicationLifecycleState.PENDING
    assert adapter.observe(active).state == ApplicationLifecycleState.ACTIVE
    assert adapter.observe(active).state == ApplicationLifecycleState.VISUALLY_STABLE
    inactive = observation("before response", url="https://chatgpt.com/")
    assert adapter.observe(inactive).state == ApplicationLifecycleState.VISUALLY_STABLE
    completed = adapter.observe(inactive)
    assert completed.state == ApplicationLifecycleState.COMPLETED
    assert completed.terminal is True
    assert completed.adapter_id == "chatgpt"


def test_chatgpt_persistent_active_control_never_completes():
    adapter = ChatGPTApplicationLifecycleAdapter()
    adapter.begin(observation("before", url="https://chatgpt.com/"))
    active = observation("response", url="https://chatgpt.com/")
    active.interactive_elements.append({
        "visible": True,
        "accessible_name": "Stop generating",
        "visible_text": "",
        "placeholder": "",
    })
    adapter.observe(active)
    states = [adapter.observe(active).state for _ in range(10)]
    assert set(states) == {ApplicationLifecycleState.VISUALLY_STABLE}


def test_chatgpt_fails_closed_for_cross_application_observation():
    adapter = ChatGPTApplicationLifecycleAdapter()
    adapter.begin(observation("before", url="https://chatgpt.com/"))
    result = adapter.observe(observation("response", url="https://gemini.google.com/app"))
    assert result.state == ApplicationLifecycleState.OBSERVATION_UNAVAILABLE
    assert result.fresh is False


def test_explicit_chatgpt_failure_indicator_is_terminal_failed():
    adapter = ChatGPTApplicationLifecycleAdapter()
    adapter.begin(observation("before", url="https://chatgpt.com/"))
    failed = adapter.observe(observation("Error generating a response", url="https://chatgpt.com/"))
    assert failed.state == ApplicationLifecycleState.FAILED
    assert failed.terminal is True
