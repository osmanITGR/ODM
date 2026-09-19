"""Checking GitHub for a newer release.

People install from a GitHub release and then never hear about the next one,
so a fix only reaches whoever happens to look. The comparison is where a
mistake is expensive: too strict and nobody is told, too loose and everyone
is told every launch.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm import updater


def api_payload(tag: str, assets=None, body: str = "") -> bytes:
    return json.dumps({
        "tag_name": tag,
        "body": body,
        "assets": assets if assets is not None else [{
            "name": "ODM.exe",
            "size": 27_000_000,
            "browser_download_url": f"https://example.com/{tag}/ODM.exe",
        }],
    }).encode("utf-8")


class FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestVersionCompare(unittest.TestCase):
    def test_a_higher_patch_is_newer(self):
        self.assertEqual(updater._compare("1.3.1", "1.3.0"), 1)

    def test_an_older_version_is_not_newer(self):
        self.assertEqual(updater._compare("1.3.0", "1.3.1"), -1)

    def test_equal_versions_compare_equal(self):
        self.assertEqual(updater._compare("1.3.1", "1.3.1"), 0)

    def test_missing_components_are_treated_as_zero(self):
        # 1.3 and 1.3.0 are the same release written two ways.
        self.assertEqual(updater._compare("1.3", "1.3.0"), 0)

    def test_numbers_compare_numerically_not_alphabetically(self):
        # The classic trap: "1.10" sorts before "1.9" as text.
        self.assertEqual(updater._compare("1.10.0", "1.9.0"), 1)

    def test_a_v_prefix_is_ignored(self):
        self.assertEqual(updater._compare("v1.4", "1.3.1"), 1)

    def test_a_suffix_is_ignored(self):
        self.assertEqual(updater._compare("1.0.0-beta", "1.0.0"), 0)

    def test_nonsense_does_not_raise(self):
        # A malformed tag must not crash the app at launch.
        self.assertIsInstance(updater._compare("not-a-version", "1.0.0"), int)


class TestCheck(unittest.TestCase):
    def test_reads_the_tag_and_the_windows_asset(self):
        with mock.patch.object(
            updater.urllib.request, "urlopen",
            return_value=FakeResponse(api_payload("v9.9.9")),
        ):
            release = updater.check()

        self.assertEqual(release.version, "9.9.9")
        self.assertTrue(release.download_url.endswith("ODM.exe"))
        self.assertEqual(release.size, 27_000_000)
        self.assertTrue(release.is_newer)

    def test_the_current_version_is_not_offered(self):
        from odm import __version__

        with mock.patch.object(
            updater.urllib.request, "urlopen",
            return_value=FakeResponse(api_payload(f"v{__version__}")),
        ):
            self.assertFalse(updater.check().is_newer)

    def test_an_older_release_is_not_offered(self):
        with mock.patch.object(
            updater.urllib.request, "urlopen",
            return_value=FakeResponse(api_payload("v0.0.1")),
        ):
            self.assertFalse(updater.check().is_newer)

    def test_a_release_without_the_exe_has_no_download(self):
        # An Android-only release must not offer a Windows update.
        assets = [{"name": "ODM-Android.apk", "size": 1, "browser_download_url": "x"}]
        with mock.patch.object(
            updater.urllib.request, "urlopen",
            return_value=FakeResponse(api_payload("v9.9.9", assets=assets)),
        ):
            self.assertIsNone(updater.check().download_url)

    def test_being_offline_is_silent(self):
        # Someone with no internet should see nothing, not an error.
        with mock.patch.object(
            updater.urllib.request, "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            self.assertIsNone(updater.check())

    def test_a_broken_response_is_silent(self):
        with mock.patch.object(
            updater.urllib.request, "urlopen",
            return_value=FakeResponse(b"not json"),
        ):
            self.assertIsNone(updater.check())

    def test_a_response_without_a_tag_is_ignored(self):
        with mock.patch.object(
            updater.urllib.request, "urlopen",
            return_value=FakeResponse(b'{"assets":[]}'),
        ):
            self.assertIsNone(updater.check())


class TestSummarise(unittest.TestCase):
    def test_keeps_only_the_bullet_points(self):
        notes = (
            "## Download\n\nSome prose about installing.\n\n"
            "- Fixed the thing\n"
            "- Fixed the other thing\n\n"
            "More prose.\n"
        )
        summary = updater.summarise(notes)
        self.assertIn("Fixed the thing", summary)
        self.assertNotIn("prose", summary)

    def test_strips_markdown_that_would_show_literally(self):
        self.assertNotIn("**", updater.summarise("- **Bold** item"))
        self.assertNotIn("`", updater.summarise("- A `code` item"))

    def test_handles_notes_with_no_bullets(self):
        self.assertEqual(updater.summarise("Just a sentence."), "")

    def test_long_notes_are_cut_at_a_line_boundary(self):
        notes = "\n".join(f"- item number {i} with some text" for i in range(40))
        summary = updater.summarise(notes, limit=120)
        self.assertLessEqual(len(summary), 120)
        # Cut between lines, not mid-word.
        self.assertFalse(summary.endswith("item"))

    def test_non_ascii_notes_survive(self):
        # The release notes are written in Bengali.
        summary = updater.summarise("- ফেসবুক ভিডিও এখন নামে")
        self.assertIn("ফেসবুক", summary)


class TestCheckInterval(unittest.TestCase):
    """The automatic check is daily.

    GitHub allows 60 unauthenticated calls an hour per address, shared by
    everyone behind it, so checking at every launch would spend that on
    people who restart often.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self._saved = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp.name

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._saved
        self.tmp.cleanup()

    def test_the_first_run_checks(self):
        self.assertTrue(updater.should_check())

    def test_a_second_launch_soon_after_does_not(self):
        updater.note_checked()
        self.assertFalse(updater.should_check())

    def test_it_checks_again_the_next_day(self):
        updater.note_checked()
        stale = time.time() - 25 * 3600
        updater._stamp_file().write_text(str(stale), encoding="utf-8")
        self.assertTrue(updater.should_check())

    def test_a_corrupt_stamp_just_checks(self):
        updater.note_checked()
        updater._stamp_file().write_text("not a number", encoding="utf-8")
        self.assertTrue(updater.should_check())

    def test_an_unwritable_location_is_not_fatal(self):
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "file-not-dir")
        Path(os.environ["LOCALAPPDATA"]).write_text("blocks the mkdir")
        updater.note_checked()  # must not raise
        self.assertTrue(updater.should_check())


class TestInstall(unittest.TestCase):
    def test_refuses_when_running_from_source(self):
        # There is no exe to replace, so this must not pretend otherwise.
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertFalse(updater.install(Path(__file__)))

    def test_refuses_a_missing_download(self):
        self.assertFalse(updater.install(Path("C:/nope/ODM.exe")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
