"""Local HTTP bridge so a browser extension can hand downloads to ODM.

Binds to 127.0.0.1 only. Every request must carry the token that the running
app generated, so other local software cannot queue downloads silently.
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DEFAULT_PORT = 47653
# Only these origins may call the bridge; browsers enforce this via CORS.
ALLOWED_ORIGIN_SCHEMES = ("chrome-extension://", "moz-extension://")


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "ODM-Bridge/1.0"
    bridge = None  # set by Bridge.start

    def log_message(self, *args):
        pass

    # helpers ----------------------------------------------------------

    def _origin_allowed(self) -> str | None:
        origin = self.headers.get("Origin", "")
        if origin.startswith(ALLOWED_ORIGIN_SCHEMES):
            return origin
        return None

    def _cors(self, origin: str | None) -> None:
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-ODM-Token")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def _reply(self, code: int, payload: dict, origin: str | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors(origin)
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        supplied = self.headers.get("X-ODM-Token", "")
        return hmac.compare_digest(supplied, self.bridge.token)

    # verbs ------------------------------------------------------------

    def do_OPTIONS(self):
        origin = self._origin_allowed()
        self.send_response(204)
        self._cors(origin)
        self.end_headers()

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/ping":
            # Unauthenticated liveness probe so the extension can show status.
            self._reply(200, {"app": "ODM", "version": "1.0.0"}, self._origin_allowed())
            return
        self._reply(404, {"error": "not found"}, self._origin_allowed())

    def do_POST(self):
        origin = self._origin_allowed()
        route = urlparse(self.path).path

        if route != "/add":
            self._reply(404, {"error": "not found"}, origin)
            return

        if not self._authorised():
            self._reply(403, {"error": "bad token"}, origin)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64 * 1024:
                raise ValueError("bad length")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._reply(400, {"error": "bad request"}, origin)
            return

        url = (payload.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            self._reply(400, {"error": "unsupported url"}, origin)
            return

        filename = payload.get("filename") or None
        try:
            self.bridge.on_download(url, filename)
        except Exception as exc:
            self._reply(500, {"error": str(exc)[:200]}, origin)
            return

        self._reply(200, {"queued": True}, origin)


class Bridge:
    """Runs the local endpoint the browser extension talks to."""

    def __init__(self, on_download, port: int = DEFAULT_PORT, token: str | None = None):
        self.on_download = on_download
        self.port = port
        self.token = token or secrets.token_urlsafe(24)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        if self._server:
            return
        handler = type("BoundHandler", (BridgeHandler,), {"bridge": self})
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._server:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
