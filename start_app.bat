@echo off
cd /d "%~dp0"
set "SDK_PATH=C:\Programs Files (x86)\MVS\Development\Bin\win64"
set "PATH=%SDK_PATH%;%PATH%"
set "MV_CAM_CTRL_PATH=%SDK_PATH%"
if not exist "%~dp0venv\Scripts\python.exe" (
    exit /b 1
)
set "PORT=7000"
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /R /C:"IPv4 Address" /C:"IPv4"') do (
    set "IP=%%A"
    goto :FOUND_IP
)
:FOUND_IP
set "IP=%IP: =%"
if not defined IP (
    exit /b 1
)
start "Valve Inspection Server" /min cmd /c ""%~dp0venv\Scripts\python.exe" "%~dp0main.py"
timeout /t 5 /nobreak >nul
start "" "http://%IP%:%PORT%"
exit /b