@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "APP_PORT=3000"
set "APP_URL=http://127.0.0.1:3000"

echo.
echo  Keystone - one-click launcher
echo  --------------------------------

if exist "%VENV_PY%" (
    for /f "tokens=2" %%V in ('"%VENV_PY%" --version 2^>^&1') do set "VENV_VERSION=%%V"
    if "!VENV_VERSION:~0,4!"=="3.14" (
        echo Existing environment uses unsupported Python !VENV_VERSION!.
        echo Recreating it with a stable Python version...
        rmdir /s /q ".venv"
    )
)

if not exist "%VENV_PY%" (
    echo [1/3] Creating a local Python environment...
    where py >nul 2>nul
    if errorlevel 1 (
        goto :missing_python
    ) else (
        py -3.13 -m venv .venv
        if errorlevel 1 (
            py -3.12 -m venv .venv
        )
        if errorlevel 1 (
            py -3.11 -m venv .venv
        )
    )
    if not exist "%VENV_PY%" goto :setup_failed
) else (
    echo [1/3] Local Python environment already exists.
)

echo [2/3] Checking dependencies...
"%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :setup_failed

if not exist ".env" (
    echo [3/3] Creating .env from .env.example...
    copy /Y ".env.example" ".env" >nul
    echo.
    echo Add your FalkorDB values to .env, then run this file again.
    echo The browser will still open so you can inspect the interface.
) else (
    echo [3/3] Environment file found.
)

echo Checking whether Keystone is already running...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/ -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto :already_running

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    set "APP_PORT=3001"
    set "APP_URL=http://127.0.0.1:3001"
    echo Port 3000 is occupied. Using %APP_URL% instead.
)
>"%~dp0.keystone_port" echo %APP_PORT%

echo.
echo Starting Keystone at %APP_URL%
start "" "%APP_URL%"
set "PORT=%APP_PORT%"
"%VENV_PY%" app.py
if errorlevel 1 goto :app_failed
exit /b 0

:missing_python
echo.
echo A stable Python 3.11, 3.12, or 3.13 installation was not found.
echo Install Python 3.13 from https://www.python.org/downloads/
echo Make sure "Add Python to PATH" is selected, then run this file again.
pause
exit /b 1

:setup_failed
echo.
echo Setup could not complete. Check your internet connection and Python installation.
pause
exit /b 1

:app_failed
echo.
echo Keystone stopped unexpectedly. Read the error above for details.
pause
exit /b 1

:already_running
echo Keystone is already running at %APP_URL%.
>"%~dp0.keystone_port" echo 3000
start "" "%APP_URL%"
echo You can close this window.
exit /b 0
