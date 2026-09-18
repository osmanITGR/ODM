"""Segmented HTTP download engine."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

USER_AGENT = "ODM/1.0 (+com.osmanit.odm)"
CHUNK = 256 * 1024
# Segments below this are not worth splitting further mid-flight.
MIN_SPLIT = 2 * 1024 * 1024
# Without boost we stay conservative: a couple of streams is enough to cover
# per-connection throttling without hammering the server.
PLAIN_CONNECTIONS = 2


class RateLimiter:
    """Token bucket shared by every worker of a download.

    A limit of 0 means unlimited. Workers call `take` before each read and
    sleep for however long the bucket says they must wait.
    """

    def __init__(self, bytes_per_second: float = 0.0):
        self._rate = max(0.0, bytes_per_second)
        self._tokens = self._rate
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    @property
    def rate(self) -> float:
        return self._rate

    def set_rate(self, bytes_per_second: float) -> None:
        with self._lock:
            self._rate = max(0.0, bytes_per_second)
            self._tokens = min(self._tokens, self._rate) if self._rate else 0.0
            self._updated = time.monotonic()

    def take(self, amount: int) -> None:
        """Wait until `amount` bytes may be read, then spend them.

        The bucket holds at most one second's worth of tokens, so a read larger
        than the current rate could never be satisfied outright: a 256 KB chunk
        under a 128 KB/s cap would wait forever. Such a read is let through on
        a full bucket and the balance carried as a debt, which the next calls
        pay off — the average still holds, and nothing wedges.
        """
        if self._rate <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._rate, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                if amount > self._rate and self._tokens >= self._rate:
                    self._tokens -= amount
                    return
                deficit = amount - self._tokens
                wait = deficit / self._rate
            time.sleep(min(wait, 0.25))


class State(str, Enum):
    PENDING = "pending"
    PROBING = "probing"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"


@dataclass
class Segment:
    index: int
    start: int
    end: int
    done: int = 0

    @property
    def total(self) -> int:
        return self.end - self.start + 1

    @property
    def remaining(self) -> int:
        return self.total - self.done

    @property
    def complete(self) -> bool:
        return self.done >= self.total


@dataclass
class SourceInfo:
    url: str
    size: int | None
    resumable: bool
    filename: str


@dataclass
class Progress:
    downloaded: int = 0
    total: int | None = None
    speed: float = 0.0
    state: State = State.PENDING
    error: str | None = None
    segments: list[tuple[int, int]] = field(default_factory=list)

    @property
    def percent(self) -> float:
        if not self.total:
            return 0.0
        return min(100.0, self.downloaded / self.total * 100.0)

    @property
    def eta(self) -> float | None:
        if not self.total or self.speed <= 0:
            return None
        return max(0.0, (self.total - self.downloaded) / self.speed)


def _filename_from(url: str, headers) -> str:
    disposition = headers.get("Content-Disposition", "") if headers else ""
    if "filename=" in disposition:
        raw = disposition.split("filename=", 1)[1].strip().strip('";\'')
        if raw.lower().startswith("utf-8''"):
            raw = urllib.parse.unquote(raw[7:])
        name = Path(raw).name
        if name:
            return name
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    name = Path(path).name
    return name or "download"


class NotAFileError(ValueError):
    """The URL serves a web page, not something worth downloading."""

    def __str__(self) -> str:
        return (
            "That link is a web page, not a file. If it is a video page, "
            "paste it again so ODM can look for the video on it."
        )


def _reject_web_page(headers) -> None:
    """Refuse a response that is a page rather than a downloadable file.

    Without this, pointing ODM at a video page it cannot extract saves the
    HTML itself: a few hundred KB of markup under the video's name, which
    looks exactly like a corrupt download. Only pages are rejected — an
    unknown or missing type still passes, since plenty of file servers send
    application/octet-stream or nothing at all.
    """
    content_type = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type not in ("text/html", "application/xhtml+xml"):
        return
    # An attachment is a file the server means to be saved, even if it is
    # markup — someone deliberately downloading an .html.
    if "attachment" in (headers.get("Content-Disposition") or "").lower():
        return
    raise NotAFileError


def probe(url: str, timeout: float = 15.0) -> SourceInfo:
    """Discover size, resumability and filename without fetching the body."""
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0", "Accept-Encoding": "identity"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = response.headers
            final_url = response.geturl()
            status = response.status
            _reject_web_page(headers)
            content_range = headers.get("Content-Range", "")
            if status == 206 and "/" in content_range:
                tail = content_range.rsplit("/", 1)[1].strip()
                size = int(tail) if tail.isdigit() else None
                return SourceInfo(final_url, size, size is not None, _filename_from(final_url, headers))
            length = headers.get("Content-Length")
            size = int(length) if length and length.isdigit() else None
            return SourceInfo(final_url, size, False, _filename_from(final_url, headers))
    except urllib.error.HTTPError as exc:
        if exc.code in (416, 501):
            request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                _reject_web_page(response.headers)
                length = response.headers.get("Content-Length")
                size = int(length) if length and length.isdigit() else None
                return SourceInfo(response.geturl(), size, False, _filename_from(response.geturl(), response.headers))
        raise


def plan_segments(size: int, connections: int, min_chunk: int = 1024 * 1024) -> list[Segment]:
    """Split size into roughly equal ranges, avoiding uselessly small parts."""
    count = max(1, min(connections, size // min_chunk or 1))
    base, extra = divmod(size, count)
    segments: list[Segment] = []
    cursor = 0
    for index in range(count):
        length = base + (1 if index < extra else 0)
        segments.append(Segment(index, cursor, cursor + length - 1))
        cursor += length
    return segments


class Download:
    """A single download, resumable and segmented when the server allows it."""

    def __init__(
        self,
        url: str,
        dest_dir: str | Path = ".",
        connections: int = 8,
        filename: str | None = None,
        timeout: float = 30.0,
        limiter: "RateLimiter | None" = None,
        boost: bool = True,
    ):
        self.url = url
        self.dest_dir = Path(dest_dir)
        self.connections = max(1, connections)
        self.timeout = timeout
        self._forced_name = filename
        self.limiter = limiter or RateLimiter(0.0)
        self.boost = boost

        self.info: SourceInfo | None = None
        self.segments: list[Segment] = []
        self.progress = Progress()

        self._lock = threading.Lock()
        self._meta_lock = threading.Lock()
        self._split_lock = threading.Lock()
        self._pause = threading.Event()
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._samples: list[tuple[float, int]] = []
        self._window_start = time.monotonic()
        self._last_error: str | None = None

    @property
    def active_connections(self) -> int:
        """How many streams to open. This is what the boost toggle buys you."""
        if self.boost:
            return self.connections
        return min(self.connections, PLAIN_CONNECTIONS)

    # paths -------------------------------------------------------------

    @property
    def target(self) -> Path:
        name = self._forced_name or (self.info.filename if self.info else "download")
        return self.dest_dir / name

    @property
    def part_file(self) -> Path:
        return self.target.with_suffix(self.target.suffix + ".part")

    @property
    def meta_file(self) -> Path:
        # Keyed by URL, not by filename: resume has to find this before the
        # remote filename is known.
        digest = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]
        return self.dest_dir / f".odm-{digest}.json"

    # state persistence -------------------------------------------------

    def _save_meta(self) -> None:
        if not self.info:
            return
        # Serialised: the progress loop and pause() both save, and on Windows a
        # replace fails outright if another writer still holds the temp file.
        with self._meta_lock:
            with self._split_lock:
                segments = [[s.index, s.start, s.end, s.done] for s in self.segments]
            payload = {
                "url": self.url,
                "final_url": self.info.url,
                "size": self.info.size,
                "filename": self.target.name,
                "segments": segments,
            }
            tmp = self.meta_file.with_name(f"{self.meta_file.name}.{threading.get_ident():x}.tmp")
            try:
                tmp.write_text(json.dumps(payload), encoding="utf-8")
                tmp.replace(self.meta_file)
            except OSError:
                tmp.unlink(missing_ok=True)

    def _load_meta(self) -> bool:
        if not self.meta_file.exists():
            return False
        try:
            payload = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if payload.get("url") != self.url or not payload.get("segments"):
            return False

        info = SourceInfo(
            payload.get("final_url") or self.url,
            payload.get("size"),
            True,
            payload.get("filename") or "download",
        )
        segments = [Segment(i, s, e, d) for i, s, e, d in payload["segments"]]

        # part_file derives from info/_forced_name, so commit those before
        # checking that the partial data is actually still on disk.
        saved_info, saved_name = self.info, self._forced_name
        self.info = info
        self._forced_name = self._forced_name or payload.get("filename")
        if not self.part_file.exists() or self.part_file.stat().st_size != (info.size or -1):
            self.info, self._forced_name = saved_info, saved_name
            return False

        self.segments = segments
        with self._lock:
            self.progress.downloaded = sum(s.done for s in self.segments)
            self.progress.total = info.size
        return True

    # speed -------------------------------------------------------------

    def _note_bytes(self, count: int) -> None:
        now = time.monotonic()
        with self._lock:
            self.progress.downloaded += count
            self._samples.append((now, count))
            cutoff = now - 3.0
            while self._samples and self._samples[0][0] < cutoff:
                # The evicted sample's timestamp is where the retained window
                # now begins.
                self._window_start = self._samples.pop(0)[0]
            self._window_start = max(self._window_start, cutoff)
            if len(self._samples) > 1:
                # Measure from just before the first retained sample, so the
                # bytes in it are counted over the window that produced them.
                span = now - self._window_start
                moved = sum(c for _, c in self._samples)
                self.progress.speed = moved / span if span > 0 else 0.0

    # work stealing -----------------------------------------------------

    def _work_outstanding(self) -> bool:
        """True while any segment is still unfinished."""
        with self._split_lock:
            return any(not seg.complete for seg in self.segments)

    def _steal_work(self) -> Segment | None:
        """Halve the largest lagging segment and take the tail of it.

        Without this, one slow connection holds up the whole transfer while
        the workers that already finished sit idle.
        """
        if not self.boost:
            return None

        with self._split_lock:
            candidate = None
            best_remaining = MIN_SPLIT
            for seg in self.segments:
                if seg.complete:
                    continue
                remaining = seg.remaining
                if remaining > best_remaining:
                    candidate = seg
                    best_remaining = remaining

            if candidate is None:
                return None

            # Cut the untouched tail in half; the original worker keeps writing
            # into the front half and stops at the new boundary.
            split_at = candidate.end - best_remaining // 2
            if split_at <= candidate.start + candidate.done:
                return None

            tail = Segment(len(self.segments), split_at + 1, candidate.end)
            candidate.end = split_at
            self.segments.append(tail)
            return tail

    # workers -----------------------------------------------------------

    def _worker(self, segment: Segment) -> None:
        """Fetch a segment, then keep stealing work until nothing is left.

        A worker that runs dry does not exit while other segments are still
        lagging: it splits the tail off the slowest one and helps finish it.
        That is what makes boost measurably faster rather than a label.
        """
        while segment is not None and not self._stop.is_set():
            self._fetch_segment(segment)
            if self._stop.is_set() or not segment.complete:
                return
            segment = self._steal_work()
            while segment is None and self.boost and self._work_outstanding():
                # Nothing splittable yet, but peers are still going. Wait for a
                # laggard to fall far enough behind to be worth halving.
                if self._stop.wait(0.25):
                    return
                segment = self._steal_work()

    def _fetch_segment(self, segment: Segment) -> None:
        while not segment.complete and not self._stop.is_set():
            self._pause.wait()
            if self._stop.is_set():
                return
            start = segment.start + segment.done
            headers = {
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "identity",
                "Range": f"bytes={start}-{segment.end}",
            }
            request = urllib.request.Request(self.info.url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    with open(self.part_file, "r+b") as handle:
                        handle.seek(start)
                        while True:
                            if self._stop.is_set():
                                return
                            if not self._pause.is_set():
                                break
                            self.limiter.take(CHUNK)
                            block = response.read(CHUNK)
                            if not block:
                                return
                            # A stealer may have moved segment.end since this
                            # response opened, so never write past it.
                            wanted = segment.remaining
                            if wanted <= 0:
                                return
                            if len(block) > wanted:
                                block = block[:wanted]
                            handle.write(block)
                            segment.done += len(block)
                            self._note_bytes(len(block))
                            if segment.complete:
                                return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                if self._stop.is_set():
                    return
                self._last_error = str(exc)
                time.sleep(1.0)

    def _single_stream(self) -> None:
        request = urllib.request.Request(
            self.info.url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            with open(self.part_file, "wb") as handle:
                while True:
                    if self._stop.is_set():
                        return
                    self._pause.wait()
                    self.limiter.take(CHUNK)
                    block = response.read(CHUNK)
                    if not block:
                        return
                    handle.write(block)
                    self._note_bytes(len(block))

    # public API --------------------------------------------------------

    def start(self) -> None:
        self._pause.set()
        self._stop.clear()
        self._last_error = None
        with self._lock:
            # A resumed download must not average against its old idle gap.
            self._samples.clear()
            self._window_start = time.monotonic()

        try:
            resumed = self._load_meta()
            if not resumed:
                with self._lock:
                    self.progress.state = State.PROBING
                self.info = probe(self.url, timeout=self.timeout)
                self.dest_dir.mkdir(parents=True, exist_ok=True)
                with self._lock:
                    self.progress.total = self.info.size
                if self.info.resumable and self.info.size:
                    self.segments = plan_segments(self.info.size, self.active_connections)
                    with open(self.part_file, "wb") as handle:
                        handle.truncate(self.info.size)
                    self._save_meta()
                else:
                    self.segments = []

            with self._lock:
                self.progress.state = State.RUNNING

            if self.segments:
                self._workers = [
                    threading.Thread(target=self._worker, args=(s,), daemon=True)
                    for s in list(self.segments)
                    if not s.complete
                ]
                for worker in self._workers:
                    worker.start()
                while any(w.is_alive() for w in self._workers):
                    for worker in self._workers:
                        worker.join(timeout=0.5)
                    self._save_meta()
                    with self._split_lock:
                        snapshot = [(s.done, s.total) for s in self.segments]
                    with self._lock:
                        self.progress.segments = snapshot
            else:
                self._single_stream()

            if self._stop.is_set():
                with self._lock:
                    self.progress.state = State.PAUSED
                return

            incomplete = [s for s in self.segments if not s.complete]
            if incomplete:
                with self._lock:
                    self.progress.state = State.ERROR
                    self.progress.error = self._last_error or "download incomplete"
                return

            self.part_file.replace(self.target)
            self.meta_file.unlink(missing_ok=True)
            with self._lock:
                self.progress.state = State.DONE
                if self.progress.total:
                    self.progress.downloaded = self.progress.total

        except Exception as exc:
            with self._lock:
                self.progress.state = State.ERROR
                self.progress.error = str(exc)

    def pause(self) -> None:
        self._pause.clear()
        self._stop.set()
        with self._lock:
            self.progress.state = State.PAUSED
        self._save_meta()

    def resume(self) -> None:
        if self.progress.state in (State.RUNNING, State.DONE):
            return
        self.start()
