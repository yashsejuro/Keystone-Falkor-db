@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  Keystone - public MCP connector
 echo --------------------------------

where cloudflared >nul 2>nul
if errorlevel 1 goto :missing_cloudflared

if not exist ".venv\Scripts\python.exe" (
    echo Run run_keystone.bat first so the local app is installed.
    pause
    exit /b 1
)

start "Keystone" cmd /c "call run_keystone.bat"
set "APP_PORT=3000"
echo Waiting for Keystone to become reachable ...
for /l %%N in (1,1,30) do (
    if exist ".keystone_port" set /p APP_PORT=<".keystone_port"
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:!APP_PORT!/ -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
    if not errorlevel 1 goto :server_ready
    echo   Still starting... (%%N/30)
    timeout /t 1 /nobreak >nul
)
echo.
echo Keystone did not respond on port 3000. Check the Keystone window for its error.
pause
exit /b 1

:server_ready
echo Keystone is ready.
echo Local app: http://127.0.0.1:!APP_PORT!
echo.
echo WAIT FOR THIS LINE: Your quick Tunnel has been created!
echo Then copy the printed HTTPS address and add /mcp in Claude.
echo Example: https://your-name.trycloudflare.com/mcp
echo Keep this window open while Claude uses Keystone.
echo.
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:!APP_PORT!
exit /b 0

:missing_cloudflared
echo.
echo cloudflared is required for a public HTTPS MCP URL.
echo Install it once from:
echo https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
echo.
echo Then run this file again.
pause
exit /b 1
