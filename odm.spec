# PyInstaller build spec for ODM (com.osmanit.odm)
import os
import customtkinter

ctk_dir = os.path.dirname(customtkinter.__file__)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        (ctk_dir, 'customtkinter/'),
        ('odm/icons', 'icons'),
        # Carried inside the exe so first-run setup can unpack it.
        ('extension', 'extension'),
    ],
    hiddenimports=['PIL._tkinter_finder'],
    hookspath=[],
    runtime_hooks=[],
    # yt-dlp pulls in every site extractor; keeping it out of the bundle saves
    # ~25 MB. The app degrades to plain file downloads when it is absent.
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'pytest', 'setuptools'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ODM',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon='odm/icons/app.ico',
    version='version_info.txt',
)
