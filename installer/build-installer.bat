@echo off
REM Builds ODM.exe and then wraps it in ODM-Setup-<version>.exe.
REM Usage:  installer\build-installer.bat

setlocal
cd /d "%~dp0\.."

echo === Step 1/2: building ODM.exe with PyInstaller ===
python -m PyInstaller --clean --noconfirm odm.spec
if errorlevel 1 (
    echo.
    echo PyInstaller failed. Run "pip install pyinstaller" if it is missing.
    exit /b 1
)

if not exist "dist\ODM.exe" (
    echo.
    echo dist\ODM.exe was not produced. Aborting.
    exit /b 1
)

echo.
echo === Step 2/2: compiling the installer with Inno Setup ===

set "ISCC="
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
) do if exist %%P set "ISCC=%%~P"

if not defined ISCC (
    where iscc >nul 2>&1 && for /f "delims=" %%I in ('where iscc') do set "ISCC=%%I"
)

if not defined ISCC (
    echo.
    echo Inno Setup was not found. Install it with:
    echo     winget install JRSoftware.InnoSetup
    echo then run this script again.
    exit /b 1
)

"%ISCC%" "installer\odm.iss"
if errorlevel 1 (
    echo.
    echo Inno Setup compilation failed.
    exit /b 1
)

echo.
echo Done. The installer is in installer\output\
dir /b "installer\output\*.exe"
endlocal
