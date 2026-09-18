"""Muxing against real ffmpeg, skipped when ffmpeg is absent."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm.video import ffmpeg_path, mux

FFMPEG = ffmpeg_path()


def probe_streams(path):
    exe = Path(FFMPEG).with_name("ffprobe.exe")
    if not exe.exists():
        exe = "ffprobe"
    out = subprocess.run(
        [str(exe), "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class TestMux(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.video = self.dir / "v.mp4"
        self.audio = self.dir / "a.m4a"

        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc=duration=2:size=160x120:rate=10",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.video)],
            check=True, capture_output=True,
        )
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=2",
             "-c:a", "aac", str(self.audio)],
            check=True, capture_output=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_inputs_are_single_stream(self):
        self.assertEqual(probe_streams(self.video), ["video"])
        self.assertEqual(probe_streams(self.audio), ["audio"])

    def test_mux_produces_both_streams(self):
        out = self.dir / "out.mp4"
        mux(self.video, self.audio, out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)
        streams = probe_streams(out)
        self.assertIn("video", streams)
        self.assertIn("audio", streams)

    def test_mux_failure_raises(self):
        missing = self.dir / "nope.mp4"
        with self.assertRaises(RuntimeError):
            mux(missing, self.audio, self.dir / "out2.mp4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
