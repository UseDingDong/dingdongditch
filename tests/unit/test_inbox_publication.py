from __future__ import annotations

import os
import threading
from pathlib import Path

import dingdongditch.runtime.publication as publication_module
from dingdongditch.runtime.inbox import publish_text, read_published_text
from experiments.gemini_live_20260731.live_conversation import load_message


def test_reader_never_observes_empty_published_message(tmp_path, monkeypatch):
    destination = tmp_path / "message.txt"
    replace_reached = threading.Event()
    allow_replace = threading.Event()
    real_replace = os.replace

    def blocked_replace(source, target):
        replace_reached.set()
        assert allow_replace.wait(timeout=5)
        real_replace(source, target)

    monkeypatch.setattr(publication_module.os, "replace", blocked_replace)
    publisher = threading.Thread(target=publish_text, args=(destination, "complete"))
    publisher.start()

    assert replace_reached.wait(timeout=5)
    assert not destination.exists()
    allow_replace.set()
    publisher.join(timeout=5)

    assert not publisher.is_alive()
    assert read_published_text(destination) == "complete"


def test_reader_never_observes_partially_written_published_message(tmp_path, monkeypatch):
    destination = tmp_path / "message.txt"
    publish_text(destination, "previous complete message")
    replace_reached = threading.Event()
    allow_replace = threading.Event()
    real_replace = os.replace

    def blocked_replace(source, target):
        replace_reached.set()
        assert allow_replace.wait(timeout=5)
        real_replace(source, target)

    monkeypatch.setattr(publication_module.os, "replace", blocked_replace)
    replacement = "replacement " * 10_000
    publisher = threading.Thread(target=publish_text, args=(destination, replacement))
    publisher.start()

    assert replace_reached.wait(timeout=5)
    assert destination.read_text(encoding="utf-8") == "previous complete message"
    allow_replace.set()
    publisher.join(timeout=5)

    assert not publisher.is_alive()
    assert read_published_text(destination) == replacement


def test_publication_is_atomic_under_concurrent_polling(tmp_path):
    destination = tmp_path / "message.txt"
    payloads = [f"message-{index}:" + chr(65 + index % 26) * 100_000 for index in range(40)]
    allowed = set(payloads)
    start = threading.Barrier(2)
    observed: list[str | None] = []

    def writer():
        start.wait()
        for payload in payloads:
            publish_text(destination, payload)

    def reader():
        start.wait()
        for _ in range(2_000):
            observed.append(read_published_text(destination))

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    writer_thread.start()
    reader_thread.start()
    writer_thread.join(timeout=15)
    reader_thread.join(timeout=15)

    assert not writer_thread.is_alive()
    assert not reader_thread.is_alive()
    assert observed
    assert all(value is None or value in allowed for value in observed)
    assert read_published_text(destination) == payloads[-1]


def test_conversation_message_loading_behavior_is_preserved(tmp_path):
    destination = tmp_path / "message.txt"

    assert load_message(destination) is None
    destination.write_bytes(b"")
    assert load_message(destination) is None

    publish_text(destination, "Hello Gemini.")
    assert load_message(destination) == "Hello Gemini."

    destination.write_bytes(b"\xef\xbb\xbfLegacy message.")
    assert load_message(destination) == "Legacy message."
