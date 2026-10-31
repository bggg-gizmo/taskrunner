@echo off
rem Select a supported Windows Python installation, not a project virtual environment.
rem Optional override: set TASKRUNNER_PYTHON to the full path of python.exe.
if defined TASKRUNNER_PYTHON_EXE goto :validate
if defined TASKRUNNER_PYTHON (
    set "TASKRUNNER_PYTHON_EXE=%TASKRUNNER_PYTHON%"
    goto :validate
)
where py >nul 2>nul
if errorlevel 1 goto :from_path
for %%V in (3.12 3.11 3.13) do (
    if not defined TASKRUNNER_PYTHON_EXE (
        for /f "delims=" %%I in ('py -%%V -c "import sys; assert sys.version_info[:2] in ((3, 11), (3, 12), (3, 13)) and sys.maxsize.bit_length() == 63 and sys.prefix == sys.base_prefix; print(sys.executable)" 2^>nul') do set "TASKRUNNER_PYTHON_EXE=%%I"
    )
)
if defined TASKRUNNER_PYTHON_EXE goto :validate
:from_path
for /f "delims=" %%I in ('python -c "import sys; assert sys.version_info[:2] in ((3, 11), (3, 12), (3, 13)) and sys.maxsize.bit_length() == 63 and sys.prefix == sys.base_prefix; print(sys.executable)" 2^>nul') do set "TASKRUNNER_PYTHON_EXE=%%I"
if not defined TASKRUNNER_PYTHON_EXE goto :missing
:validate
"%TASKRUNNER_PYTHON_EXE%" -c "import sys; assert sys.version_info[:2] in ((3, 11), (3, 12), (3, 13)) and sys.maxsize.bit_length() == 63 and sys.prefix == sys.base_prefix, 'Requires normal 64-bit Python 3.11-3.13, not a virtual environment'; print('Shared Python:', sys.executable)"
if errorlevel 1 exit /b 1
exit /b 0
:missing
echo ERROR: No supported Python found. Install 64-bit Python 3.11, 3.12, or 3.13.
echo        Python should be available through the Windows py launcher or PATH.
echo        You can also set TASKRUNNER_PYTHON to the full path of python.exe.
exit /b 1
