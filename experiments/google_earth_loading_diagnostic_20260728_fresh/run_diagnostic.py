"""One-shot Google Earth loading diagnostic; never a benchmark receipt."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
)

ROOT = Path(__file__).resolve().parent
SCREENSHOTS = ROOT / "screenshots"
SNAPSHOTS = ROOT / "dom_snapshots"
LOGS = ROOT / "logs"
for directory in (SCREENSHOTS, SNAPSHOTS, LOGS):
    directory.mkdir(parents=True, exist_ok=False)

URL = "https://earth.google.com/web/"
TIMEOUT_SECONDS = 60
INTERVAL_SECONDS = 5
CONFIG = BrowserConfig(
    provider=BrowserProvider.PLAYWRIGHT,
    engine=BrowserEngine.CHROMIUM,
    channel=BrowserChannel.BUNDLED,
    headless=False,
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    backend = PlaywrightBackend(CONFIG)
    console: list[dict] = []
    page_errors: list[dict] = []
    failed_requests: list[dict] = []
    error_responses: list[dict] = []
    timeline: list[dict] = []
    started_unix_ms = int(time.time() * 1000)
    started_monotonic = time.monotonic()
    result: dict[str, object] = {
        "diagnostic_kind": "experiment_only_playwright_instrumentation",
        "url": URL,
        "timeout_seconds": TIMEOUT_SECONDS,
        "interval_seconds": INTERVAL_SECONDS,
        "started_unix_ms": started_unix_ms,
    }
    try:
        backend.start()
        page = backend.page
        context = page.context

        def on_console(message) -> None:
            console.append({
                "elapsed_ms": round((time.monotonic() - started_monotonic) * 1000),
                "type": message.type,
                "text": message.text,
                "location": message.location,
            })

        def on_page_error(error) -> None:
            page_errors.append({
                "elapsed_ms": round((time.monotonic() - started_monotonic) * 1000),
                "name": getattr(error, "name", type(error).__name__),
                "message": str(error),
                "stack": getattr(error, "stack", None),
            })

        def on_request_failed(request) -> None:
            failed_requests.append({
                "elapsed_ms": round((time.monotonic() - started_monotonic) * 1000),
                "url": request.url,
                "method": request.method,
                "resource_type": request.resource_type,
                "failure": request.failure,
            })

        def on_response(response) -> None:
            if response.status >= 400:
                error_responses.append({
                    "elapsed_ms": round(
                        (time.monotonic() - started_monotonic) * 1000
                    ),
                    "url": response.url,
                    "status": response.status,
                    "status_text": response.status_text,
                    "resource_type": response.request.resource_type,
                })

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("requestfailed", on_request_failed)
        page.on("response", on_response)

        cdp_error = None
        gpu_info = None
        try:
            browser_cdp = backend._browser.new_browser_cdp_session()  # type: ignore[union-attr]
            gpu_info = browser_cdp.send("SystemInfo.getInfo")
            browser_cdp.detach()
        except Exception as exc:
            cdp_error = f"{type(exc).__name__}: {exc}"

        navigation_started = time.monotonic()
        navigation_error = None
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            navigation_error = f"{type(exc).__name__}: {exc}"
        navigation_elapsed_ms = round((time.monotonic() - navigation_started) * 1000)

        feature_support = page.evaluate(
            """() => {
              const canvas = document.createElement('canvas');
              const gl2 = canvas.getContext('webgl2');
              const gl = gl2 || canvas.getContext('webgl') ||
                canvas.getContext('experimental-webgl');
              let webgl = {
                available: !!gl,
                webgl2: !!gl2,
                vendor: null,
                renderer: null,
                unmaskedVendor: null,
                unmaskedRenderer: null,
                version: null,
                shadingLanguageVersion: null,
                maxTextureSize: null,
                contextAttributes: null,
              };
              if (gl) {
                const debug = gl.getExtension('WEBGL_debug_renderer_info');
                webgl.vendor = gl.getParameter(gl.VENDOR);
                webgl.renderer = gl.getParameter(gl.RENDERER);
                webgl.version = gl.getParameter(gl.VERSION);
                webgl.shadingLanguageVersion =
                  gl.getParameter(gl.SHADING_LANGUAGE_VERSION);
                webgl.maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
                webgl.contextAttributes = gl.getContextAttributes();
                if (debug) {
                  webgl.unmaskedVendor =
                    gl.getParameter(debug.UNMASKED_VENDOR_WEBGL);
                  webgl.unmaskedRenderer =
                    gl.getParameter(debug.UNMASKED_RENDERER_WEBGL);
                }
              }
              return {
                userAgent: navigator.userAgent,
                platform: navigator.platform,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory ?? null,
                crossOriginIsolated: self.crossOriginIsolated,
                secureContext: self.isSecureContext,
                webAssembly: typeof WebAssembly !== 'undefined',
                sharedArrayBuffer: typeof SharedArrayBuffer !== 'undefined',
                offscreenCanvas: typeof OffscreenCanvas !== 'undefined',
                webGPU: !!navigator.gpu,
                webGL: webgl,
              };
            }"""
        )

        for sample_index in range(1, TIMEOUT_SECONDS // INTERVAL_SECONDS + 1):
            target = started_monotonic + sample_index * INTERVAL_SECONDS
            remaining_ms = max(0, round((target - time.monotonic()) * 1000))
            if remaining_ms:
                page.wait_for_timeout(remaining_ms)
            elapsed_ms = round((time.monotonic() - started_monotonic) * 1000)
            html = page.content()
            html_path = SNAPSHOTS / f"{sample_index:02d}_{elapsed_ms:06d}ms.html"
            html_path.write_text(html, encoding="utf-8")
            screenshot_path = (
                SCREENSHOTS / f"{sample_index:02d}_{elapsed_ms:06d}ms.png"
            )
            page.screenshot(path=str(screenshot_path), full_page=False)
            state = page.evaluate(
                """() => {
                  const all = document.querySelectorAll('*');
                  const visibleLabels = Array.from(
                    document.querySelectorAll('[aria-label]')
                  ).filter((el) => {
                    const s = getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.visibility !== 'hidden' && s.display !== 'none' &&
                      r.width > 0 && r.height > 0;
                  }).slice(0, 100).map((el) => ({
                    tag: el.tagName.toLowerCase(),
                    ariaLabel: el.getAttribute('aria-label'),
                  }));
                  const resources = performance.getEntriesByType('resource');
                  const navigation = performance.getEntriesByType('navigation')[0];
                  return {
                    url: location.href,
                    title: document.title,
                    readyState: document.readyState,
                    nodeCount: all.length,
                    bodyChildCount: document.body?.children.length ?? null,
                    bodyTextLength: document.body?.innerText.length ?? null,
                    htmlLength: document.documentElement?.outerHTML.length ?? null,
                    canvasCount: document.querySelectorAll('canvas').length,
                    iframeCount: document.querySelectorAll('iframe').length,
                    visibleAriaLabels: visibleLabels,
                    resourceCount: resources.length,
                    resourceDurationMax: resources.length
                      ? Math.max(...resources.map((r) => r.duration || 0))
                      : 0,
                    navigationTiming: navigation ? {
                      duration: navigation.duration,
                      domInteractive: navigation.domInteractive,
                      domContentLoadedEventEnd:
                        navigation.domContentLoadedEventEnd,
                      loadEventEnd: navigation.loadEventEnd,
                      responseEnd: navigation.responseEnd,
                    } : null,
                  };
                }"""
            )
            timeline.append({
                "sample": sample_index,
                "elapsed_ms": elapsed_ms,
                "html_sha256": hashlib.sha256(
                    html.encode("utf-8")
                ).hexdigest(),
                "dom_snapshot": str(html_path),
                "screenshot": str(screenshot_path),
                **state,
            })

        final_html = page.content()
        final_dom = ROOT / "final_dom_snapshot.html"
        final_dom.write_text(final_html, encoding="utf-8")
        performance = page.evaluate(
            """() => ({
              timeOrigin: performance.timeOrigin,
              now: performance.now(),
              navigation: performance.getEntriesByType('navigation'),
              resourceSummary: performance.getEntriesByType('resource').map(
                (r) => ({
                  name: r.name,
                  initiatorType: r.initiatorType,
                  duration: r.duration,
                  transferSize: r.transferSize,
                  encodedBodySize: r.encodedBodySize,
                  decodedBodySize: r.decodedBodySize,
                })
              ),
            })"""
        )
        result.update({
            "browser": backend.browser_environment(),
            "navigation_error": navigation_error,
            "navigation_elapsed_ms": navigation_elapsed_ms,
            "gpu_info": gpu_info,
            "gpu_info_error": cdp_error,
            "feature_support": feature_support,
            "console_message_count": len(console),
            "javascript_error_count": len(page_errors),
            "failed_request_count": len(failed_requests),
            "http_error_response_count": len(error_responses),
            "timeline_sample_count": len(timeline),
            "final_dom_snapshot": str(final_dom),
        })
        write_json(LOGS / "console.json", console)
        write_json(LOGS / "javascript_errors.json", page_errors)
        write_json(LOGS / "failed_requests.json", failed_requests)
        write_json(LOGS / "http_error_responses.json", error_responses)
        write_json(LOGS / "timeline.json", timeline)
        write_json(LOGS / "performance.json", performance)
        write_json(ROOT / "diagnostic_result.json", result)
        return 0
    except Exception as exc:
        result["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
        write_json(ROOT / "diagnostic_result.json", result)
        return 1
    finally:
        before = backend.browser_environment()
        backend.stop()
        after = backend.browser_environment()
        write_json(ROOT / "terminal_browser.json", {
            "before_stop": before,
            "after_stop": after,
        })


if __name__ == "__main__":
    raise SystemExit(main())
