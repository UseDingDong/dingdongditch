from pathlib import Path
import hashlib
import os
import threading

import pytest

from dingdongditch import (
    Action, ActionType, BrowserConfig, DownloadArtifactStore,
    DownloadCollisionPolicy, DownloadFailureReason, DownloadPolicy,
    DownloadRequest, Locator, LocatorStrategy,
    TrustedDownloadConfig,
)
from dingdongditch.contract.download import (
    DownloadChecksumPolicy, DownloadDeadline, DownloadIntegrityVerifier,
    DownloadMimeSource, DownloadSecurityError, SafeFilenameResolver,
)
from dingdongditch.plan_json import plan_document_from_dict


def test_download_action_is_typed_and_serializes():
    action = Action(
        type=ActionType.DOWNLOAD,
        locator=Locator(strategy=LocatorStrategy.CSS, value="#download"),
        download_request=DownloadRequest(
            preferred_filename="report.txt",
            allowed_extensions=(".txt",),
        ),
    )
    action.validate()
    assert action.describe()["download_request"]["checksum_policy"] == "sha256"


@pytest.mark.parametrize(
    "name",
    ["../evil.txt", r"..\evil.txt", r"C:\evil.txt", r"\\server\share.txt",
     "CON.txt", "name:stream", "...\u0000.txt", "%2e%2e%2fevil.txt"],
)
def test_filename_security_rejects_path_and_platform_attacks(name):
    with pytest.raises(DownloadSecurityError):
        SafeFilenameResolver(DownloadPolicy()).filename(name)


@pytest.mark.parametrize(
    "subdir",
    ["../escape", r"..\escape", "/absolute", r"C:\absolute", r"\\server\share",
     "safe/../escape", "safe./child", "CON/child"],
)
def test_subdirectory_security_rejects_escape(subdir):
    with pytest.raises(DownloadSecurityError):
        SafeFilenameResolver(DownloadPolicy()).subdirectory(subdir)


def test_store_commits_under_session_root_and_hashes(tmp_path):
    store = DownloadArtifactStore(
        TrustedDownloadConfig(artifact_root=str(tmp_path)),
        DownloadPolicy(), "session",
    )
    staging = store.new_staging_path()
    staging.write_bytes(b"hello")
    artifact = store.commit(
        staging,
        "hello.txt",
        DownloadRequest(allowed_extensions=(".txt",), minimum_bytes=5),
        "hello.txt",
        response_mime="text/plain",
        deadline=DownloadDeadline(10**15),
    )
    final = Path(artifact.final_path)
    assert final.read_bytes() == b"hello"
    assert store.root in final.parents
    assert artifact.checksum_algorithm == "sha256"
    portable = artifact.to_dict()
    assert "final_path" not in portable
    assert str(tmp_path) not in str(portable)


def test_concurrent_download_commits_are_serialized_and_complete(tmp_path):
    store = DownloadArtifactStore(
        TrustedDownloadConfig(artifact_root=str(tmp_path)),
        DownloadPolicy(), "concurrent-session",
    )
    staged = []
    for payload in (b"first-complete", b"second-complete"):
        path = store.new_staging_path()
        path.write_bytes(payload)
        staged.append(path)
    artifacts = []

    def commit(path):
        artifacts.append(
            store.commit(
                path,
                "result.txt",
                DownloadRequest(
                    collision_policy=DownloadCollisionPolicy.UNIQUIFY,
                    allowed_extensions=(".txt",),
                ),
                "result.txt",
                response_mime="text/plain",
                deadline=DownloadDeadline(10**15),
            )
        )

    threads = [threading.Thread(target=commit, args=(path,)) for path in staged]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert len(artifacts) == 2
    contents = {Path(item.final_path).read_bytes() for item in artifacts}
    assert contents == {b"first-complete", b"second-complete"}


def test_collision_reject_preserves_existing_file(tmp_path):
    store = DownloadArtifactStore(
        TrustedDownloadConfig(artifact_root=str(tmp_path)),
        DownloadPolicy(), "session",
    )
    first = store.new_staging_path()
    first.write_bytes(b"one")
    store.commit(
        first, "same.txt", DownloadRequest(), "same.txt",
        response_mime="text/plain", deadline=DownloadDeadline(10**15),
    )
    second = store.new_staging_path()
    second.write_bytes(b"two")
    with pytest.raises(DownloadSecurityError) as caught:
        store.commit(
            second, "same.txt",
            DownloadRequest(collision_policy=DownloadCollisionPolicy.REJECT),
            "same.txt",
            response_mime="text/plain",
            deadline=DownloadDeadline(10**15),
        )
    assert caught.value.reason == DownloadFailureReason.COLLISION_REJECTED


