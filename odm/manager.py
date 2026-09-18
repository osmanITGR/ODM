"""Download queue: runs several downloads at once, bounded by a worker pool."""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .engine import Download, RateLimiter, State


@dataclass
class Task:
    id: str
    download: Download
    thread: threading.Thread | None = None
    # Set when the user pauses: keeps the scheduler from restarting it.
    held: bool = False
    # Set for the video half of a muxed pair; see Manager.add_video.
    companion: "Task | None" = None
    mux_target: Path | None = None
    muxing: bool = False
    final_path: Path | None = None

    @property
    def result_path(self) -> Path:
        return self.final_path or self.mux_target or self.download.target

    @property
    def state(self) -> State:
        return self.download.progress.state

    @property
    def name(self) -> str:
        return self.result_path.name


class Manager:
    """Holds the queue and keeps at most `concurrent` downloads active."""

    def __init__(
        self,
        dest_dir: str | Path = ".",
        connections: int = 8,
        concurrent: int = 3,
        speed_limit: float = 0.0,
        boost: bool = True,
    ):
        self.dest_dir = Path(dest_dir)
        self.connections = connections
        self.concurrent = concurrent
        self.boost = boost
        # One bucket shared by every download, so the cap is app-wide.
        self.limiter = RateLimiter(speed_limit)
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def speed_limit(self) -> float:
        return self.limiter.rate

    @speed_limit.setter
    def speed_limit(self, bytes_per_second: float) -> None:
        self.limiter.set_rate(bytes_per_second)

    # queue ------------------------------------------------------------

    def add(self, url: str, filename: str | None = None, autostart: bool = True) -> Task:
        task = Task(
            id=uuid.uuid4().hex[:12],
            download=Download(
                url, self.dest_dir, self.connections, filename,
                limiter=self.limiter, boost=self.boost,
            ),
        )
        with self._lock:
            self._tasks[task.id] = task
        if autostart:
            self.pump()
        return task

    def add_video(self, info, plan, max_height: int | None = None) -> Task:
        """Queue a video: one task, or a video+audio pair that is muxed on completion."""
        from .video import suggested_filename

        primary_fmt = plan.video or plan.audio
        final_name = suggested_filename(info, primary_fmt)

        if not plan.needs_mux:
            return self.add(primary_fmt.url, filename=final_name)

        stem = Path(final_name).stem
        video_task = self.add(
            plan.video.url, filename=f"{stem}.video.{plan.video.ext}", autostart=False
        )
        audio_task = self.add(
            plan.audio.url, filename=f"{stem}.audio.{plan.audio.ext}", autostart=False
        )
        video_task.companion = audio_task
        video_task.mux_target = self.dest_dir / final_name
        self.pump()
        return video_task

    def _finish_mux(self, task: Task) -> None:
        from .video import mux

        task.muxing = True
        try:
            mux(task.download.target, task.companion.download.target, task.mux_target)
            task.download.target.unlink(missing_ok=True)
            task.companion.download.target.unlink(missing_ok=True)
            with self._lock:
                self._tasks.pop(task.companion.id, None)
            task.final_path = task.mux_target
            task.companion = None
            task.mux_target = None
        except Exception as exc:
            task.download.progress.state = State.ERROR
            task.download.progress.error = f"mux failed: {exc}"
        finally:
            task.muxing = False

    def _pump_mux(self) -> None:
        """Start muxing for any pair whose two halves have both finished."""
        for task in self.tasks():
            if (
                task.mux_target
                and task.companion
                and not task.muxing
                and task.state is State.DONE
                and task.companion.state is State.DONE
            ):
                threading.Thread(target=self._finish_mux, args=(task,), daemon=True).start()

    def remove(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.pop(task_id, None)
        if task and task.state is State.RUNNING:
            task.download.pause()

    def tasks(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    # scheduling -------------------------------------------------------

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(
                1 for t in self._tasks.values()
                if t.thread is not None and t.thread.is_alive()
            )

    def pump(self) -> None:
        """Start queued downloads until the concurrency limit is reached."""
        with self._lock:
            running = sum(1 for t in self._tasks.values() if t.thread and t.thread.is_alive())
            waiting = [
                t for t in self._tasks.values()
                if t.state in (State.PENDING, State.PAUSED)
                and not t.held
                and not (t.thread and t.thread.is_alive())
            ]
            to_start = waiting[: max(0, self.concurrent - running)]
            for task in to_start:
                task.thread = threading.Thread(target=task.download.start, daemon=True)

        for task in to_start:
            task.thread.start()

        self._pump_mux()

    def pause(self, task_id: str) -> None:
        task = self.get(task_id)
        if task and task.state is State.RUNNING:
            task.held = True
            task.download.pause()

    def resume(self, task_id: str) -> None:
        task = self.get(task_id)
        if not task or task.state in (State.RUNNING, State.DONE):
            return
        task.held = False
        self.pump()

    def pause_all(self) -> None:
        for task in self.tasks():
            if task.state is State.RUNNING:
                task.held = True
                task.download.pause()

    def resume_all(self) -> None:
        for task in self.tasks():
            task.held = False
        self.pump()

    def totals(self) -> tuple[int, float]:
        """Combined bytes/sec and count of active downloads."""
        speed = 0.0
        active = 0
        for task in self.tasks():
            if task.state is State.RUNNING:
                speed += task.download.progress.speed
                active += 1
        return active, speed
