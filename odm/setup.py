"""First-run self installation.

The shipped ODM.exe is both the installer and the application. When it is
launched from anywhere other than its installed location it offers to install
itself: copy the executable into %LOCALAPPDATA%, unpack the browser extension,
create shortcuts, and register for Add/Remove Programs. Per-user paths are used
throughout so no administrator prompt is needed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import winreg
from pathlib import Path

from . import __version__

APP_NAME = "ODM"
DISPLAY_NAME = "ODM - Osman Download Manager"
PUBLISHER = "Osman IT"
# Shown in Add/Remove Programs; read from one place so it cannot drift.
VERSION = __version__
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
TARGET_EXE = INSTALL_DIR / "ODM.exe"
EXTENSION_DIR = INSTALL_DIR / "extension"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def current_exe() -> Path:
    return Path(sys.executable).resolve()


def is_installed() -> bool:
    """True when this process is the copy living in the install directory."""
    if not is_frozen():
        return True  # running from source; never offer to install
    try:
        return current_exe() == TARGET_EXE.resolve()
    except OSError:
        return False


def _no_window() -> dict:
    """Keep helper processes from flashing a console window."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}


def _copy_extension() -> None:
    """Unpack the bundled extension next to the installed executable."""
    source = getattr(sys, "_MEIPASS", None)
    if source is None:
        source = Path(__file__).resolve().parent.parent / "extension"
    else:
        source = Path(source) / "extension"
    if not Path(source).is_dir():
        return
    if EXTENSION_DIR.exists():
        shutil.rmtree(EXTENSION_DIR, ignore_errors=True)
    shutil.copytree(source, EXTENSION_DIR)


def _make_shortcut(link: Path, target: Path, description: str) -> None:
    """Create a .lnk via PowerShell's WScript.Shell COM object."""
    link.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath = '{target}';"
        "$s.WorkingDirectory = '{cwd}';"
        "$s.Description = '{desc}';"
        "$s.Save()"
    ).format(
        link=str(link).replace("'", "''"),
        target=str(target).replace("'", "''"),
        cwd=str(target.parent).replace("'", "''"),
        desc=description.replace("'", "''"),
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        **_no_window(),
    )


def _register_uninstall() -> None:
    size_kb = 0
    try:
        size_kb = TARGET_EXE.stat().st_size // 1024
    except OSError:
        pass
    values = {
        "DisplayName": DISPLAY_NAME,
        "DisplayVersion": VERSION,
        "Publisher": PUBLISHER,
        "DisplayIcon": str(TARGET_EXE),
        "InstallLocation": str(INSTALL_DIR),
        "UninstallString": f'"{TARGET_EXE}" --uninstall',
    }
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name in ("NoModify", "NoRepair"):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1)
        if size_kb:
            winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)


