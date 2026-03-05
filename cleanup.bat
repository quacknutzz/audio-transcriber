@echo off
echo Stopping all Audio Transcriber processes...

taskkill /F /IM python.exe
taskkill /F /IM node.exe

echo.
echo All processes stopped. You can now run start_app.bat again.
pause