def test_json_download_round_trip_contract(tmp_path):
    plan = plan_document_from_dict({
        "browser": {
            "headless": True,
            "download_policy": {"max_filename_length": 180},
        },
        "plan": {
            "plan_id": "download",
            "operations": [{
                "operation_id": "get",
                "url": "https://example.test/",
                "action": {
                    "type": "download",
                    "locator": {"strategy": "css", "value": "#get"},
                    "download_request": {
                        "preferred_filename": "report.txt",
                        "allowed_extensions": [".txt"],
                    },
                },
            }],
        },
    })
    assert plan.operations[0].action.type == ActionType.DOWNLOAD
    assert plan.browser_config.download_policy.max_filename_length == 180


@pytest.mark.parametrize(
    "root",
    ["/tmp/escape", "relative/escape", r"C:\escape", r"\\server\share"],
)
def test_plan_json_rejects_download_artifact_root(root):
    with pytest.raises(ValueError, match="artifact_root"):
        plan_document_from_dict({
            "browser": {
                "download_policy": {
                    "max_filename_length": 180,
                    "artifact_root": root,
                },
            },
            "plan": {"plan_id": "unsafe", "operations": []},
        })


def test_host_root_cannot_be_overridden_by_plan(tmp_path):
    document = plan_document_from_dict({
        "browser": {"download_policy": {"max_filename_length": 180}},
        "plan": {
            "plan_id": "safe",
            "operations": [{
                "operation_id": "navigate",
                "url": "https://example.test/",
                "action": {"type": "navigate"},
            }],
        },
    })
    assert not hasattr(document.browser_config.download_policy, "artifact_root")
    store = DownloadArtifactStore(
        TrustedDownloadConfig(artifact_root=str(tmp_path / "host-owned")),
        document.browser_config.download_policy,
        "session",
    )
    assert store.artifact_root == (tmp_path / "host-owned").absolute()
    store.close()


@pytest.mark.parametrize(
    ("name", "maximum", "accepted"),
    [
        ("a." + ("x" * 30), 20, False),
        ("a." + ("x" * 19), 20, False),
        ("a." + ("x" * 17), 20, True),
        (".profile", 20, True),
        ("archive." + ("é" * 130), 180, False),
    ],
)
def test_filename_length_invariant(name, maximum, accepted):
    resolver = SafeFilenameResolver(DownloadPolicy(max_filename_length=maximum))
    if not accepted:
        with pytest.raises(DownloadSecurityError) as caught:
            resolver.filename(name)
        assert caught.value.reason == DownloadFailureReason.FILENAME_REJECTED
    else:
        resolved, _ = resolver.filename(name)
        assert len(resolved) <= maximum
        assert len(resolved.encode("utf-8")) <= 255


def test_mime_allowlist_does_not_trust_extension(tmp_path):
    path = tmp_path / "payload.txt"
    path.write_bytes(b"MZ" + bytes(64))
    fd = path.open("rb")
    try:
        with pytest.raises(DownloadSecurityError) as caught:
            DownloadIntegrityVerifier.verify_handle(
                fd.fileno(),
                DownloadRequest(
                    allowed_mime_types=("text/plain",),
                    checksum_policy=DownloadChecksumPolicy.NONE,
                ),
                DownloadPolicy(),
                logical_filename="payload.txt",
                response_mime=None,
                deadline=DownloadDeadline(10**15),
            )
        assert caught.value.reason == DownloadFailureReason.MIME_TYPE_NOT_ALLOWED
    finally:
        fd.close()


def test_response_mime_is_normalized_and_authoritative(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"plain text\n")
    with path.open("rb") as handle:
        result = DownloadIntegrityVerifier.verify_handle(
            handle.fileno(),
            DownloadRequest(allowed_mime_types=("text/plain",)),
            DownloadPolicy(),
            logical_filename="payload.bin",
            response_mime=" Text/Plain; charset=UTF-8 ",
            deadline=DownloadDeadline(10**15),
        )
    assert result[1] == "text/plain"
    assert result[2] == DownloadMimeSource.RESPONSE_HEADER.value


