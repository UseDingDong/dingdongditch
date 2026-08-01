from __future__ import annotations

import json
import threading

from dingdongditch.runtime.run_ownership import acquire_run_generation


def test_generation_is_fully_initialized_before_publication(tmp_path):
    lease = acquire_run_generation(tmp_path)
    try:
        assert lease.path.is_dir()
        assert (lease.path / ".lease").is_file()
        owner = json.loads((lease.path / "owner.json").read_text(encoding="utf-8"))
        assert owner["generation_id"] == lease.generation_id
        assert (tmp_path / "current").read_text(encoding="utf-8") == lease.generation_id
        manifest = json.loads((lease.path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["state"] == "active"
        assert not list((tmp_path / "generations").glob(".building-*"))
    finally:
        lease.close()


def test_concurrent_runs_receive_distinct_owned_generations(tmp_path):
    barrier = threading.Barrier(3)
    leases = []

    def acquire():
        barrier.wait()
        leases.append(acquire_run_generation(tmp_path))

    threads = [threading.Thread(target=acquire) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    try:
        assert all(not thread.is_alive() for thread in threads)
        assert len(leases) == 2
        assert len({lease.generation_id for lease in leases}) == 2
        assert all((lease.path / "owner.json").is_file() for lease in leases)
    finally:
        for lease in leases:
            lease.close()


def test_completion_manifest_is_terminal_and_atomically_published(tmp_path):
    lease = acquire_run_generation(tmp_path)
    lease.finish("completed", receipts=3)
    manifest = json.loads(
        (lease.path / "completion.json").read_text(encoding="utf-8")
    )
    assert manifest["state"] == "terminal"
    assert manifest["outcome"] == "completed"
    assert manifest["detail"] == {"receipts": 3}
    lease.close()
