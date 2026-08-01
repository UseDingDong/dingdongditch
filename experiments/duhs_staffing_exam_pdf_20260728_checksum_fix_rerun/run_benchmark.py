"""Checksum-fix rerun: download one public staffing-exam PDF via DingDongDitch."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from dingdongditch import (
    Action,
    ActionType,
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
    ConstraintType,
    DownloadChecksumPolicy,
    DownloadPageEffectPolicy,
    DownloadRequest,
    ExecutionPlan,
    Expectation,
    ExpectationType,
    Locator,
    LocatorStrategy,
    NameMatchMode,
    Operation,
    ScreenshotConfig,
    ScreenshotPolicy,
    TrustedDownloadConfig,
    TargetConstraint,
    execute_plan,
    inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


ROOT = Path(__file__).resolve().parent
RECEIPTS = ROOT / "receipts"
SCREENSHOTS = ROOT / "screenshots"
INSPECTIONS = ROOT / "inspections"
LOGS = ROOT / "logs"
ARTIFACTS = ROOT / "artifacts"
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS, ARTIFACTS):
    directory.mkdir(parents=True, exist_ok=False)

SOURCE_PAGE = (
    "https://www4.duhs.edu.pk/examination/"
    "eexamination-program-recruitment-test-examination-2026-senior-registrar/"
)
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
TRUSTED = TrustedDownloadConfig(artifact_root=str(ARTIFACTS))
events: list[dict] = []
receipt_index = 0
inspection_index = 0


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **detail: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **detail})
    save(LOGS / "run_history.json", events)


def run_plan(
    backend: PlaywrightBackend,
    plan_id: str,
    operations: list[Operation],
    *,
    screenshot_policy: ScreenshotPolicy,
):
    global receipt_index
    receipt_index += 1
    receipt = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=operations,
            browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=screenshot_policy,
                artifact_root=str(SCREENSHOTS),
            ),
            initial_plan_timeout_ms=60_000,
            max_plan_timeout_ms=60_000,
        ),
        backend=backend,
        trusted_download_config=TRUSTED,
    )
    path = RECEIPTS / f"{receipt_index:02d}_{plan_id}.json"
    save(path, receipt.to_dict())
    log(
        "plan",
        plan_id=plan_id,
        verdict=receipt.plan_verdict.value,
        completion=receipt.completion_status.value,
        receipt=str(path),
    )
    return receipt


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict:
    global inspection_index
    inspection_index += 1
    result = inspect_target(backend, locator)
    path = INSPECTIONS / f"{inspection_index:03d}_{label}.json"
    save(path, result)
    log(
        "inspection",
        label=label,
        locator=locator.describe(),
        match_count=result.get("match_count"),
        text=result.get("text"),
        artifact=str(path),
    )
    return result


def main() -> int:
    backend = PlaywrightBackend(CONFIG, trusted_download_config=TRUSTED)
    status = "failed"
    report: dict[str, object] = {"verdict": "FAIL"}
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        nav = run_plan(
            backend,
            "navigate_duhs_recruitment_exam",
            [
                Operation(
                    operation_id="navigate-duhs-exam",
                    url=SOURCE_PAGE,
                    action=Action(type=ActionType.NAVIGATE),
                    expectations=[
                        Expectation(
                            type=ExpectationType.URL,
                            url_value=SOURCE_PAGE,
                        )
                    ],
                )
            ],
            screenshot_policy=ScreenshotPolicy.AFTER_SUCCESS,
        )
        if nav.plan_verdict.value != "VERIFIED":
            raise RuntimeError("OPM source page navigation was not verified")

        link = Locator(
            strategy=LocatorStrategy.CSS,
            value=(
                "a[href*='ENTRY-TEST-RECRUITMENT-TEST-FOR-"
                "SENIOR-REGISTRAR-EXAM-2026.PDF.pdf']"
            ),
            constraints=(
                TargetConstraint(
                    type=ConstraintType.EXCLUDE,
                    exclude_names_exact=(
                        "ENTRY TEST RECRUITMENT TEST FOR SENIOR REGISTRAR "
                        "EXAM – 2026.PDF",
                    ),
                ),
            ),
        )
        state = inspect(backend, "duhs_recruitment_exam_pdf_link", link)
        if state.get("match_count") != 1 or state.get("visible") is not True:
            raise RuntimeError("unique visible DUHS recruitment-exam PDF link not found")

        download_receipt = run_plan(
            backend,
            "download_one_opm_assessment_pdf",
            [
                Operation(
                    operation_id="download-assessment-guide",
                    url=SOURCE_PAGE,
                    action=Action(
                        type=ActionType.DOWNLOAD,
                        locator=link,
                        download_request=DownloadRequest(
                            preferred_filename="duhs-senior-registrar-recruitment-exam.pdf",
                            allowed_extensions=(".pdf",),
                            allowed_mime_types=("application/pdf",),
                            checksum_policy=DownloadChecksumPolicy.SHA256,
                            minimum_bytes=1_024,
                            maximum_bytes=50_000_000,
                            page_effect_policy=(
                                DownloadPageEffectPolicy.ANY_DECLARED_PAGE_EFFECT
                            ),
                            timeout_ms=45_000,
                            correlation_window_ms=1_000,
                            late_event_guard_ms=500,
                        ),
                    ),
                    timeout_ms=50_000,
                )
            ],
            screenshot_policy=ScreenshotPolicy.ALWAYS,
        )
        step = download_receipt.steps[0].receipt
        if step is None:
            raise RuntimeError("download receipt is absent")
        evidence = (step.action_evidence or {}).get("download") or {}
        artifact = evidence.get("artifact")
        if (
            not step.action_executed_successfully
            or evidence.get("state") != "completed"
            or not artifact
        ):
            raise RuntimeError(
                f"download did not complete: {step.failure_kind}: {step.execution_error}"
            )
        assert backend._download_store is not None
        final = backend._download_store.root / artifact["relative_path"]
        payload = final.read_bytes()
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        staging_files = list(backend._download_store.staging.iterdir())
        completed_files = [
            item for item in backend._download_store.completed.rglob("*")
            if item.is_file()
        ]
        if len(completed_files) != 1:
            raise RuntimeError(f"expected one completed file, got {len(completed_files)}")
        if staging_files:
            raise RuntimeError(f"orphaned staging files: {staging_files}")
        if actual_sha256 != artifact.get("checksum"):
            raise RuntimeError("receipt SHA-256 does not match completed bytes")
        if len(payload) != artifact.get("byte_size"):
            raise RuntimeError("receipt byte size does not match completed bytes")
        if not payload.startswith(b"%PDF-"):
            raise RuntimeError("completed artifact lacks a PDF signature")
        report = {
            "verdict": "PASS",
            "source": "Dow University of Health Sciences",
            "source_page": SOURCE_PAGE,
            "filename": final.name,
            "byte_size": len(payload),
            "mime_type": artifact.get("mime_type"),
            "mime_source": artifact.get("mime_source"),
            "sha256": actual_sha256,
            "artifact_location": str(final),
            "portable_artifact_location": artifact.get("relative_path"),
            "completed_files": [str(item) for item in completed_files],
            "staging_files": [],
            "download_receipt": str(
                RECEIPTS / "02_download_one_opm_assessment_pdf.json"
            ),
            "browser": backend.browser_environment(),
        }
        save(ROOT / "run_result.json", report)
        status = "completed"
        return 0
    except Exception as exc:
        report.update({"error": f"{type(exc).__name__}: {exc}"})
        save(ROOT / "run_result.json", report)
        log("benchmark_failed", error=report["error"])
        return 1
    finally:
        before = backend.browser_environment()
        backend.stop()
        after = backend.browser_environment()
        save(
            ROOT / "terminal_browser.json",
            {"status": status, "before_stop": before, "after_stop": after},
        )
        log("browser_stopped", status=status, cleanup_errors=after["cleanup_errors"])


if __name__ == "__main__":
    raise SystemExit(main())
