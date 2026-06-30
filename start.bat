@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Project environment is missing. Run setup.bat first.
    pause
    exit /b 1
)

echo Smart Billing System is starting...
echo Open http://127.0.0.1:5000 in your browser.
".venv\Scripts\python.exe" -m flask --app app run
pause
