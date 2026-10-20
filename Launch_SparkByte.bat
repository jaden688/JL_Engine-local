@echo off
setlocal
cd /d "%~dp0"
set "SPARKBYTE_HOST=127.0.0.1"
set "SPARKBYTE_PORT=8081"
set "SPARKBYTE_LAUNCH_BROWSER=0"
set "SPARKBYTE_SKIP_PKG_INSTANTIATE=1"
set "SPARKBYTE_UI=http://127.0.0.1:8081/"
echo === SparkByte / JL Engine ===
echo Root: %CD%
echo UI: %SPARKBYTE_UI%
powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='%SPARKBYTE_UI%'; function Test-Jlos { try { $h=Invoke-WebRequest -UseBasicParsing ($u+'health') -TimeoutSec 2; $p=Invoke-WebRequest -UseBasicParsing $u -TimeoutSec 2; return $h.StatusCode -eq 200 -and $p.Content -match '<title>JL_OS // SPARKBYTE</title>' } catch { return $false } }; if (Test-Jlos) { Start-Process $u; exit 0 }; Start-Process -FilePath 'C:\Users\J_lin\.julia\juliaup\julia-1.12.6+0.x64.w64.mingw32\bin\julia.exe' -ArgumentList '--project=.','sparkbyte.jl' -WorkingDirectory '%CD%'; for ($i=0; $i -lt 180; $i++) { Start-Sleep -Seconds 2; if (Test-Jlos) { Start-Process $u; exit 0 } }; Write-Error 'JL_OS did not become healthy on port 8081'; exit 1"
if errorlevel 1 (
    echo SparkByte failed to become healthy. Check the Julia window.
    pause
    exit /b 1
)
echo Opened the canonical BYTE UI: %SPARKBYTE_UI%
endlocal