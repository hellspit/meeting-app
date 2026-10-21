@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing Python environment. Follow the setup steps in README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m src.main %*
if errorlevel 1 pause
