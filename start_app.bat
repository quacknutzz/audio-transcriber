@echo off
echo Starting Audio Transcriber Desktop App...

:: Navigate to the desktop wrapper
cd desktop_app

echo.
echo ====================================================
echo Launching the Desktop Application...
echo The backend and frontend servers are starting automatically.
echo This window will stay open to show any logs.
echo Closing the app window will close this terminal.
echo ====================================================
echo.

:: Start Electron App
call cmd /c "npm start"
