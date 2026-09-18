"""Video extraction: resolve a page URL into downloadable media streams.

yt-dlp does the site-specific extraction; ODM's own engine does the transfer,
so videos get the same segmented speed and resume behaviour as any other file.
"""

from __future__ import annotations

from dataclasses import dataclass


class ExtractorUnavailable(RuntimeError):
    """yt-dlp is not installed."""


@dataclass
class MediaFormat:
    format_id: str
    url: str
    ext: str
    label: str
    filesize: int | None
    height: int | None
    vcodec: str
    acodec: str

    @property
    def has_video(self) -> bool:
        return self.vcodec not in ("none", "", None)

    @property
    def has_audio(self) -> bool:
        return self.acodec not in ("none", "", None)

    @property
    def is_complete(self) -> bool:
        """True when this stream needs no muxing with a second one."""
        return self.has_video and self.has_audio


@dataclass
class MediaInfo:
    title: str
    webpage_url: str
    duration: int | None
    thumbnail: str | None
    formats: list[MediaFormat]

    def best_complete(self) -> MediaFormat | None:
        candidates = [f for f in self.formats if f.is_complete]
        if not candidates:
            return None
        return max(candidates, key=lambda f: (f.height or 0, f.filesize or 0))

    def best_audio(self) -> MediaFormat | None:
        candidates = [f for f in self.formats if f.has_audio and not f.has_video]
        if not candidates:
            return None
        return max(candidates, key=lambda f: f.filesize or 0)

    def best_video(self, max_height: int | None = None) -> MediaFormat | None:
        candidates = [f for f in self.formats if f.has_video and not f.has_audio]
        if max_height:
            candidates = [f for f in candidates if (f.height or 0) <= max_height] or candidates
        if not candidates:
            return None
        # Prefer mp4 at equal height: it muxes without re-encoding and plays everywhere.
        return max(candidates, key=lambda f: ((f.height or 0), f.ext == "mp4", -(f.filesize or 0)))

    def video_heights(self) -> list[int]:
        heights = {f.height for f in self.formats if f.has_video and f.height}
        return sorted(heights, reverse=True)

    def plan(self, max_height: int | None = None) -> "DownloadPlan":
        """Pick the streams needed for one playable file."""
        complete = self.best_complete()
        if complete and (not max_height or (complete.height or 0) <= max_height):
            return DownloadPlan(video=complete, audio=None, needs_mux=False)

        video = self.best_video(max_height)
        if video is None:
            audio = self.best_audio()
            if audio is None:
                raise ValueError("no downloadable streams found")
            return DownloadPlan(video=None, audio=audio, needs_mux=False)

        if video.has_audio:
            return DownloadPlan(video=video, audio=None, needs_mux=False)

        audio = self.best_audio()
        return DownloadPlan(video=video, audio=audio, needs_mux=audio is not None)


@dataclass
class DownloadPlan:
    video: MediaFormat | None
    audio: MediaFormat | None
    needs_mux: bool

    @property
    def streams(self) -> list[MediaFormat]:
        return [f for f in (self.video, self.audio) if f is not None]

    @property
    def total_size(self) -> int | None:
        sizes = [f.filesize for f in self.streams]
        return sum(sizes) if all(s is not None for s in sizes) else None


def available() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def is_media_page(url: str) -> bool:
    """Cheap check for whether a URL is worth handing to the extractor."""
    if not url.lower().startswith(("http://", "https://")):
        return False
    try:
        import yt_dlp
    except ImportError:
        return False

    from yt_dlp.extractor import gen_extractor_classes

    for extractor in gen_extractor_classes():
        name = extractor.IE_NAME
        if name == "generic":
            continue
        try:
            if extractor.suitable(url):
                return True
        except Exception:
            continue
    return False


def _safe_title(raw: str) -> str:
    cleaned = "".join(c for c in raw if c not in '<>:"/\\|?*').strip()
    return (cleaned or "video")[:120]


def extract(url: str, timeout: float = 30.0) -> MediaInfo:
    """Resolve a page URL into its media formats without downloading."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise ExtractorUnavailable("yt-dlp is not installed") from exc

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": timeout,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        data = ydl.extract_info(url, download=False)

    if data.get("_type") == "playlist" and data.get("entries"):
        data = data["entries"][0]

    formats: list[MediaFormat] = []
    for raw in data.get("formats", []):
        stream_url = raw.get("url")
        if not stream_url:
            continue
        # Fragmented streams (HLS/DASH) cannot be fetched as one ranged file.
        if raw.get("protocol", "") not in ("http", "https"):
            continue

        height = raw.get("height")
        note = raw.get("format_note") or ""
        ext = raw.get("ext") or "bin"
        size = raw.get("filesize") or raw.get("filesize_approx")

        if height:
            label = f"{height}p"
        elif raw.get("acodec") not in ("none", None) and raw.get("vcodec") in ("none", None):
            abr = raw.get("abr")
            label = f"audio {int(abr)}k" if abr else "audio"
        else:
            label = note or raw.get("format_id", "stream")

        formats.append(
            MediaFormat(
                format_id=raw.get("format_id", ""),
                url=stream_url,
                ext=ext,
                label=f"{label} ({ext})",
                filesize=size,
                height=height,
                vcodec=raw.get("vcodec") or "none",
                acodec=raw.get("acodec") or "none",
            )
        )

    return MediaInfo(
        title=_safe_title(data.get("title") or "video"),
        webpage_url=data.get("webpage_url") or url,
        duration=data.get("duration"),
        thumbnail=data.get("thumbnail"),
        formats=formats,
    )


def suggested_filename(info: MediaInfo, fmt: MediaFormat) -> str:
    quality = f".{fmt.height}p" if fmt.height else ""
    return f"{info.title}{quality}.{fmt.ext}"


def ffmpeg_path() -> str | None:
    """Locate ffmpeg, falling back to the usual install spots.

    A frozen build inherits the PATH of whatever launched it, which often
    misses entries a package manager added after that shell started.
    """
    import os
    import shutil
    from pathlib import Path

    found = shutil.which("ffmpeg")
    if found:
        return found

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe",
        Path(os.environ.get("ProgramFiles", "")) / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    winget_packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_packages.is_dir():
        for match in winget_packages.glob("*FFmpeg*/**/bin/ffmpeg.exe"):
            return str(match)

    return None


def mux(video_path, audio_path, output_path, timeout: float = 600.0) -> None:
    """Combine separate video and audio files without re-encoding."""
    import subprocess

    exe = ffmpeg_path()
    if not exe:
        raise RuntimeError("ffmpeg is required to combine video and audio")

    result = subprocess.run(
        [
            exe, "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c", "copy",
            "-map", "0:v:0", "-map", "1:a:0",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:300]}")
