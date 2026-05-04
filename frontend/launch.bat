@echo off
:: =============================================
:: EgerBot — Frontend Launcher
:: Starts a proper local web server so the
:: browser can call the Flask backend without
:: CORS file:// errors.
:: =============================================

echo.
echo  ==========================================
echo   EgerBot Frontend Server
echo  ==========================================
echo.
echo  Starting local server at http://localhost:8080
echo  Your browser will open automatically.
echo.
echo  Keep this window open while using EgerBot.
echo  Press Ctrl+C to stop.
echo.

cd /d "%~dp0"

where python3 >nul 2>&1
if %errorlevel% == 0 (
    python3 serve.py
) else (
    python serve.py
)
