"""Engine tests against a local HTTP server, so they need no internet."""

from __future__ import annotations

import hashlib
import http.server
import os
import socketserver
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm.clipboard import extract_urls, looks_downloadable
from odm.engine import (
    CHUNK,
    Download,
    RateLimiter,
    Segment,
    State,
    plan_segments,
    probe,
)
from odm.manager import Manager

PAYLOAD = bytes((i * 7 + 13) % 256 for i in range(3_000_000))
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


class Handler(http.server.BaseHTTPRequestHandler):
    allow_ranges = True
    serve_length = True

    def log_message(self, *args):
        pass

    def _body_for(self):
        rng = self.headers.get("Range")
        if self.allow_ranges and rng and rng.startswith("bytes="):
            spec = rng[6:]
            start_s, _, end_s = spec.partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else len(PAYLOAD) - 1
            end = min(end, len(PAYLOAD) - 1)
            if start > end or start >= len(PAYLOAD):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(PAYLOAD)}")
                self.end_headers()
                return None
            chunk = PAYLOAD[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Disposition", 'attachment; filename="sample.bin"')
            self.end_headers()
            return chunk

        self.send_response(200)
        if self.serve_length:
            self.send_header("Content-Length", str(len(PAYLOAD)))
        self.send_header("Content-Disposition", 'attachment; filename="sample.bin"')
        self.end_headers()
        return PAYLOAD

    def do_GET(self):
        body = self._body_for()
        if body is not None:
            self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        if self.serve_length:
            self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class ServerMixin:
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadedServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.port}/sample.bin"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.allow_ranges = True
        Handler.serve_length = True
        self.tmp = TemporaryDirectory()
        self.dest = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def sha(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                h.update(c)
        return h.hexdigest()


class TestProbe(ServerMixin, unittest.TestCase):
    def test_detects_size_and_resumability(self):
        info = probe(self.url)
        self.assertEqual(info.size, len(PAYLOAD))
        self.assertTrue(info.resumable)
        self.assertEqual(info.filename, "sample.bin")

    def test_non_resumable_server(self):
        Handler.allow_ranges = False
        info = probe(self.url)
        self.assertFalse(info.resumable)


class TestSegmentPlanning(unittest.TestCase):
    def test_covers_whole_range_without_gaps(self):
        segs = plan_segments(1000, 4, min_chunk=1)
        self.assertEqual(segs[0].start, 0)
        self.assertEqual(segs[-1].end, 999)
        self.assertEqual(sum(s.total for s in segs), 1000)
        for a, b in zip(segs, segs[1:]):
            self.assertEqual(b.start, a.end + 1)

    def test_uneven_split(self):
        segs = plan_segments(1003, 4, min_chunk=1)
        self.assertEqual(sum(s.total for s in segs), 1003)

    def test_small_file_gets_one_segment(self):
        segs = plan_segments(500, 8, min_chunk=1024 * 1024)
        self.assertEqual(len(segs), 1)


class TestSegmentedDownload(ServerMixin, unittest.TestCase):
    def test_multi_connection_is_byte_exact(self):
        d = Download(self.url, self.dest, connections=8)
        d.start()
        self.assertIs(d.progress.state, State.DONE)
        self.assertEqual(d.target.name, "sample.bin")
        self.assertEqual(self.sha(d.target), PAYLOAD_SHA)
        self.assertGreater(len(d.segments), 1)

    def test_single_connection_is_byte_exact(self):
        d = Download(self.url, self.dest, connections=1)
        d.start()
        self.assertIs(d.progress.state, State.DONE)
        self.assertEqual(self.sha(d.target), PAYLOAD_SHA)

    def test_fallback_when_server_refuses_ranges(self):
        Handler.allow_ranges = False
        d = Download(self.url, self.dest, connections=8)
        d.start()
        self.assertIs(d.progress.state, State.DONE)
        self.assertEqual(self.sha(d.target), PAYLOAD_SHA)
        self.assertEqual(d.segments, [])

    def test_unknown_length_still_downloads(self):
        Handler.allow_ranges = False
        Handler.serve_length = False
        d = Download(self.url, self.dest, connections=4)
        d.start()
        self.assertIs(d.progress.state, State.DONE)
        self.assertEqual(self.sha(d.target), PAYLOAD_SHA)

    def test_progress_reaches_total(self):
        d = Download(self.url, self.dest, connections=4)
        d.start()
        self.assertEqual(d.progress.downloaded, len(PAYLOAD))
        self.assertAlmostEqual(d.progress.percent, 100.0, places=3)

    def test_temp_files_removed_on_success(self):
        d = Download(self.url, self.dest, connections=4)
        d.start()
        self.assertFalse(d.part_file.exists())
        self.assertFalse(d.meta_file.exists())

    def test_custom_filename_is_honoured(self):
        d = Download(self.url, self.dest, connections=4, filename="renamed.dat")
        d.start()
        self.assertEqual(d.target.name, "renamed.dat")
        self.assertEqual(self.sha(d.target), PAYLOAD_SHA)


class TestWorkStealing(ServerMixin, unittest.TestCase):
    def test_boost_keeps_the_file_byte_exact(self):
        d = Download(self.url, self.dest, connections=8, boost=True)
        d.start()
        self.assertIs(d.progress.state, State.DONE)
        self.assertEqual(self.sha(d.target), PAYLOAD_SHA)

    def test_segments_stay_contiguous_after_splitting(self):
        # Sized so each segment is comfortably above MIN_SPLIT.
        total = 64 * 1024 * 1024
        d = Download(self.url, self.dest, connections=4, boost=True)
        d.segments = plan_segments(total, 4)
        original = len(d.segments)

        stolen = d._steal_work()
        self.assertIsNotNone(stolen)
        self.assertEqual(len(d.segments), original + 1)

        ordered = sorted(d.segments, key=lambda s: s.start)
        self.assertEqual(ordered[0].start, 0)
        self.assertEqual(ordered[-1].end, total - 1)
        for a, b in zip(ordered, ordered[1:]):
            self.assertEqual(b.start, a.end + 1, "split left a gap or an overlap")
        self.assertEqual(sum(s.total for s in d.segments), total)

    def test_repeated_splits_stay_consistent(self):
        total = 64 * 1024 * 1024
        d = Download(self.url, self.dest, connections=4, boost=True)
        d.segments = plan_segments(total, 4)
        for _ in range(10):
            d._steal_work()
        ordered = sorted(d.segments, key=lambda s: s.start)
        for a, b in zip(ordered, ordered[1:]):
            self.assertEqual(b.start, a.end + 1)
        self.assertEqual(sum(s.total for s in d.segments), total)

    def test_no_split_below_the_minimum(self):
        d = Download(self.url, self.dest, connections=2, boost=True)
        d.segments = [Segment(0, 0, 1024)]
        self.assertIsNone(d._steal_work())

    def test_disabled_boost_never_splits(self):
        d = Download(self.url, self.dest, connections=4, boost=False)
        d.segments = plan_segments(64 * 1024 * 1024, 4)
        self.assertIsNone(d._steal_work())
        self.assertEqual(len(d.segments), 4)

    def test_completed_segments_are_not_stolen_from(self):
        d = Download(self.url, self.dest, connections=2, boost=True)
        seg = Segment(0, 0, 10_000_000)
        seg.done = seg.total
        d.segments = [seg]
        self.assertIsNone(d._steal_work())


class TestResume(ServerMixin, unittest.TestCase):
    def test_pause_writes_resumable_state(self):
        d = Download(self.url, self.dest, connections=4)
        t = threading.Thread(target=d.start, daemon=True)
        t.start()
        while d.progress.total is None or d.progress.downloaded < 300_000:
            pass
        d.pause()
        t.join(timeout=15)
        self.assertTrue(d.meta_file.exists())
        self.assertTrue(d.part_file.exists())
        self.assertGreater(d.progress.downloaded, 0)

    def test_fresh_object_resumes_and_completes(self):
        first = Download(self.url, self.dest, connections=4)
        t = threading.Thread(target=first.start, daemon=True)
        t.start()
        while first.progress.total is None or first.progress.downloaded < 300_000:
            pass
        first.pause()
        t.join(timeout=15)
        paused_at = first.progress.downloaded

        second = Download(self.url, self.dest, connections=4)
        self.assertTrue(second._load_meta())
        self.assertEqual(second.progress.downloaded, paused_at)

        second.start()
        self.assertIs(second.progress.state, State.DONE)
        self.assertEqual(self.sha(second.target), PAYLOAD_SHA)

    def test_stale_meta_without_part_is_ignored(self):
        d = Download(self.url, self.dest, connections=4)
        d.info = probe(self.url)
        d.segments = plan_segments(len(PAYLOAD), 4)
        d._save_meta()
        fresh = Download(self.url, self.dest, connections=4)
        self.assertFalse(fresh._load_meta())


class TestManager(ServerMixin, unittest.TestCase):
    def test_runs_queue_to_completion(self):
        m = Manager(self.dest, connections=4, concurrent=2)
        tasks = [m.add(f"{self.url}?n={i}", filename=f"f{i}.bin") for i in range(4)]
        deadline = 120
        waited = 0.0
        while any(t.state not in (State.DONE, State.ERROR) for t in tasks) and waited < deadline:
            m.pump()
            threading.Event().wait(0.1)
            waited += 0.1
        for t in tasks:
            self.assertIs(t.state, State.DONE, f"{t.name}: {t.download.progress.error}")
            self.assertEqual(self.sha(t.download.target), PAYLOAD_SHA)

    def test_respects_concurrency_limit(self):
        m = Manager(self.dest, connections=2, concurrent=2)
        for i in range(5):
            m.add(f"{self.url}?c={i}", filename=f"c{i}.bin", autostart=False)
        m.pump()
        self.assertLessEqual(m.active_count, 2)

    def test_pump_does_not_restart_a_user_paused_task(self):
        m = Manager(self.dest, connections=4, concurrent=2)
        task = m.add(self.url, filename="held.bin")
        while task.download.progress.total is None or task.download.progress.downloaded < 200_000:
            pass
        m.pause(task.id)
        if task.thread:
            task.thread.join(timeout=15)
        self.assertTrue(task.held)
        for _ in range(5):
            m.pump()
            threading.Event().wait(0.1)
        self.assertIs(task.state, State.PAUSED)

    def test_resume_clears_the_hold(self):
        m = Manager(self.dest, connections=4, concurrent=2)
        task = m.add(self.url, filename="held2.bin")
        while task.download.progress.total is None or task.download.progress.downloaded < 200_000:
            pass
        m.pause(task.id)
        if task.thread:
            task.thread.join(timeout=15)
        m.resume(task.id)
        self.assertFalse(task.held)
        waited = 0.0
        while task.state not in (State.DONE, State.ERROR) and waited < 60:
            m.pump()
            threading.Event().wait(0.1)
            waited += 0.1
        self.assertIs(task.state, State.DONE)
        self.assertEqual(self.sha(task.download.target), PAYLOAD_SHA)

    def test_remove_drops_task(self):
        m = Manager(self.dest, connections=2, concurrent=1)
        task = m.add(self.url, filename="x.bin", autostart=False)
        m.remove(task.id)
        self.assertIsNone(m.get(task.id))


class TestRateLimiter(unittest.TestCase):
    def test_zero_rate_never_blocks(self):
        limiter = RateLimiter(0.0)
        start = time.monotonic()
        for _ in range(50):
            limiter.take(1 << 20)
        self.assertLess(time.monotonic() - start, 0.2)

    def test_limits_throughput(self):
        rate = 200_000.0
        limiter = RateLimiter(rate)
        limiter.take(int(rate))  # drain the initial bucket
        start = time.monotonic()
        moved = 0
        while moved < 100_000:
            limiter.take(10_000)
            moved += 10_000
        elapsed = time.monotonic() - start
        # 100 KB at 200 KB/s should take ~0.5s; allow generous slack.
        self.assertGreater(elapsed, 0.25)

    def test_set_rate_lifts_the_cap(self):
        limiter = RateLimiter(1000.0)
        limiter.set_rate(0.0)
        start = time.monotonic()
        limiter.take(10_000_000)
        self.assertLess(time.monotonic() - start, 0.2)

    def test_read_larger_than_the_rate_completes(self):
        """A chunk bigger than one second's worth must not wedge.

        The bucket caps at the rate, so `take` could never reach a larger
        amount and span forever. Every worker asks for CHUNK (256 KB), so any
        cap below that froze the whole download.
        """
        limiter = RateLimiter(1024.0)  # 1 KB/s
        done = threading.Event()
        threading.Thread(
            target=lambda: (limiter.take(CHUNK), done.set()), daemon=True
        ).start()
        self.assertTrue(
            done.wait(timeout=5.0),
            "take() never returned for a read larger than the rate",
        )

    def test_an_oversized_read_is_paid_back(self):
        """The debt from an oversized read still holds the average down."""
        limiter = RateLimiter(1024.0)
        limiter.take(4096)  # four seconds of debt
        start = time.monotonic()
        limiter.take(256)
        self.assertGreater(time.monotonic() - start, 0.2)


class TestLimitedDownload(ServerMixin, unittest.TestCase):
    def test_capped_download_is_slower_but_correct(self):
        limiter = RateLimiter(400_000.0)
        d = Download(self.url, self.dest, connections=4, limiter=limiter)
        start = time.monotonic()
        d.start()
        elapsed = time.monotonic() - start
        self.assertIs(d.progress.state, State.DONE)
        self.assertEqual(self.sha(d.target), PAYLOAD_SHA)
        # 3 MB at 400 KB/s cannot finish in under a second.
        self.assertGreater(elapsed, 1.0)

    def test_manager_shares_one_budget(self):
        m = Manager(self.dest, connections=2, concurrent=2, speed_limit=500_000.0)
        self.assertEqual(m.speed_limit, 500_000.0)
        t1 = m.add(f"{self.url}?a=1", filename="a.bin")
        t2 = m.add(f"{self.url}?a=2", filename="b.bin")
        self.assertIs(t1.download.limiter, m.limiter)
        self.assertIs(t2.download.limiter, m.limiter)
        m.speed_limit = 0.0
        waited = 0.0
        while any(t.state not in (State.DONE, State.ERROR) for t in (t1, t2)) and waited < 90:
            m.pump()
            threading.Event().wait(0.1)
            waited += 0.1
        for t in (t1, t2):
            self.assertIs(t.state, State.DONE)
            self.assertEqual(self.sha(t.download.target), PAYLOAD_SHA)


class TestClipboard(unittest.TestCase):
    def test_extracts_multiple_urls(self):
        text = "get https://a.com/f.zip and http://b.org/g.pdf now"
        self.assertEqual(extract_urls(text), ["https://a.com/f.zip", "http://b.org/g.pdf"])

    def test_strips_trailing_punctuation(self):
        self.assertEqual(extract_urls("see https://a.com/f.zip."), ["https://a.com/f.zip"])

    def test_deduplicates(self):
        self.assertEqual(extract_urls("https://a.com/f.zip https://a.com/f.zip"), ["https://a.com/f.zip"])

    def test_recognises_file_links(self):
        self.assertTrue(looks_downloadable("https://x.com/a/setup.exe"))
        self.assertTrue(looks_downloadable("https://x.com/v.MP4"))

    def test_ignores_pages(self):
        self.assertFalse(looks_downloadable("https://x.com/about"))
        self.assertFalse(looks_downloadable("https://x.com/dir/"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
