@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\TaskRunner\TaskRunner.exe" (
    echo TaskRunner.exe not found. First run BUILD_WINDOWS.cmd.
    pause
    exit /b 1
)
"dist\TaskRunner\TaskRunner.exe" --remove-scheduler
if errorlevel 1 (pause & exit /b 1)
echo Scheduler removed. Stored jobs are not deleted.
pause
exit /b 0
