from __future__ import annotations

import json
import threading

from dingdongditch.runtime.publication import (
    PublicationUnavailableError,
    append_json_line,
    publish_json,
    publish_text,
    read_published_json,
)


def test_json_publication_is_never_partial_under_polling(tmp_path):
    destination = tmp_path / "artifact.json"
    values = [{"generation": index, "payload": "x" * 50_000} for index in range(30)]
    allowed = values
    barrier = threading.Barrier(2)
    observed = []

    def writer():
        barrier.wait()
        for value in values:
            publish_json(destination, value)

    def reader():
        barrier.wait()
        for _ in range(1_000):
            try:
                observed.append(read_published_json(destination))
            except PublicationUnavailableError:
                pass

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert all(value in allowed for value in observed)
    assert json.loads(destination.read_text(encoding="utf-8")) == values[-1]


def test_atomic_jsonl_append_never_exposes_partial_record(tmp_path):
    destination = tmp_path / "events.jsonl"
    for index in range(25):
        append_json_line(destination, {"sequence": index})
        lines = destination.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["sequence"] for line in lines] == list(range(index + 1))


def test_unique_temporary_names_allow_concurrent_publishers(tmp_path):
    destination = tmp_path / "status.txt"
    payloads = [f"complete-{index}" for index in range(20)]
    threads = [threading.Thread(target=publish_text, args=(destination, value)) for value in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert destination.read_text(encoding="utf-8") in payloads
    assert not list(tmp_path.glob(".status.txt.*.tmp"))
