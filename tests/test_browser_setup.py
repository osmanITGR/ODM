"""Helpers that guide the user through loading the browser extension.

Chrome removed silent extension installs in 2018, so the final pick has to be
the user's. Everything leading up to it is automated, and these cover that
part: finding the browsers, opening them at the right page, and putting the
folder on the clipboard so the picker can be filled with one paste.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm import setup


class TestFindBrowsers(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def place(self, *parts: str) -> None:
        """Create a stand-in for a browser executable."""
        exe = self.root.joinpath(*parts)
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("")

    def find_with_root(self):
        with mock.patch.object(setup, "_browser_roots", return_value=[self.root]):
            return setup.find_browsers()

    def test_finds_chrome(self):
        self.place("Google", "Chrome", "Application", "chrome.exe")
        found = self.find_with_root()
        self.assertEqual([name for name, _, _ in found], ["Chrome"])

    def test_finds_several_and_keeps_their_order(self):
        self.place("Google", "Chrome", "Application", "chrome.exe")
        self.place("Microsoft", "Edge", "Application", "msedge.exe")
        self.place("Vivaldi", "Application", "vivaldi.exe")

        self.assertEqual(
            [name for name, _, _ in self.find_with_root()],
            ["Chrome", "Edge", "Vivaldi"],
        )

    def test_each_browser_gets_its_own_extensions_url(self):
        self.place("Google", "Chrome", "Application", "chrome.exe")
        self.place("Microsoft", "Edge", "Application", "msedge.exe")

        urls = {name: url for name, url, _ in self.find_with_root()}
        self.assertEqual(urls["Chrome"], "chrome://extensions")
        self.assertEqual(urls["Edge"], "edge://extensions")

    def test_no_browsers_installed_is_not_an_error(self):
        # The window falls back to telling the user what to type.
        self.assertEqual(self.find_with_root(), [])

    def test_the_path_returned_is_the_real_executable(self):
        self.place("Google", "Chrome", "Application", "chrome.exe")
        _, _, exe = self.find_with_root()[0]
        self.assertTrue(exe.is_file())
        self.assertEqual(exe.name, "chrome.exe")


class TestBrowserOrdering(unittest.TestCase):
    """The first browser in the list is the one opened automatically.

    It has to be the browser the user is actually in, or the extensions page
    appears somewhere they are not looking.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for parts in (
            ("Google", "Chrome", "Application", "chrome.exe"),
            ("Microsoft", "Edge", "Application", "msedge.exe"),
            ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ):
            exe = self.root.joinpath(*parts)
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def order(self, running: set[str], default: str | None) -> list[str]:
        with mock.patch.object(setup, "_browser_roots", return_value=[self.root]), \
             mock.patch.object(setup, "_running_browser_names", return_value=running), \
             mock.patch.object(setup, "_default_browser_name", return_value=default):
            return [name for name, _, _ in setup.find_browsers()]

    def test_a_running_browser_comes_first(self):
        self.assertEqual(self.order({"Brave"}, None)[0], "Brave")

    def test_running_beats_the_default(self):
        self.assertEqual(self.order({"Brave"}, "Chrome")[0], "Brave")

    def test_the_default_wins_when_nothing_is_running(self):
        self.assertEqual(self.order(set(), "Edge")[0], "Edge")

    def test_installed_order_is_kept_when_there_is_no_signal(self):
        # Stable between launches rather than arbitrary.
        self.assertEqual(self.order(set(), None), ["Chrome", "Edge", "Brave"])

    def test_every_browser_is_still_offered(self):
        # Ordering must not drop the ones the user might switch to.
        self.assertEqual(sorted(self.order({"Brave"}, "Chrome")),
                         ["Brave", "Chrome", "Edge"])


class TestRunningBrowserDetection(unittest.TestCase):
    def test_process_names_map_to_browser_names(self):
        with mock.patch.object(setup.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout="chrome\nmsedge\n")
            self.assertEqual(setup._running_browser_names(), {"Chrome", "Edge"})

    def test_an_unknown_process_is_ignored(self):
        with mock.patch.object(setup.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout="chrome\nfirefox\n")
            # Firefox uses a different extension system and is not offered.
            self.assertEqual(setup._running_browser_names(), {"Chrome"})

    def test_a_failure_is_not_fatal(self):
        # Ordering falls back to the default browser instead.
        with mock.patch.object(setup.subprocess, "run", side_effect=OSError):
            self.assertEqual(setup._running_browser_names(), set())


class TestOpenExtensionsPage(unittest.TestCase):
    def test_passes_the_url_to_that_browser_not_the_shell(self):
        # chrome:// and edge:// mean nothing to the default handler, so the
        # URL has to go to the browser's own executable.
        browser = ("Chrome", "chrome://extensions", Path("C:/fake/chrome.exe"))
        with mock.patch.object(setup.subprocess, "Popen") as popen:
            self.assertTrue(setup.open_extensions_page(browser))

        command = popen.call_args[0][0]
        self.assertEqual(command[0], "C:/fake/chrome.exe".replace("/", os.sep))
        self.assertEqual(command[1], "chrome://extensions")

    def test_a_missing_executable_reports_failure(self):
        browser = ("Chrome", "chrome://extensions", Path("C:/nope/chrome.exe"))
        with mock.patch.object(setup.subprocess, "Popen", side_effect=OSError):
            self.assertFalse(setup.open_extensions_page(browser))


class TestClipboard(unittest.TestCase):
    def test_the_path_survives_the_round_trip(self):
        target = str(setup.EXTENSION_DIR)
        if not setup.copy_to_clipboard(target):
            self.skipTest("clipboard unavailable in this environment")

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), target)

    def test_a_failure_is_reported_rather_than_raised(self):
        with mock.patch.object(setup.subprocess, "run", side_effect=OSError):
            self.assertFalse(setup.copy_to_clipboard("anything"))


class TestLaunchInstalled(unittest.TestCase):
    def test_token_flag_is_passed_only_when_asked(self):
        with mock.patch.object(setup.subprocess, "Popen") as popen:
            setup.launch_installed(copy_token=True)
            self.assertIn("--copy-token", popen.call_args[0][0])

        with mock.patch.object(setup.subprocess, "Popen") as popen:
            setup.launch_installed()
            self.assertNotIn("--copy-token", popen.call_args[0][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
