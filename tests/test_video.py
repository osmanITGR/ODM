"""Video plan selection. Network-free: MediaInfo is built directly."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm.video import (
    MediaFormat,
    MediaInfo,
    _codec,
    _height_from_name,
    suggested_filename,
)


def fmt(fid, ext="mp4", height=None, vcodec="none", acodec="none", size=None):
    label = f"{height}p" if height else "audio"
    return MediaFormat(fid, f"https://x/{fid}", ext, f"{label} ({ext})", size, height, vcodec, acodec)


def video(fid, height, ext="mp4", size=None):
    return fmt(fid, ext, height, vcodec="avc1", acodec="none", size=size)


def audio(fid, ext="m4a", size=None):
    return fmt(fid, ext, None, vcodec="none", acodec="mp4a", size=size)


def progressive(fid, height, ext="mp4", size=None):
    return fmt(fid, ext, height, vcodec="avc1", acodec="mp4a", size=size)


def info(formats):
    return MediaInfo("Clip", "https://x/watch", 100, None, formats)


class TestFormatFlags(unittest.TestCase):
    def test_stream_kind_detection(self):
        self.assertTrue(video("v", 720).has_video)
        self.assertFalse(video("v", 720).has_audio)
        self.assertTrue(audio("a").has_audio)
        self.assertTrue(progressive("p", 360).is_complete)
        self.assertFalse(video("v", 720).is_complete)


class TestPlan(unittest.TestCase):
    def test_prefers_progressive_when_present(self):
        plan = info([progressive("p", 360), video("v", 1080), audio("a")]).plan()
        self.assertFalse(plan.needs_mux)
        self.assertEqual(plan.video.format_id, "p")
        self.assertIsNone(plan.audio)

    def test_pairs_video_and_audio_when_split(self):
        plan = info([video("v", 1080), audio("a")]).plan()
        self.assertTrue(plan.needs_mux)
        self.assertEqual(plan.video.format_id, "v")
        self.assertEqual(plan.audio.format_id, "a")
        self.assertEqual(len(plan.streams), 2)

    def test_height_cap_is_respected(self):
        formats = [video("hi", 2160), video("mid", 720), video("lo", 360), audio("a")]
        plan = info(formats).plan(max_height=720)
        self.assertEqual(plan.video.height, 720)

    def test_cap_below_everything_falls_back_to_lowest_available(self):
        plan = info([video("only", 1080), audio("a")]).plan(max_height=240)
        self.assertEqual(plan.video.height, 1080)

    def test_prefers_mp4_at_equal_height(self):
        formats = [video("w", 720, ext="webm"), video("m", 720, ext="mp4"), audio("a")]
        plan = info(formats).plan()
        self.assertEqual(plan.video.ext, "mp4")

    def test_audio_only_source(self):
        plan = info([audio("a")]).plan()
        self.assertIsNone(plan.video)
        self.assertEqual(plan.audio.format_id, "a")
        self.assertFalse(plan.needs_mux)

    def test_raises_when_nothing_usable(self):
        with self.assertRaises(ValueError):
            info([]).plan()

    def test_total_size_needs_every_part_known(self):
        known = info([video("v", 720, size=100), audio("a", size=20)]).plan()
        self.assertEqual(known.total_size, 120)
        unknown = info([video("v", 720, size=None), audio("a", size=20)]).plan()
        self.assertIsNone(unknown.total_size)

    def test_heights_are_listed_high_to_low(self):
        i = info([video("a", 360), video("b", 1080), video("c", 720)])
        self.assertEqual(i.video_heights(), [1080, 720, 360])


class TestFilename(unittest.TestCase):
    def test_includes_quality_and_extension(self):
        i = info([video("v", 720)])
        self.assertEqual(suggested_filename(i, i.formats[0]), "Clip.720p.mp4")

    def test_audio_has_no_quality_suffix(self):
        i = info([audio("a", ext="m4a")])
        self.assertEqual(suggested_filename(i, i.formats[0]), "Clip.m4a")


class TestCodecNormalisation(unittest.TestCase):
    """Extractors disagree about how to say "this track is absent"."""

    def test_missing_field_is_not_treated_as_absent(self):
        # Facebook omits vcodec/acodec entirely. Reading that as "no tracks"
        # made every Facebook video undownloadable.
        self.assertEqual(_codec(None), "unknown")

    def test_explicit_none_stays_absent(self):
        self.assertEqual(_codec("none"), "none")

    def test_empty_string_is_absent(self):
        self.assertEqual(_codec(""), "none")

    def test_a_real_codec_passes_through(self):
        self.assertEqual(_codec("avc1.640028"), "avc1.640028")

    def test_unknown_codecs_make_a_stream_usable(self):
        # A progressive mp4 with unknown codecs must still be downloadable.
        stream = MediaFormat(
            "sd", "https://x/sd", "mp4", "sd (mp4)", None, 360,
            "unknown", "unknown",
        )
        self.assertTrue(stream.has_video)
        self.assertTrue(stream.has_audio)
        self.assertTrue(stream.is_complete)


class TestHeightFromName(unittest.TestCase):
    """Facebook reports no height, only the names "sd" and "hd"."""

    def test_hd_outranks_sd(self):
        self.assertGreater(_height_from_name("hd", ""), _height_from_name("sd", ""))

    def test_reads_the_format_note_too(self):
        self.assertEqual(_height_from_name("", "HD"), 720)

    def test_unrecognised_name_gives_nothing(self):
        self.assertIsNone(_height_from_name("dash-9", "whatever"))

    def test_hd_is_picked_over_sd_when_neither_has_a_height(self):
        # Without this the picker returned whichever came first, usually SD.
        sd = MediaFormat("sd", "https://x/sd", "mp4", "sd (mp4)", None,
                         _height_from_name("sd", ""), "unknown", "unknown")
        hd = MediaFormat("hd", "https://x/hd", "mp4", "hd (mp4)", None,
                         _height_from_name("hd", ""), "unknown", "unknown")
        chosen = info([sd, hd]).plan().video
        self.assertEqual(chosen.format_id, "hd")


if __name__ == "__main__":
    unittest.main(verbosity=2)
