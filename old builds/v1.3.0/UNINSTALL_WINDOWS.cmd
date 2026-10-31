@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "SCRIPT=%~dp0uninstall_windows.ps1"
if not exist "%SCRIPT%" set "SCRIPT=%~dp0scripts\uninstall_windows.ps1"
set "STAGED=%TEMP%\TaskRunnerUninstall-%RANDOM%%RANDOM%.ps1"
copy /Y "%SCRIPT%" "%STAGED%" >nul
if errorlevel 1 goto :failed
cd /d "%TEMP%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STAGED%" %*
set "EXITCODE=%ERRORLEVEL%"
del /Q "%STAGED%" >nul 2>nul
if not "%EXITCODE%"=="0" goto :failed
echo UNINSTALL COMPLETE.
pause
exit /b 0
:failed
echo UNINSTALL FAILED - see the error above.
pause
exit /b 1
