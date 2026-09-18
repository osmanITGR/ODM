"""Scheduler window logic."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odm.scheduler import Scheduler, Window, parse_window


class FakeManager:
    def __init__(self):
        self.paused = 0
        self.resumed = 0

    def pause_all(self):
        self.paused += 1

    def resume_all(self):
        self.resumed += 1


class TestWindow(unittest.TestCase):
    def test_daytime_window(self):
        w = Window(dtime(9, 0), dtime(17, 0))
        self.assertTrue(w.contains(dtime(9, 0)))
        self.assertTrue(w.contains(dtime(12, 30)))
        self.assertFalse(w.contains(dtime(17, 0)))
        self.assertFalse(w.contains(dtime(8, 59)))

    def test_window_crossing_midnight(self):
        w = Window(dtime(23, 0), dtime(6, 0))
        self.assertTrue(w.contains(dtime(23, 30)))
        self.assertTrue(w.contains(dtime(2, 0)))
        self.assertFalse(w.contains(dtime(12, 0)))
        self.assertFalse(w.contains(dtime(6, 0)))

    def test_equal_bounds_means_always(self):
        w = Window(dtime(0, 0), dtime(0, 0))
        self.assertTrue(w.contains(dtime(3, 14)))
        self.assertTrue(w.contains(dtime(19, 45)))

    def test_next_start_today_or_tomorrow(self):
        w = Window(dtime(23, 0), dtime(6, 0))
        morning = datetime(2026, 9, 18, 10, 0)
        self.assertEqual(w.next_start(morning), datetime(2026, 9, 18, 23, 0))
        late = datetime(2026, 9, 18, 23, 30)
        self.assertEqual(w.next_start(late), datetime(2026, 9, 19, 23, 0))


class TestParse(unittest.TestCase):
    def test_parses_range(self):
        w = parse_window("23:00-06:30")
        self.assertEqual(w.start, dtime(23, 0))
        self.assertEqual(w.end, dtime(6, 30))

    def test_tolerates_spaces_and_bare_hours(self):
        w = parse_window(" 9 - 17 ")
        self.assertEqual(w.start, dtime(9, 0))
        self.assertEqual(w.end, dtime(17, 0))


class TestScheduler(unittest.TestCase):
    def test_disabled_allows_everything(self):
        s = Scheduler(FakeManager(), Window(dtime(1, 0), dtime(2, 0)))
        self.assertTrue(s.allowed_now(datetime(2026, 9, 18, 15, 0)))

    def test_enabled_blocks_outside_window(self):
        s = Scheduler(FakeManager(), Window(dtime(1, 0), dtime(2, 0)))
        s.enabled = True
        self.assertFalse(s.allowed_now(datetime(2026, 9, 18, 15, 0)))
        self.assertTrue(s.allowed_now(datetime(2026, 9, 18, 1, 30)))

    def test_tick_pauses_then_resumes_once_each(self):
        manager = FakeManager()
        s = Scheduler(manager, Window(dtime(1, 0), dtime(2, 0)))
        s.enabled = True

        s.allowed_now = lambda now=None: False
        s.tick()
        s.tick()
        self.assertEqual(manager.paused, 1, "should not re-pause every tick")

        s.allowed_now = lambda now=None: True
        s.tick()
        s.tick()
        self.assertEqual(manager.resumed, 1, "should not re-resume every tick")

    def test_stop_releases_a_suspended_queue(self):
        manager = FakeManager()
        s = Scheduler(manager, Window(dtime(1, 0), dtime(2, 0)))
        s.enabled = True
        s.allowed_now = lambda now=None: False
        s.tick()
        self.assertEqual(manager.paused, 1)
        s.stop()
        self.assertEqual(manager.resumed, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
