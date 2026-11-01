@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Task Runner - Shared Dependency Checker
echo Checking Python and packages shared with your future programs...
call "%~dp0scripts\FIND_PYTHON.cmd"
if errorlevel 1 goto :FAILED
"%TASKRUNNER_PYTHON_EXE%" "%~dp0scripts\shared_dependencies.py" "%~dp0requirements-build.txt"
if errorlevel 1 goto :FAILED
if not defined LOCALAPPDATA goto :FAILED
set "PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\ms-playwright"
"%TASKRUNNER_PYTHON_EXE%" -m playwright install chromium
if errorlevel 1 goto :FAILED
echo.
echo All Task Runner dependencies are available from the shared Python installation.
pause
exit /b 0
:FAILED
echo.
echo Dependency check or installation failed. See the output above.
pause
exit /b 1
