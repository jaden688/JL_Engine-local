param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostAddress = "127.0.0.1"
$HealthUrl = "http://$HostAddress`:$Port/health"
$DocsUrl = "http://$HostAddress`:$Port"
$PythonPath = Join-Path $Root "src"

function Test-JulianHealth {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            return $true
        }
    } catch {
    }
    return $false
}

function Wait-JulianHealth {
    param(
        [string]$Url,
        [int]$Retries = 20,
        [int]$DelayMs = 500
    )
    for ($i = 0; $i -lt $Retries; $i++) {
        if (Test-JulianHealth -Url $Url) {
            return $true
        }
        Start-Sleep -Milliseconds $DelayMs
    }
    return $false
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python was not found on PATH." -ForegroundColor Red
    exit 1
}

if (Test-JulianHealth -Url $HealthUrl) {
    Write-Host "Julian MetaMorph is already running on port $Port." -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process $DocsUrl | Out-Null
    }
    exit 0
}

$Command = @(
    '$env:PYTHONPATH=' + "'" + $PythonPath + "'"
    'Set-Location ' + "'" + $Root + "'"
    'python -m julian_metamorph.cli serve --host ' + $HostAddress + ' --port ' + $Port
) -join '; '

Start-Process powershell `
    -WorkingDirectory $Root `
    -ArgumentList @(
        '-NoExit',
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-Command', $Command
    ) | Out-Null

if (Wait-JulianHealth -Url $HealthUrl) {
    Write-Host "Julian MetaMorph is running at $DocsUrl" -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process $DocsUrl | Out-Null
    }
    exit 0
}

Write-Host "Julian MetaMorph did not come online in time. Check the service window." -ForegroundColor Yellow
exit 1