def test_missing_mime_fails_closed_unless_host_allows_unknown(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(bytes([0, 1, 2, 3]))
    request = DownloadRequest(allowed_mime_types=("application/octet-stream",))
    with path.open("rb") as handle:
        with pytest.raises(DownloadSecurityError):
            DownloadIntegrityVerifier.verify_handle(
                handle.fileno(), request, DownloadPolicy(),
                logical_filename="payload.bin", response_mime=None,
                deadline=DownloadDeadline(10**15),
            )
    with path.open("rb") as handle:
        result = DownloadIntegrityVerifier.verify_handle(
            handle.fileno(), request, DownloadPolicy(allow_unknown_mime=True),
            logical_filename="payload.bin", response_mime=None,
            deadline=DownloadDeadline(10**15),
        )
    assert result[2] == DownloadMimeSource.UNKNOWN.value


def test_downloads_symlink_causes_no_external_mutation(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    try:
        (artifact_root / "downloads").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable for this account")
    with pytest.raises(DownloadSecurityError):
        DownloadArtifactStore(
            TrustedDownloadConfig(artifact_root=str(artifact_root)),
            DownloadPolicy(), "session",
        )
    assert list(external.iterdir()) == []


def test_prior_session_recovery_preserves_completed_and_unknown(tmp_path):
    config = TrustedDownloadConfig(
        artifact_root=str(tmp_path), recovery_stale_after_seconds=60
    )
    old = DownloadArtifactStore(config, DownloadPolicy(), "old")
    staged = old.new_staging_path()
    staged.write_bytes(b"abandoned")
    completed = old.completed / "keep.txt"
    completed.write_bytes(b"keep")
    unknown = old.staging / "unknown.file"
    unknown.write_bytes(b"unknown")
    old.close()
    marker = old.root / ".ddd-session.json"
    import os
    import time
    old_time = time.time() - 120
    os.utime(marker, (old_time, old_time))
    current = DownloadArtifactStore(config, DownloadPolicy(), "current")
    report = current.recover_abandoned_sessions(deadline=DownloadDeadline(10**15))
    assert str(staged) in report["removed"]
    assert completed.read_bytes() == b"keep"
    assert unknown.read_bytes() == b"unknown"
    assert current.recover_abandoned_sessions(
        deadline=DownloadDeadline(10**15)
    )["removed"] == []
    current.close()


def test_committed_artifact_is_not_aliased_to_open_staging_writer(tmp_path):
    """A producer retaining its handle must not mutate completed bytes."""
    store = DownloadArtifactStore(
        TrustedDownloadConfig(artifact_root=str(tmp_path)),
        DownloadPolicy(),
        "session",
    )
    staging = store.new_staging_path()
    original = b"%PDF-1.7\n" + (b"immutable-download-bytes\n" * 64)
    staging.write_bytes(original)
    producer_fd = os.open(staging, os.O_RDWR)
    try:
        artifact = store.commit(
            staging,
            "assessment.pdf",
            DownloadRequest(
                allowed_extensions=(".pdf",),
                allowed_mime_types=("application/pdf",),
            ),
            "assessment.pdf",
            response_mime="application/pdf",
            deadline=DownloadDeadline(10**15),
        )
        os.lseek(producer_fd, 0, os.SEEK_SET)
        os.write(producer_fd, b"X" * len(original))
        os.fsync(producer_fd)
    finally:
        os.close(producer_fd)
    completed = Path(artifact.final_path)
    assert completed.read_bytes() == original
    assert artifact.checksum == hashlib.sha256(completed.read_bytes()).hexdigest()
    store.close()


def test_windows_binary_pdf_receipt_hashes_exact_committed_bytes(tmp_path):
    store = DownloadArtifactStore(
        TrustedDownloadConfig(artifact_root=str(tmp_path)),
        DownloadPolicy(),
        "session",
    )
    staging = store.new_staging_path()
    payload = b"%PDF-1.7\r\nbinary\x1a\x00\r\nstream\nendstream\r\n"
    staging.write_bytes(payload)
    artifact = store.commit(
        staging,
        "binary.pdf",
        DownloadRequest(
            allowed_extensions=(".pdf",),
            allowed_mime_types=("application/pdf",),
        ),
        "binary.pdf",
        response_mime="application/pdf; charset=binary",
        deadline=DownloadDeadline(10**15),
    )
    completed = Path(artifact.final_path)
    assert completed.read_bytes() == payload
    assert artifact.byte_size == len(payload)
    assert artifact.checksum == hashlib.sha256(payload).hexdigest()
    store.close()
