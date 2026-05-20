@echo off
setlocal
cd /d "%~dp0"
title Notes Viewer

echo =====================================
echo   Notes Viewer
echo =====================================
echo.

:: Verify Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found.
    echo.
    echo   Download Python 3 from https://www.python.org/downloads/
    echo   During install, check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:: Kill any existing instance on port 8765
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8765"') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Start the server backgrounded in this console (window-close kills it)
start /b "" python server.py

:: Wait for the server to bind, then open the browser
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765

echo   Running at http://127.0.0.1:8765
echo   Close this window to stop the server.
echo =====================================
echo.

:: Keep this window alive — closing it terminates the server
:wait
timeout /t 30 /nobreak >nul
goto wait
