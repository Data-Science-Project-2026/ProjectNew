@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [Error] Python was not found. Install Python 3.10 or newer, then run this file again.
  pause
  exit /b 1
)

echo Creating the backend environment...
python -m venv backend\.venv
if errorlevel 1 (
  echo [Error] Could not create the backend environment.
  pause
  exit /b 1
)

echo Installing backend dependencies...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 (
  echo [Error] Dependency installation failed. Check your network connection and try again.
  pause
  exit /b 1
)

echo Backend setup is complete. You can now double-click start-all.bat.
pause
endlocal
