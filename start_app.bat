@echo off
echo Starting Audio Transcriber Desktop App...
echo.

:: ========================================
:: CLEANUP: Kill any orphaned processes from previous runs
:: This prevents port conflicts on 3000 and 8000
:: ========================================
echo Cleaning up any leftover processes...

:: Kill anything on port 3000 (Next.js)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Kill anything on port 8000 (FastAPI)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo Cleanup done.
echo.

:: Navigate to the desktop wrapper
cd desktop_app

echo ====================================================
echo Launching the Desktop Application...
echo The backend and frontend servers are starting automatically.
echo This window will stay open to show any logs.
echo Closing the app window will close this terminal.
echo ====================================================
echo.

:: Start Electron App
call cmd /c "npm start"
