"""One-shot generator: record a ~3s silent WebM via Playwright Chromium."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "medium.webm"

HTML = """
<!doctype html>
<html><body>
<canvas id="c" width="64" height="64"></canvas>
<script>
async function record() {
  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d');
  const stream = canvas.captureStream(10);
  const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8' });
  const chunks = [];
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  const done = new Promise((resolve) => { rec.onstop = resolve; });
  rec.start();
  const start = performance.now();
  function frame(t) {
    ctx.fillStyle = '#222';
    ctx.fillRect(0, 0, 64, 64);
    ctx.fillStyle = '#8cf';
    ctx.fillRect(0, 0, ((t / 3000) * 64) | 0, 64);
    if (performance.now() - start < 3000) {
      requestAnimationFrame(frame);
    } else {
      rec.stop();
    }
  }
  requestAnimationFrame(frame);
  await done;
  const blob = new Blob(chunks, { type: 'video/webm' });
  const buf = await blob.arrayBuffer();
  const bytes = Array.from(new Uint8Array(buf));
  window.__bytes = bytes;
}
window.__ready = record();
</script>
</body></html>
"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(HTML)
        page.wait_for_function("() => window.__bytes && window.__bytes.length > 0", timeout=15_000)
        data = page.evaluate("() => window.__bytes")
        OUT.write_bytes(bytes(data))
        browser.close()
    print("wrote", OUT, "bytes", OUT.stat().st_size)


if __name__ == "__main__":
    main()
