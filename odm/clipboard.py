"""Clipboard watcher that spots downloadable links."""

from __future__ import annotations

import re
import threading
import time
from urllib.parse import urlsplit

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Extensions worth offering to download; pages and scripts are ignored.
INTERESTING = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".img",
    ".exe", ".msi", ".apk", ".dmg", ".deb", ".rpm", ".appimage",
    ".pdf", ".epub", ".mobi", ".djvu",
    ".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus",
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".wmv",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
    ".bin", ".dat", ".pkg", ".jar", ".whl", ".torrent",
}


def looks_downloadable(url: str) -> bool:
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return False
    if not path or path.endswith("/"):
        return False
    for ext in INTERESTING:
        if path.endswith(ext):
            return True
    return False


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    seen: list[str] = []
    for match in URL_RE.findall(text):
        cleaned = match.rstrip(".,);]}”’")
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


class ClipboardMonitor:
    """Polls the clipboard and calls `on_url` for each new downloadable link."""

    def __init__(self, on_url, interval: float = 0.8, filter_extensions: bool = True):
        self.on_url = on_url
        self.interval = interval
        self.filter_extensions = filter_extensions
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_text = ""
        self._offered: set[str] = set()

    def _read_clipboard(self) -> str:
        try:
            import tkinter

            root = tkinter._default_root
            if root is None:
                return ""
            return root.clipboard_get()
        except Exception:
            return ""

    def _loop(self) -> None:
        while not self._stop.is_set():
            text = self._read_clipboard()
            if text and text != self._last_text:
                self._last_text = text
                for url in extract_urls(text):
                    if url in self._offered:
                        continue
                    if self.filter_extensions and not looks_downloadable(url):
                        continue
                    self._offered.add(url)
                    try:
                        self.on_url(url)
                    except Exception:
                        pass
            self._stop.wait(self.interval)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def forget(self, url: str) -> None:
        self._offered.discard(url)
