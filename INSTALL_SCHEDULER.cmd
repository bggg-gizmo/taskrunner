@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\TaskRunner\TaskRunner.exe" (
    echo TaskRunner.exe not found. First run BUILD_WINDOWS.cmd.
    pause
    exit /b 1
)
"dist\TaskRunner\TaskRunner.exe" --install-scheduler
if errorlevel 1 (
    echo Scheduler registration failed. You can also install it from Task Runner Settings.
    pause
    exit /b 1
)
echo Interactive scheduler installed. Windows must be logged in and unlocked for desktop automation.
pause
exit /b 0
