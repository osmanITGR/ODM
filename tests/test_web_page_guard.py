"""Refusing to download a web page as if it were a file.

Pointing ODM at a video page it cannot extract used to save the HTML itself:
a few hundred KB of markup under the video's name, which looks exactly like a
corrupt download. These cover the guard that stops it.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm.engine import NotAFileError, probe


class ConfigurableHandler(http.server.BaseHTTPRequestHandler):
    """Serves whatever content type a test asks for."""

    content_type = "application/octet-stream"
    disposition: str | None = None
    body = b"x" * 512

    def log_message(self, *args):
        pass

    def _respond(self, include_body: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", type(self).content_type)
        if type(self).disposition:
            self.send_header("Content-Disposition", type(self).disposition)
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        if include_body:
            self.wfile.write(type(self).body)

    def do_GET(self):
        self._respond(include_body=True)

    def do_HEAD(self):
        self._respond(include_body=False)


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TestWebPageGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadedServer(("127.0.0.1", 0), ConfigurableHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        ConfigurableHandler.content_type = "application/octet-stream"
        ConfigurableHandler.disposition = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/thing"

    def test_refuses_html(self):
        ConfigurableHandler.content_type = "text/html; charset=utf-8"
        with self.assertRaises(NotAFileError):
            probe(self.url)

    def test_refuses_xhtml(self):
        ConfigurableHandler.content_type = "application/xhtml+xml"
        with self.assertRaises(NotAFileError):
            probe(self.url)

    def test_allows_html_sent_as_an_attachment(self):
        # Someone genuinely saving an .html file must not be blocked.
        ConfigurableHandler.content_type = "text/html"
        ConfigurableHandler.disposition = 'attachment; filename="saved.html"'
        self.assertEqual(probe(self.url).filename, "saved.html")

    def test_allows_a_media_type(self):
        ConfigurableHandler.content_type = "video/mp4"
        self.assertEqual(probe(self.url).filename, "thing")

    def test_allows_an_unknown_type(self):
        # Many file servers send octet-stream; that must still work.
        ConfigurableHandler.content_type = "application/octet-stream"
        self.assertEqual(probe(self.url).filename, "thing")

    def test_message_says_what_to_do_instead(self):
        message = str(NotAFileError())
        self.assertIn("web page", message)
        self.assertIn("video page", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
