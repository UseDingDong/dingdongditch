from __future__ import annotations

import threading

from dingdongditch.runtime.file_queue import AtomicFileQueue


def test_concurrent_consumers_claim_each_message_exactly_once(tmp_path):
    queue = AtomicFileQueue(tmp_path)
    count = 40
    for index in range(count):
        queue.publish({"index": index}, message_id=f"message-{index:03d}")
    claimed: list[int] = []
    lock = threading.Lock()

    def consume():
        while True:
            item = queue.claim()
            if item is None:
                return
            with lock:
                claimed.append(item.payload["index"])
            queue.complete(item, {"done": item.payload["index"]})

    workers = [threading.Thread(target=consume) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert sorted(claimed) == list(range(count))
    assert len(list(queue.completed.glob("*.json"))) == count
    assert not list(queue.pending.glob("*.json"))
    assert not list(queue.claimed.glob("*.json"))


def test_duplicate_producer_cannot_overwrite_published_message(tmp_path):
    queue = AtomicFileQueue(tmp_path)
    queue.publish({"producer": 1}, message_id="same")
    try:
        queue.publish({"producer": 2}, message_id="same")
    except FileExistsError:
        pass
    else:
        raise AssertionError("duplicate immutable publication was accepted")
    assert queue.claim().payload == {"producer": 1}
