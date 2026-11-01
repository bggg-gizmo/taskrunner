@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Task Runner - Windows EXE Builder

echo.
echo  ================================================================
echo     TASK RUNNER  v1.5.1  -  Windows build - vaporwave edition
 echo  ================================================================
echo.
call "%~dp0scripts\FIND_PYTHON.cmd"
if errorlevel 1 goto :FAILED

echo [1/6] Checking reusable Python dependencies - no virtual environment ...
"%TASKRUNNER_PYTHON_EXE%" "%~dp0scripts\shared_dependencies.py" "%~dp0requirements-build.txt"
if errorlevel 1 goto :FAILED

echo [2/6] Running validation tests ...
"%TASKRUNNER_PYTHON_EXE%" -m pytest tests -q
if errorlevel 1 goto :FAILED

echo [3/6] Checking shared Playwright Chromium browser installation ...
rem This is Playwright's standard Windows user-level browser cache.
rem Other projects using the same Playwright browser revision can reuse it.
if not defined LOCALAPPDATA (
    echo ERROR: Windows LOCALAPPDATA is not available.
    goto :FAILED
)
set "PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\ms-playwright"
"%TASKRUNNER_PYTHON_EXE%" -m playwright install chromium
if errorlevel 1 goto :FAILED

echo [4/6] Building the full Windows GUI executable ...
"%TASKRUNNER_PYTHON_EXE%" -m PyInstaller --noconfirm --clean --windowed --onedir --name "TaskRunner" --version-file "assets\version_info.txt" --icon "assets\task-runner.ico" --add-data "assets;assets" --collect-all playwright --collect-submodules pywinauto --collect-submodules pyautogui --collect-submodules pynput --collect-submodules psutil --collect-submodules bs4 --collect-submodules lxml --hidden-import tzdata --hidden-import tzlocal --hidden-import croniter --hidden-import cv2 --collect-all rapidocr --collect-all onnxruntime --paths "." "launcher.py"
if errorlevel 1 goto :FAILED

echo [5/6] Bundling installed Chromium browser binaries for offline EXE use ...
if not exist "%PLAYWRIGHT_BROWSERS_PATH%" (
    echo ERROR: Shared Chromium browser cache was not created.
    goto :FAILED
)
if not exist "dist\TaskRunner\browser-binaries" mkdir "dist\TaskRunner\browser-binaries"
robocopy "%PLAYWRIGHT_BROWSERS_PATH%" "dist\TaskRunner\browser-binaries" /E /NFL /NDL /NJH /NJS /NC /NS >nul
if errorlevel 8 goto :FAILED

echo [6/6] Validating the packaged executable, GUI imports and browser ...
if not exist "dist\TaskRunner\TaskRunner.exe" goto :FAILED
"dist\TaskRunner\TaskRunner.exe" --self-test --report "%CD%\dist\TaskRunner\windows-self-test.json"
if errorlevel 1 (
    echo The compiled executable could not pass its runtime self-test.
    if exist "dist\TaskRunner\windows-self-test.json" type "dist\TaskRunner\windows-self-test.json"
    goto :FAILED
)
if not exist "dist\TaskRunner\windows-self-test.json" goto :FAILED
if not exist "dist\TaskRunner\browser-binaries" goto :FAILED

echo.
echo SUCCESS: %CD%\dist\TaskRunner\TaskRunner.exe
echo Dependencies were installed into the shared Python user site, NOT .venv.
echo The full dist\TaskRunner directory must remain together.
echo Optional: Run INSTALL_WINDOWS.cmd for Start Menu install and proper uninstaller.
echo Run INSTALL_SCHEDULER.cmd after testing if you want scheduled execution.
echo.
pause
exit /b 0

:FAILED
echo.
echo BUILD FAILED. Read the error output above. No existing build was removed.
pause
exit /b 1
