"""Fresh Government of Alberta PDF benchmark through DingDongDitch."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from dingdongditch import (
    Action, ActionType, BrowserChannel, BrowserConfig, BrowserEngine,
    BrowserProvider, DownloadChecksumPolicy, DownloadPageEffectPolicy,
    ConstraintType, DownloadRequest, DownloadTriggerAction, ExecutionPlan, Expectation,
    ExpectationType, Locator, NameMatchMode, TargetConstraint,
    LocatorStrategy, Operation, ScreenshotConfig, ScreenshotPolicy,
    TrustedDownloadConfig, execute_plan, inspect_target,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend

ROOT = Path(__file__).resolve().parent
RECEIPTS, SCREENSHOTS = ROOT / "receipts", ROOT / "screenshots"
INSPECTIONS, LOGS, ARTIFACTS = (
    ROOT / "inspections", ROOT / "logs", ROOT / "artifacts"
)
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS, ARTIFACTS):
    directory.mkdir(parents=True, exist_ok=False)

SOURCE_PAGE = (
    "https://www.alberta.ca/staff-directory.cfm"
    "?utm_source=%28direct%29&utm_medium=%28none%29"
    "&utm_campaign=mktg&utm_term=directory"
)
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)
TRUSTED = TrustedDownloadConfig(artifact_root=str(ARTIFACTS))
events: list[dict] = []
receipt_number = 0
inspection_number = 0


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event: str, **detail: object) -> None:
    events.append({"at_unix_ms": int(time.time() * 1000), "event": event, **detail})
    save(LOGS / "run_history.json", events)


def run_plan(
    backend: PlaywrightBackend,
    plan_id: str,
    operations: list[Operation],
    screenshot_policy: ScreenshotPolicy,
):
    global receipt_number
    receipt_number += 1
    receipt = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=operations,
            browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=screenshot_policy, artifact_root=str(SCREENSHOTS)
            ),
            initial_plan_timeout_ms=60_000,
            max_plan_timeout_ms=60_000,
        ),
        backend=backend,
        trusted_download_config=TRUSTED,
    )
    path = RECEIPTS / f"{receipt_number:02d}_{plan_id}.json"
    save(path, receipt.to_dict())
    log(
        "plan", plan_id=plan_id, verdict=receipt.plan_verdict.value,
        completion=receipt.completion_status.value, receipt=str(path),
    )
    return receipt


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict:
    global inspection_number
    inspection_number += 1
    result = inspect_target(backend, locator)
    path = INSPECTIONS / f"{inspection_number:03d}_{label}.json"
    save(path, result)
    log(
        "inspection", label=label, locator=locator.describe(),
        match_count=result.get("match_count"), text=result.get("text"),
        artifact=str(path),
    )
    return result


def main() -> int:
    backend = PlaywrightBackend(CONFIG, trusted_download_config=TRUSTED)
    status = "failed"
    try:
        backend.start()
        log("fresh_browser_started", browser=backend.browser_environment())
        navigation = run_plan(
            backend,
            "navigate_alberta_publication",
            [Operation(
                operation_id="navigate-alberta",
                url=SOURCE_PAGE,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[Expectation(
                    type=ExpectationType.URL, url_value=SOURCE_PAGE
                )],
            )],
            ScreenshotPolicy.AFTER_SUCCESS,
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Alberta navigation plan was not VERIFIED")

        link = Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role="link",
            name="Legislative Branch PDF opens in new window",
            name_match=NameMatchMode.EXACT,
        )
        link_state = inspect(backend, "official_pdf_download_link", link)
        if link_state.get("match_count") != 1 or link_state.get("visible") is not True:
            raise RuntimeError("official Alberta PDF link was not uniquely visible")

        download = run_plan(
            backend,
            "download_one_alberta_pdf",
            [Operation(
                operation_id="download-alberta-pdf",
                url=SOURCE_PAGE,
                action=Action(
                    type=ActionType.DOWNLOAD,
                    locator=link,
                    download_request=DownloadRequest(
                        trigger_action=DownloadTriggerAction.PRESS_KEY,
                        trigger_key="Alt+Enter",
                        preferred_filename="alberta-legislative-branch-directory.pdf",
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
            )],
            ScreenshotPolicy.ALWAYS,
        )
        step = download.steps[0].receipt
        evidence = (
            ((step.action_evidence or {}).get("download") or {})
            if step is not None else {}
        )
        artifact = evidence.get("artifact")
        if (
            step is None or not step.action_executed_successfully
            or evidence.get("state") != "completed" or not artifact
        ):
            raise RuntimeError(
                "DOWNLOAD did not complete: "
                f"{getattr(step, 'failure_kind', None)}"
            )
        assert backend._download_store is not None
        store = backend._download_store
        final = store.root / artifact["relative_path"]
        raw = final.read_bytes()
        independent = hashlib.sha256(raw).hexdigest()
        completed = list(store.completed.rglob("*.pdf"))
        staging = list(store.staging.iterdir())
        if artifact["checksum"] != independent:
            raise RuntimeError("receipt and independent SHA-256 differ")
        if len(raw) != artifact["byte_size"]:
            raise RuntimeError("receipt and independent byte size differ")
        if not raw.startswith(b"%PDF-"):
            raise RuntimeError("artifact does not have a PDF signature")
        if len(completed) != 1 or staging:
            raise RuntimeError(
                f"artifact cardinality/cleanup failed: completed={len(completed)}, "
                f"staging={len(staging)}"
            )
        result = {
            "verdict": "PASS",
            "source_page": SOURCE_PAGE,
            "filename": final.name,
            "byte_size": len(raw),
            "mime_type": artifact["mime_type"],
            "mime_source": artifact["mime_source"],
            "receipt_sha256": artifact["checksum"],
            "independent_sha256": independent,
            "artifact_location": str(final),
            "portable_artifact_location": artifact["relative_path"],
            "completed_pdf_count": len(completed),
            "staging_file_count": len(staging),
            "browser": backend.browser_environment(),
        }
        save(ROOT / "run_result.json", result)
        status = "completed"
        return 0
    except Exception as exc:
        save(
            ROOT / "run_result.json",
            {"verdict": "FAIL", "source_page": SOURCE_PAGE,
             "error": f"{type(exc).__name__}: {exc}"},
        )
        log("benchmark_failed", error=f"{type(exc).__name__}: {exc}")
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
