"""Bridge endpoint: auth, validation, and CORS behaviour."""

from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm.bridge import Bridge

EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnop"


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.queued = []
        self.bridge = Bridge(lambda url, name: self.queued.append((url, name)), port=0)
        self.bridge.start()
        self.base = self.bridge.endpoint

    def tearDown(self):
        self.bridge.stop()

    def post(self, payload, token=None, origin=EXTENSION_ORIGIN, path="/add"):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("X-ODM-Token", token)
        if origin:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read()), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), dict(e.headers)

    # auth -------------------------------------------------------------

    def test_valid_token_queues_download(self):
        status, body, _ = self.post({"url": "https://x.test/a.zip"}, token=self.bridge.token)
        self.assertEqual(status, 200)
        self.assertTrue(body["queued"])
        self.assertEqual(self.queued, [("https://x.test/a.zip", None)])

    def test_missing_token_is_rejected(self):
        status, _, _ = self.post({"url": "https://x.test/a.zip"})
        self.assertEqual(status, 403)
        self.assertEqual(self.queued, [])

    def test_wrong_token_is_rejected(self):
        status, _, _ = self.post({"url": "https://x.test/a.zip"}, token="not-the-token")
        self.assertEqual(status, 403)
        self.assertEqual(self.queued, [])

    # validation -------------------------------------------------------

    def test_filename_is_passed_through(self):
        self.post(
            {"url": "https://x.test/a.zip", "filename": "custom.zip"}, token=self.bridge.token
        )
        self.assertEqual(self.queued, [("https://x.test/a.zip", "custom.zip")])

    def test_non_http_scheme_rejected(self):
        for bad in ("file:///C:/windows/system32/x.dll", "javascript:alert(1)", "ftp://x/y"):
            status, _, _ = self.post({"url": bad}, token=self.bridge.token)
            self.assertEqual(status, 400, bad)
        self.assertEqual(self.queued, [])

    def test_empty_url_rejected(self):
        status, _, _ = self.post({"url": ""}, token=self.bridge.token)
        self.assertEqual(status, 400)

    def test_unknown_route_is_404(self):
        status, _, _ = self.post({"url": "https://x.test/a.zip"},
                                 token=self.bridge.token, path="/wat")
        self.assertEqual(status, 404)

    # cors -------------------------------------------------------------

    def test_extension_origin_gets_cors_header(self):
        _, _, headers = self.post({"url": "https://x.test/a.zip"}, token=self.bridge.token)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), EXTENSION_ORIGIN)

    def test_web_page_origin_gets_no_cors_header(self):
        _, _, headers = self.post(
            {"url": "https://x.test/a.zip"}, token=self.bridge.token,
            origin="https://evil.example",
        )
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    # liveness ---------------------------------------------------------

    def test_ping_needs_no_token(self):
        with urllib.request.urlopen(self.base + "/ping", timeout=5) as r:
            body = json.loads(r.read())
        self.assertEqual(body["app"], "ODM")

    def test_binds_loopback_only(self):
        self.assertTrue(self.bridge.endpoint.startswith("http://127.0.0.1:"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
