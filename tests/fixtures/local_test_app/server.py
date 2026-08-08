from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(FIXTURE_DIR), **kwargs)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/popup-redirect"):
            self.send_response(302)
            self.send_header("Location", "/popup_target.html?redirected")
            self.end_headers()
            return
        if self.path.startswith("/api/signal"):
            body = b'{"ok":true,"signal":"local"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path.startswith("/api/checkout"):
            body = b'{"ok":true,"checkout":"local"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A003
        return


def start_fixture_server() -> tuple[ThreadingHTTPServer, str]:
    # Bind all interfaces so localhost and 127.0.0.1 both reach fixtures
    # (needed for controlled cross-origin iframe tests).
    server = ThreadingHTTPServer(("0.0.0.0", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _host, port = server.server_address[:2]
    base = f"http://127.0.0.1:{port}/index.html"
    return server, base