def set_run_at_startup(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{TARGET_EXE}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def desktop_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"


def start_menu_dir() -> Path:
    return (
        Path(os.environ.get("APPDATA", Path.home()))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )


def install(desktop_icon: bool = True, run_at_startup: bool = False) -> Path:
    """Install this executable into the per-user install directory.

    Returns the path of the installed executable. Raises OSError on failure.
    """
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    source = current_exe()
    if source != TARGET_EXE:
        # A previously installed copy may be running; move it aside so the
        # replacement can be written, then let Windows clean it up on reboot.
        if TARGET_EXE.exists():
            stale = TARGET_EXE.with_suffix(".exe.old")
            stale.unlink(missing_ok=True)
            try:
                TARGET_EXE.rename(stale)
            except OSError:
                pass
        shutil.copy2(source, TARGET_EXE)

    _copy_extension()

    _make_shortcut(start_menu_dir() / f"{APP_NAME}.lnk", TARGET_EXE, DISPLAY_NAME)
    if desktop_icon:
        _make_shortcut(desktop_dir() / f"{APP_NAME}.lnk", TARGET_EXE, DISPLAY_NAME)

    _register_uninstall()
    set_run_at_startup(run_at_startup)
    return TARGET_EXE


def uninstall() -> None:
    """Remove shortcuts and registry entries, then delete the install dir."""
    for link in (desktop_dir() / f"{APP_NAME}.lnk", start_menu_dir() / f"{APP_NAME}.lnk"):
        try:
            link.unlink(missing_ok=True)
        except OSError:
            pass

    set_run_at_startup(False)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass

    # The running executable lives inside the directory being removed, so the
    # deletion is handed to a detached shell that waits for this process to exit.
    subprocess.Popen(
        [
            "cmd",
            "/c",
            f'timeout /t 3 /nobreak >nul & rd /S /Q "{INSTALL_DIR}"',
        ],
        **_no_window(),
    )


def launch_installed(copy_token: bool = False) -> None:
    """Start the installed copy and let this one exit.

    `copy_token` is passed straight after a first install, so the pairing
    token is on the clipboard by the time the extension popup asks for it.
    """
    command = [str(TARGET_EXE)]
    if copy_token:
        command.append("--copy-token")
    subprocess.Popen(command, cwd=str(INSTALL_DIR), close_fds=True)


def open_extension_folder() -> None:
    if EXTENSION_DIR.is_dir():
        os.startfile(EXTENSION_DIR)  # noqa: S606 - opening a local folder


# Browser integration helpers ------------------------------------------------
#
# Chrome removed silent extension installs in 2018 because malware used them,
# so the Load unpacked step cannot be automated. Everything around it can be:
# finding the browser, opening its extensions page, and putting the folder on
# the clipboard so the file picker can be filled with one paste.

# Each browser's extensions page, and where its executable usually lives.
_BROWSERS = (
    ("Chrome", "chrome://extensions", ("Google", "Chrome", "Application", "chrome.exe")),
    ("Edge", "edge://extensions", ("Microsoft", "Edge", "Application", "msedge.exe")),
    ("Brave", "brave://extensions",
     ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
    ("Opera", "opera://extensions", ("Opera", "launcher.exe")),
    ("Vivaldi", "vivaldi://extensions", ("Vivaldi", "Application", "vivaldi.exe")),
)


def _browser_roots() -> list[Path]:
    """Directories browsers install themselves into, per-user and system-wide."""
    names = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
    return [Path(os.environ[n]) for n in names if os.environ.get(n)]


def find_browsers() -> list[tuple[str, str, Path]]:
    """Return (name, extensions URL, executable) for each browser installed.

    Two sources, because neither alone is complete: the registry lists what
    Windows knows about wherever it was installed, and the usual directories
    catch a browser that never registered itself. Results are ordered so the
    browser the user is actually in comes first — whichever is running, then
    their default, then the rest.
    """
    found: list[tuple[str, str, Path]] = []
    seen: set[str] = set()

    def remember(name: str, url: str, executable: Path) -> None:
        # The same browser can appear in both sources; keep the first.
        if name in seen:
            return
        seen.add(name)
        found.append((name, url, executable))

    for name, url, executable in _registered_browsers():
        remember(name, url, executable)

    for name, url, parts in _BROWSERS:
        if name in seen:
            continue
        for root in _browser_roots():
            candidate = root.joinpath(*parts)
            if candidate.is_file():
                remember(name, url, candidate)
                break

    running = _running_browser_names()
    default = _default_browser_name()

    def rank(browser: tuple[str, str, Path]) -> tuple[int, int]:
        name = browser[0]
        # Running beats default, default beats merely installed; ties keep
        # the order above so the list does not shuffle between launches.
        return (
            0 if name in running else 1,
            0 if name == default else 1,
        )

    return sorted(found, key=rank)


def _registered_browsers() -> list[tuple[str, str, Path]]:
    """Browsers Windows has on record, wherever they were installed.

    StartMenuInternet is where every browser registers itself, so this finds
    one installed to a second drive or a custom folder that the fixed paths
    would miss.
    """
    found = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            clients = winreg.OpenKey(root, r"SOFTWARE\Clients\StartMenuInternet")
        except OSError:
            continue

        with clients:
            index = 0
            while True:
                try:
                    entry = winreg.EnumKey(clients, index)
                except OSError:
                    break
                index += 1

                known = _match_browser(entry)
                if known is None:
                    continue

                try:
                    with winreg.OpenKey(
                        clients, rf"{entry}\shell\open\command"
                    ) as command:
                        raw, _ = winreg.QueryValueEx(command, "")
                except OSError:
                    continue

                # The command is a quoted path, sometimes with arguments.
                executable = Path(raw.strip().strip('"').split('" ')[0].strip('"'))
                if executable.is_file():
                    name, url = known
                    found.append((name, url, executable))
    return found


def _match_browser(registry_name: str) -> "tuple[str, str] | None":
    """Map a registry entry to one of the browsers this extension supports.

    Firefox is deliberately absent: it uses a different extension format, and
    offering a button that cannot work would be worse than leaving it out.
    """
    lowered = registry_name.lower()
    for name, url, _ in _BROWSERS:
        if name.lower() in lowered:
            return name, url
    return None


def _running_browser_names() -> set[str]:
    """Names of the browsers with a window open right now.

    Matched on the process name rather than the path, since a browser can be
    installed in several places and the running one is what matters.
    """
    processes = {
        "chrome": "Chrome",
        "msedge": "Edge",
        "brave": "Brave",
        "opera": "Opera",
        "vivaldi": "Vivaldi",
    }
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-Process " + ",".join(processes)
                + " -ErrorAction SilentlyContinue"
                " | Select-Object -ExpandProperty ProcessName -Unique",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            **_no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        return set()

    return {
        processes[line.strip().lower()]
        for line in result.stdout.splitlines()
        if line.strip().lower() in processes
    }


def _default_browser_name() -> str | None:
    """The browser Windows opens https:// links with, if it is one we know."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations"
            r"\UrlAssociations\https\UserChoice",
        )
        with key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
    except OSError:
        return None

    prog_id = prog_id.lower()
    for fragment, name in (
        ("chrome", "Chrome"),
        ("msedge", "Edge"),
        ("edge", "Edge"),
        ("brave", "Brave"),
        ("opera", "Opera"),
        ("vivaldi", "Vivaldi"),
    ):
        if fragment in prog_id:
            return name
    return None


def open_extensions_page(browser: tuple[str, str, Path]) -> bool:
    """Open a browser at its extensions page.

    The URL is passed to that browser's own executable rather than to the
    default handler, since chrome:// and edge:// mean nothing to the shell.
    """
    _, url, executable = browser
    try:
        subprocess.Popen([str(executable), url], close_fds=True)
        return True
    except OSError:
        return False


def browser_icon(executable: Path, size: int = 20) -> "Path | None":
    """Extract a browser's own icon, for the buttons that open it.

    Taken from the executable rather than bundled, so every browser is shown
    with its real icon and nothing has to be shipped or kept up to date.
    Cached beside the install, since extraction spawns PowerShell.
    """
    cache = INSTALL_DIR / "icons"
    target = cache / f"{executable.stem}-{size}.png"
    if target.is_file():
        return target

    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    # ExtractAssociatedIcon gives 32x32; the redraw is what makes it sharp at
    # button size rather than letting the widget scale it.
    script = (
        "Add-Type -AssemblyName System.Drawing;"
        f"$icon = [System.Drawing.Icon]::ExtractAssociatedIcon('{executable}');"
        f"$bitmap = New-Object System.Drawing.Bitmap {size},{size};"
        "$graphics = [System.Drawing.Graphics]::FromImage($bitmap);"
        "$graphics.InterpolationMode = 'HighQualityBicubic';"
        f"$graphics.DrawIcon($icon, (New-Object System.Drawing.Rectangle 0,0,{size},{size}));"
        f"$bitmap.Save('{target}', [System.Drawing.Imaging.ImageFormat]::Png);"
        "$graphics.Dispose(); $bitmap.Dispose(); $icon.Dispose()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=15,
            **_no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        return None

    return target if target.is_file() else None


def copy_to_clipboard(text: str) -> bool:
    """Put text on the clipboard without needing a Tk window."""
    try:
        subprocess.run(
            ["clip"], input=text.encode("utf-16-le"), check=True, **_no_window()
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
