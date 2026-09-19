"""Check GitHub for a newer release, and install it.

People install ODM from a GitHub release and then never hear about the next
one, so a fix only reaches whoever happens to look. This checks on launch,
quietly, and offers the update rather than applying it unasked.

The download uses ODM's own engine: the same segmented transfer as any other
file, and no second downloader to maintain.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__

LATEST_RELEASE_API = "https://api.github.com/repos/osmanITGR/ODM/releases/latest"
RELEASES_PAGE = "https://github.com/osmanITGR/ODM/releases/latest"

# The asset a Windows install should fetch.
WINDOWS_ASSET = "ODM.exe"


@dataclass
class Release:
    """A published release, as far as the updater cares."""

    version: str
    tag: str
    notes: str
    download_url: str | None
    size: int | None

    @property
    def is_newer(self) -> bool:
        return _compare(self.version, __version__) > 0


def _parse_version(raw: str) -> tuple[int, ...]:
    """Turn 'v1.3.1' into (1, 3, 1), ignoring anything non-numeric."""
    cleaned = raw.strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for piece in cleaned.split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _compare(left: str, right: str) -> int:
    """-1, 0 or 1, comparing two version strings by their numbers."""
    a, b = _parse_version(left), _parse_version(right)
    # Pad so 1.3 and 1.3.0 compare equal rather than by length.
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return (a > b) - (a < b)


def should_check(interval_hours: float = 24.0) -> bool:
    """Whether enough time has passed since the last automatic check.

    GitHub allows 60 unauthenticated calls an hour per address, shared by
    everyone behind it. Checking on every launch would spend that on people
    who restart often and leave offices and cafes hitting the limit, so the
    automatic check is daily. The Settings button ignores this.
    """
    stamp = _stamp_file()
    try:
        last = float(stamp.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (time.time() - last) >= interval_hours * 3600


def note_checked() -> None:
    """Record that an automatic check just happened."""
    try:
        stamp = _stamp_file()
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        # Losing the stamp only means checking again sooner.
        pass


def _stamp_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "ODM" / "last-update-check"


def check(timeout: float = 10.0) -> Release | None:
    """Ask GitHub for the newest release.

    Returns None when the check fails for any reason — no internet, a rate
    limit, a malformed response. An update notice is a convenience, and
    someone offline should see nothing rather than an error they did not ask
    for.
    """
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "User-Agent": f"ODM/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None

    tag = data.get("tag_name") or ""
    if not tag:
        return None

    download_url = None
    size = None
    for asset in data.get("assets", []):
        if asset.get("name") == WINDOWS_ASSET:
            download_url = asset.get("browser_download_url")
            size = asset.get("size")
            break

    return Release(
        version=tag.lstrip("vV"),
        tag=tag,
        notes=data.get("body") or "",
        download_url=download_url,
        size=size,
    )


def summarise(notes: str, limit: int = 400) -> str:
    """Condense release notes into something that fits a dialog.

    Release notes are written for the download page, with tables and install
    instructions. Only the bullet points say what changed.
    """
    lines = []
    for raw in notes.splitlines():
        line = raw.strip()
        if not line.startswith(("- ", "* ", "• ")):
            continue
        # Strip the markdown that would show as literal characters.
        text = line[2:].replace("**", "").replace("`", "").strip()
        if text:
            lines.append(f"• {text}")

    summary = "\n".join(lines)
    if not summary:
        return ""
    return summary if len(summary) <= limit else summary[:limit].rsplit("\n", 1)[0]


def install(downloaded: Path) -> bool:
    """Replace the running executable with a freshly downloaded one.

    A running exe cannot overwrite itself, so the swap is handed to a detached
    shell that waits for this process to exit — the same approach the
    uninstaller uses.
    """
    if not downloaded.is_file():
        return False

    target = Path(sys.executable).resolve()
    if not getattr(sys, "frozen", False):
        # Running from source: there is no exe to replace.
        return False

    script = (
        f'timeout /t 3 /nobreak >nul & '
        f'move /y "{downloaded}" "{target}" >nul & '
        f'start "" "{target}"'
    )
    try:
        subprocess.Popen(["cmd", "/c", script], **_no_window())
        return True
    except OSError:
        return False


def _no_window() -> dict:
    """Keep the helper shell from flashing a console window."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def download_dir() -> Path:
    """Somewhere to put the new exe until it replaces the old one."""
    return Path(tempfile.gettempdir())
