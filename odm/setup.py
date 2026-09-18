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

APP_NAME = "ODM"
DISPLAY_NAME = "ODM - Osman Download Manager"
PUBLISHER = "Osman IT"
VERSION = "1.0.0"
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


def launch_installed() -> None:
    """Start the installed copy and let this one exit."""
    subprocess.Popen([str(TARGET_EXE)], cwd=str(INSTALL_DIR), close_fds=True)


def open_extension_folder() -> None:
    if EXTENSION_DIR.is_dir():
        os.startfile(EXTENSION_DIR)  # noqa: S606 - opening a local folder
