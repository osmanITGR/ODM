@echo off
REM Fallback installer for ODM - no Inno Setup needed.
REM Installs per-user into %LOCALAPPDATA%\ODM, so it needs no admin rights.
REM Right-click -> Run as administrator only if you want the Chrome policy keys.

setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

set "TARGET=%LOCALAPPDATA%\ODM"
set "APPNAME=ODM"

echo ============================================
echo   ODM - Osman Download Manager   installer
echo ============================================
echo.

if not exist "dist\ODM.exe" (
    echo ERROR: dist\ODM.exe not found.
    echo Build it first:  python -m PyInstaller --clean --noconfirm odm.spec
    pause
    exit /b 1
)

echo Installing to: %TARGET%
if not exist "%TARGET%" mkdir "%TARGET%"
if not exist "%TARGET%\extension" mkdir "%TARGET%\extension"

REM Stop a running copy so the file is not locked.
taskkill /IM ODM.exe /F >nul 2>&1

copy /Y "dist\ODM.exe" "%TARGET%\" >nul
if errorlevel 1 (
    echo ERROR: could not copy ODM.exe - is it still running?
    pause
    exit /b 1
)
xcopy /E /I /Y "extension" "%TARGET%\extension" >nul
copy /Y "README.md" "%TARGET%\" >nul 2>&1

echo Creating shortcuts...
powershell -NoProfile -Command ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "$desktop = $w.CreateShortcut(\"$env:USERPROFILE\Desktop\ODM.lnk\");" ^
  "$desktop.TargetPath = \"%TARGET%\ODM.exe\";" ^
  "$desktop.WorkingDirectory = \"%TARGET%\";" ^
  "$desktop.Description = 'ODM - Osman Download Manager';" ^
  "$desktop.Save();" ^
  "$menu = \"$env:APPDATA\Microsoft\Windows\Start Menu\Programs\ODM.lnk\";" ^
  "$start = $w.CreateShortcut($menu);" ^
  "$start.TargetPath = \"%TARGET%\ODM.exe\";" ^
  "$start.WorkingDirectory = \"%TARGET%\";" ^
  "$start.Description = 'ODM - Osman Download Manager';" ^
  "$start.Save()"

echo Registering in Add/Remove Programs...
set "UNKEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ODM"
reg add "%UNKEY%" /v DisplayName     /t REG_SZ /d "ODM - Osman Download Manager" /f >nul
reg add "%UNKEY%" /v DisplayVersion  /t REG_SZ /d "1.0.0" /f >nul
reg add "%UNKEY%" /v Publisher       /t REG_SZ /d "Osman IT" /f >nul
reg add "%UNKEY%" /v DisplayIcon     /t REG_SZ /d "%TARGET%\ODM.exe" /f >nul
reg add "%UNKEY%" /v InstallLocation /t REG_SZ /d "%TARGET%" /f >nul
reg add "%UNKEY%" /v UninstallString /t REG_SZ /d "\"%TARGET%\uninstall.bat\"" /f >nul
reg add "%UNKEY%" /v NoModify        /t REG_DWORD /d 1 /f >nul
reg add "%UNKEY%" /v NoRepair        /t REG_DWORD /d 1 /f >nul

copy /Y "installer\uninstall.bat" "%TARGET%\" >nul 2>&1

REM Allow sideloaded extensions to stay enabled. Silently skipped without admin.
net session >nul 2>&1
if %errorlevel% equ 0 (
    echo Applying browser extension policy...
    reg add "HKLM\Software\Policies\Google\Chrome\ExtensionSettings\*" /v installation_mode /t REG_SZ /d allowed /f >nul 2>&1
    reg add "HKLM\Software\Policies\Microsoft\Edge\ExtensionSettings\*" /v installation_mode /t REG_SZ /d allowed /f >nul 2>&1
) else (
    echo Skipping browser policy - not running as administrator.
)

echo.
echo ============================================
echo   Installed.
echo ============================================
echo.
echo To finish browser integration:
echo.
echo   1. Open chrome://extensions  (or edge://extensions)
echo   2. Turn on "Developer mode"
echo   3. Click "Load unpacked" and choose:
echo        %TARGET%\extension
echo   4. In ODM: Settings -^> Browser integration -^> Start bridge -^> Copy token
echo   5. Paste the token into the extension popup and Save
echo.
echo Opening the extension folder for you...
start "" "%TARGET%\extension"
echo.
pause
endlocal
