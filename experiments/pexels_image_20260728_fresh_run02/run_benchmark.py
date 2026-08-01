"""Fresh Pexels image download benchmark through DingDongDitch."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from dingdongditch import (
    Action, ActionType, BrowserChannel, BrowserConfig, BrowserEngine,
    BrowserProvider, DownloadChecksumPolicy, DownloadPageEffectPolicy,
    DownloadRequest, DownloadTriggerAction, ExecutionPlan, Expectation,
    ExpectationType, Locator, LocatorStrategy, NameMatchMode, Operation,
    ScreenshotConfig, ScreenshotPolicy, TrustedDownloadConfig, execute_plan,
    inspect_target, ConstraintType, TargetConstraint,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend

ROOT = Path(__file__).resolve().parent
RECEIPTS, SCREENSHOTS = ROOT / "receipts", ROOT / "screenshots"
INSPECTIONS, LOGS, ARTIFACTS = (
    ROOT / "inspections", ROOT / "logs", ROOT / "artifacts"
)
for directory in (RECEIPTS, SCREENSHOTS, INSPECTIONS, LOGS, ARTIFACTS):
    directory.mkdir(parents=True, exist_ok=False)

SOURCE_PAGE = "https://www.pexels.com/photo/landscape-photo-of-mountains-939714/"
DESCRIPTION = (
    "Breathtaking view of snow-capped mountains, green meadows, "
    "and a clear blue sky"
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


def plan(
    backend: PlaywrightBackend,
    plan_id: str,
    operations: list[Operation],
    policy: ScreenshotPolicy,
):
    global receipt_index
    receipt_index += 1
    result = execute_plan(
        ExecutionPlan(
            plan_id=plan_id,
            operations=operations,
            browser_config=CONFIG,
            screenshot_config=ScreenshotConfig(
                policy=policy, artifact_root=str(SCREENSHOTS)
            ),
            initial_plan_timeout_ms=60_000,
            max_plan_timeout_ms=60_000,
        ),
        backend=backend,
        trusted_download_config=TRUSTED,
    )
    path = RECEIPTS / f"{receipt_index:02d}_{plan_id}.json"
    save(path, result.to_dict())
    log(
        "plan", plan_id=plan_id, verdict=result.plan_verdict.value,
        completion=result.completion_status.value, receipt=str(path),
    )
    return result


def inspect(backend: PlaywrightBackend, label: str, locator: Locator) -> dict:
    global inspection_index
    inspection_index += 1
    result = inspect_target(backend, locator)
    path = INSPECTIONS / f"{inspection_index:03d}_{label}.json"
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
        navigation = plan(
            backend,
            "navigate_pexels_photo",
            [Operation(
                operation_id="navigate-pexels",
                url=SOURCE_PAGE,
                action=Action(type=ActionType.NAVIGATE),
                expectations=[Expectation(
                    type=ExpectationType.URL, url_value=SOURCE_PAGE
                )],
            )],
            ScreenshotPolicy.AFTER_SUCCESS,
        )
        if navigation.plan_verdict.value != "VERIFIED":
            raise RuntimeError("Pexels navigation was not VERIFIED")

        body = inspect(
            backend, "photo_page_body",
            Locator(strategy=LocatorStrategy.CSS, value="body"),
        )
        body_text = body.get("text") or ""
        if DESCRIPTION.lower() not in body_text.lower():
            raise RuntimeError("visible photo description was not observed")
        if "free to use" not in body_text.lower():
            raise RuntimeError("visible free-use statement was not observed")
        if "accept all cookies" in body_text.lower():
            consent = plan(
                backend,
                "accept_cookie_consent",
                [Operation(
                    operation_id="accept-cookies",
                    url=SOURCE_PAGE,
                    action=Action(
                        type=ActionType.CLICK,
                        locator=Locator(
                            strategy=LocatorStrategy.ROLE_NAME,
                            role="button",
                            name="Accept All Cookies",
                            name_match=NameMatchMode.EXACT,
                        ),
                    ),
                )],
                ScreenshotPolicy.ON_FAILURE,
            )
            if not consent.steps[0].receipt.action_executed_successfully:
                raise RuntimeError("cookie consent could not be dismissed")

        download_link = Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role="link",
            name="Free download",
            name_match=NameMatchMode.EXACT,
            constraints=(
                TargetConstraint(type=ConstraintType.VISIBLE, visible=True),
            ),
        )
        link_state = inspect(backend, "free_jpg_download_link", download_link)
        if link_state.get("match_count") != 1 or link_state.get("visible") is not True:
            raise RuntimeError("unique visible free JPG download link not found")

        receipt = plan(
            backend,
            "download_one_free_pexels_photo",
            [Operation(
                operation_id="download-photo",
                url=SOURCE_PAGE,
                action=Action(
                    type=ActionType.DOWNLOAD,
                    locator=download_link,
                    download_request=DownloadRequest(
                        trigger_action=DownloadTriggerAction.PRESS_KEY,
                        trigger_key="Alt+Enter",
                        preferred_filename="pexels-mountain-landscape.jpg",
                        allowed_extensions=(".jpg",),
                        allowed_mime_types=("image/jpeg",),
                        checksum_policy=DownloadChecksumPolicy.SHA256,
                        minimum_bytes=2_000_000,
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
        step = receipt.steps[0].receipt
        download = (
            ((step.action_evidence or {}).get("download") or {})
            if step is not None else {}
        )
        artifact = download.get("artifact")
        if (
            step is None or not step.action_executed_successfully
            or download.get("state") != "completed" or not artifact
        ):
            raise RuntimeError(
                f"DOWNLOAD did not complete: {getattr(step, 'failure_kind', None)}"
            )
        assert backend._download_store is not None
        store = backend._download_store
        final = store.root / artifact["relative_path"]
        raw = final.read_bytes()
        independent = hashlib.sha256(raw).hexdigest()
        extension = final.suffix.lower()
        jpeg_signature = raw.startswith(b"\xff\xd8\xff")
        completed = [
            item for item in store.completed.rglob("*")
            if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]
        staging = list(store.staging.iterdir())
        temporary = list(store.completed.rglob("*.commit"))
        if artifact["checksum"] != independent:
            raise RuntimeError("receipt and independent SHA-256 differ")
        if len(raw) != artifact["byte_size"] or len(raw) < 2_000_000:
            raise RuntimeError("image size verification failed")
        if extension != ".jpg" or not jpeg_signature:
            raise RuntimeError("JPG extension/signature verification failed")
        if len(completed) != 1 or staging or temporary:
            raise RuntimeError("artifact cardinality or cleanup verification failed")
        save(
            ROOT / "run_result.json",
            {
                "verdict": "PASS",
                "website": "Pexels",
                "source_page": SOURCE_PAGE,
                "photo_description": DESCRIPTION,
                "download_method": "visible free JPG link, Alt+Enter download intent",
                "filename": final.name,
                "extension": extension,
                "byte_size": len(raw),
                "mime_type": artifact["mime_type"],
                "mime_source": artifact["mime_source"],
                "content_signature": "JPEG FF D8 FF",
                "receipt_sha256": artifact["checksum"],
                "independent_sha256": independent,
                "artifact_location": str(final),
                "portable_artifact_location": artifact["relative_path"],
                "completed_image_count": len(completed),
                "staging_file_count": len(staging),
                "temporary_file_count": len(temporary),
                "browser": backend.browser_environment(),
            },
        )
        status = "completed"
        return 0
    except Exception as exc:
        save(
            ROOT / "run_result.json",
            {
                "verdict": "FAIL", "website": "Pexels",
                "source_page": SOURCE_PAGE,
                "error": f"{type(exc).__name__}: {exc}",
            },
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
