@echo off
REM Removes an ODM installation made by install.bat.

setlocal
set "TARGET=%LOCALAPPDATA%\ODM"

echo Uninstalling ODM...
echo.

taskkill /IM ODM.exe /F >nul 2>&1

del /Q "%USERPROFILE%\Desktop\ODM.lnk" >nul 2>&1
del /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\ODM.lnk" >nul 2>&1

reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ODM" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v ODM /f >nul 2>&1

REM The batch file lives inside the folder it is deleting, so hand the job to
REM a detached cmd that removes the folder after this script has exited.
start "" /min cmd /c "timeout /t 2 /nobreak >nul & rd /S /Q ""%TARGET%"""

echo Removed.
echo.
echo Note: the browser extension must be removed from chrome://extensions
echo separately, since the browser owns it once loaded.
echo.
pause
endlocal
