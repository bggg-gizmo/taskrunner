@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
call "%~dp0scripts\FIND_PYTHON.cmd"
if errorlevel 1 goto :FAILED
"%TASKRUNNER_PYTHON_EXE%" "%~dp0scripts\capture_ui_windows.py"
if errorlevel 1 goto :FAILED
echo.
echo Actual Windows Qt screenshots saved in ui-shots
pause
exit /b 0
:FAILED
echo Actual Qt screenshot capture FAILED. Check the errors above.
pause
exit /b 1
