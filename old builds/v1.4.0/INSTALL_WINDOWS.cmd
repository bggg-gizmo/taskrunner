@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "SCRIPT=%~dp0scripts\install_windows.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
if errorlevel 1 (
 echo INSTALL FAILED - no administrator privileges required.
 pause
 exit /b 1
)
echo INSTALL COMPLETE - Task Runner appears in Windows Start Menu and Installed Apps.
pause
