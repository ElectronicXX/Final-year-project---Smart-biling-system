@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if not exist "%PYTHON%" (
    echo Python 3.12 is not installed.
    echo Install it with: winget install --id Python.Python.3.12 --exact
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    "%PYTHON%" -m venv .venv
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :error

echo.
echo Setup and tests completed successfully.
pause
exit /b 0

:error
echo.
echo Setup failed. Review the error above.
pause
exit /b 1
