@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
call "%~dp0scripts\FIND_PYTHON.cmd"
if errorlevel 1 goto :FAILED
"%TASKRUNNER_PYTHON_EXE%" "%~dp0scripts\shared_dependencies.py" "%~dp0requirements.txt"
if errorlevel 1 goto :FAILED
if not defined LOCALAPPDATA goto :FAILED
set "PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\ms-playwright"
"%TASKRUNNER_PYTHON_EXE%" -m playwright install chromium
if errorlevel 1 goto :FAILED
"%TASKRUNNER_PYTHON_EXE%" -m task_runner %*
exit /b %ERRORLEVEL%
:FAILED
echo Could not start Task Runner. See the error above.
pause
exit /b 1
