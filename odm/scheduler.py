"""Time windows that decide when queued downloads are allowed to run."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta


@dataclass
class Window:
    """A daily allowed period. `start == end` means the whole day."""

    start: dtime
    end: dtime

    def contains(self, moment: dtime) -> bool:
        if self.start == self.end:
            return True
        if self.start < self.end:
            return self.start <= moment < self.end
        # Wraps past midnight, e.g. 23:00 -> 06:00.
        return moment >= self.start or moment < self.end

    def next_start(self, now: datetime) -> datetime:
        today = now.replace(
            hour=self.start.hour, minute=self.start.minute, second=0, microsecond=0
        )
        return today if today > now else today + timedelta(days=1)


def parse_window(text: str) -> Window:
    """Parse 'HH:MM-HH:MM' into a Window."""
    start_s, _, end_s = text.partition("-")
    return Window(_parse_time(start_s.strip()), _parse_time(end_s.strip()))


def _parse_time(text: str) -> dtime:
    hours, _, minutes = text.partition(":")
    return dtime(int(hours) % 24, int(minutes or 0) % 60)


class Scheduler:
    """Gates a Manager: pauses outside the window, resumes inside it.

    Disabled by default, so downloads run whenever they are queued.
    """

    def __init__(self, manager, window: Window | None = None, poll: float = 20.0):
        self.manager = manager
        self.window = window
        self.poll = poll
        self.enabled = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._suspended = False

    def allowed_now(self, now: datetime | None = None) -> bool:
        if not self.enabled or self.window is None:
            return True
        return self.window.contains((now or datetime.now()).time())

    def next_window_start(self, now: datetime | None = None) -> datetime | None:
        if not self.enabled or self.window is None:
            return None
        return self.window.next_start(now or datetime.now())

    def _apply(self) -> None:
        if self.allowed_now():
            if self._suspended:
                self._suspended = False
                self.manager.resume_all()
        elif not self._suspended:
            self._suspended = True
            self.manager.pause_all()

    def tick(self) -> None:
        """Apply the window once; safe to call from a UI loop."""
        self._apply()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                self._apply()
                self._stop.wait(self.poll)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._suspended:
            self._suspended = False
            self.manager.resume_all()
