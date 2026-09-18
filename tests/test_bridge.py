"""Bridge endpoint: auth, validation, and CORS behaviour."""

from __future__ import annotations

import json
import os
import socket
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm.bridge import Bridge, load_or_create_token, token_file

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


class TestTokenPersistence(unittest.TestCase):
    """The pairing token has to survive a restart.

    Generating a fresh one each launch meant the extension had to be paired
    again every time ODM was reopened, which looks like the pairing being
    broken rather than working as designed.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        # token_file() reads the environment, so point it at a scratch dir.
        self._saved = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp.name

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._saved
        self.tmp.cleanup()

    def test_the_same_token_comes_back_next_launch(self):
        first = load_or_create_token()
        self.assertEqual(load_or_create_token(), first)

    def test_separate_bridges_share_the_saved_token(self):
        a = Bridge(lambda url, name: None)
        b = Bridge(lambda url, name: None)
        self.assertEqual(a.token, b.token)

    def test_the_token_is_long_enough_to_resist_guessing(self):
        self.assertGreaterEqual(len(load_or_create_token()), 24)

    def test_a_truncated_file_is_replaced_rather_than_trusted(self):
        path = token_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("short", encoding="utf-8")

        token = load_or_create_token()
        self.assertGreaterEqual(len(token), 24)
        self.assertNotEqual(token, "short")

    def test_regenerating_invalidates_the_old_token(self):
        bridge = Bridge(lambda url, name: None)
        old = bridge.token
        new = bridge.regenerate_token()

        self.assertNotEqual(old, new)
        # The new one is what a later launch picks up.
        self.assertEqual(load_or_create_token(), new)

    def test_an_unwritable_location_still_yields_a_token(self):
        # Losing persistence only costs re-pairing; the bridge must still run.
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "file-not-dir")
        Path(os.environ["LOCALAPPDATA"]).write_text("blocks the mkdir")

        self.assertGreaterEqual(len(load_or_create_token()), 24)


class TestPortIsExclusive(unittest.TestCase):
    def test_start_fails_when_the_port_is_taken(self):
        """The extension has the port compiled in.

        Windows lets a second process bind the same port and quietly take the
        requests, so a bridge that "started" would never be reached. Failing
        here is what lets the GUI say so.
        """
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]

        bridge = Bridge(lambda url, name: None, port=port)
        try:
            with self.assertRaises(OSError):
                bridge.start()
            self.assertFalse(bridge.running)
        finally:
            bridge.stop()
            blocker.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
