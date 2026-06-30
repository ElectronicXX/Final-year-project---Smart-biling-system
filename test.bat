@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Project environment is missing. Run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m unittest discover -s tests -v
pause
