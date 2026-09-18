"""Command-line front end for the FastDM engine."""

from __future__ import annotations

import argparse
import sys
import threading
import time

from .engine import Download, State


def human_bytes(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def human_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def render(progress, width: int = 32) -> str:
    if progress.total:
        filled = int(width * progress.percent / 100)
        bar = "#" * filled + "-" * (width - filled)
        return (
            f"[{bar}] {progress.percent:5.1f}%  "
            f"{human_bytes(progress.downloaded)}/{human_bytes(progress.total)}  "
            f"{human_bytes(progress.speed)}/s  ETA {human_time(progress.eta)}"
        )
    return f"{human_bytes(progress.downloaded)} downloaded  {human_bytes(progress.speed)}/s"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="odm", description="Segmented file downloader")
    parser.add_argument("url")
    parser.add_argument("-o", "--output", help="output directory", default=".")
    parser.add_argument("-n", "--connections", type=int, default=8)
    parser.add_argument("-f", "--filename", help="override the saved filename")
    parser.add_argument(
        "--no-boost", action="store_true",
        help="disable work stealing (idle connections splitting slow segments)",
    )
    args = parser.parse_args(argv)

    download = Download(
        args.url, args.output, args.connections, args.filename, boost=not args.no_boost
    )
    worker = threading.Thread(target=download.start, daemon=True)
    worker.start()

    try:
        while worker.is_alive():
            if download.progress.state in (State.RUNNING, State.PROBING):
                sys.stdout.write("\r" + render(download.progress).ljust(100))
                sys.stdout.flush()
            time.sleep(0.2)
        sys.stdout.write("\r" + render(download.progress).ljust(100) + "\n")
    except KeyboardInterrupt:
        download.pause()
        print("\nPaused. Re-run the same command to resume.")
        return 130

    if download.progress.state is State.DONE:
        mode = f"{len(download.segments)} connections" if download.segments else "single stream"
        print(f"Saved to {download.target}  ({mode})")
        return 0

    print(f"Failed: {download.progress.error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
