@echo off
setlocal
cd /d "%~dp0"

if not exist "node_modules" (
  echo [Error] Frontend dependencies are missing. Run npm install first.
  pause
  exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [Error] Backend environment is not ready.
  echo Double-click setup-backend.bat once, then run this file again.
  pause
  exit /b 1
)

echo Starting the frontend and API in separate windows...

rem Keep backend console open after startup; use cmd /k so it remains visible for logs and errors.
start "Nature Insight API" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

rem Frontend stays open too for dev server output.
start "Nature Insight Frontend" /D "%~dp0" cmd /k "npm.cmd run dev"

timeout /t 3 /nobreak >nul
start "" "http://localhost:5173"

echo Frontend: http://localhost:5173
echo API docs: http://127.0.0.1:8000/docs
echo.
echo If the backend or frontend console closes unexpectedly, check the window title above for logs.
endlocal
