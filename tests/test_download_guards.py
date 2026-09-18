"""Guards on what a download is allowed to fetch and where it may write.

Two things a download manager must refuse:

- Saving a web page as if it were a file. Pointing ODM at a video page it
  cannot extract used to save the HTML itself — a few hundred KB of markup
  under the video's name, which looks exactly like a corrupt download.
- Writing outside the destination folder, when a filename supplied over the
  browser bridge or the CLI contains a path.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm.engine import Download, NotAFileError, probe


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


class TestTargetStaysInsideDestination(unittest.TestCase):
    """A supplied filename must not write outside the download folder.

    Names read from a server are stripped when they are parsed, but one given
    explicitly — over the browser bridge, or with the CLI's -f — reaches the
    path untouched.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dest = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def target_for(self, name: str) -> Path:
        return Download("https://example.com/x", self.dest, filename=name).target.resolve()

    def assert_inside(self, name: str) -> Path:
        target = self.target_for(name)
        self.assertEqual(target.parent, self.dest, f"{name!r} escaped to {target}")
        return target

    def test_relative_traversal_is_flattened(self):
        self.assertEqual(self.assert_inside("../../../evil.exe").name, "evil.exe")

    def test_absolute_path_is_flattened(self):
        self.assertEqual(self.assert_inside("C:/Windows/evil.dll").name, "evil.dll")

    def test_subdirectory_is_flattened(self):
        self.assertEqual(self.assert_inside("sub/dir/file.zip").name, "file.zip")

    def test_dot_names_fall_back(self):
        self.assertEqual(self.assert_inside("..").name, "download")
        self.assertEqual(self.assert_inside(".").name, "download")

    def test_ordinary_name_is_untouched(self):
        self.assertEqual(self.assert_inside("clip.mp4").name, "clip.mp4")

    def test_part_and_meta_files_are_inside_too(self):
        download = Download("https://example.com/x", self.dest, filename="../../evil")
        self.assertEqual(download.part_file.resolve().parent, self.dest)
        self.assertEqual(download.meta_file.resolve().parent, self.dest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
