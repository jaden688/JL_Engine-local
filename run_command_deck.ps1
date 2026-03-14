$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pythonPathParts = @($root, (Join-Path $root "src"))
if ($env:PYTHONPATH) {
    $pythonPathParts += $env:PYTHONPATH
}
$env:PYTHONPATH = ($pythonPathParts -join [IO.Path]::PathSeparator)

$serviceConfigPath = Join-Path $root "jl_engine_core\gemini_config.json"
$configuredUrl = [string]$env:JL_PLATFORM_API_URL
if (-not $configuredUrl -and (Test-Path $serviceConfigPath)) {
    try {
        $rawConfig = Get-Content $serviceConfigPath -Raw
        if ($rawConfig) {
            $loaded = $rawConfig | ConvertFrom-Json
            if ($loaded -and ($loaded.PSObject.Properties.Name -contains "platform_api_url")) {
                $configuredUrl = [string]$loaded.platform_api_url
            }
        }
    } catch {
        $configuredUrl = ""
    }
}
if (-not $configuredUrl) {
    $defaultHost = if ($env:JL_PLATFORM_HOST) { [string]$env:JL_PLATFORM_HOST } else { "127.0.0.1" }
    $defaultPort = if ($env:JL_PLATFORM_PORT) { [string]$env:JL_PLATFORM_PORT } else { "8000" }
    $configuredUrl = "http://$defaultHost`:$defaultPort"
}
if ($configuredUrl -notmatch "^[a-z][a-z0-9+\.-]*://") {
    $configuredUrl = "http://$configuredUrl"
}

$uri = [Uri]$configuredUrl
$scheme = if ($uri.Scheme) { $uri.Scheme } else { "http" }
$jlHost = if ($uri.Host) { $uri.Host } else { "127.0.0.1" }
$jlPort = if ($uri.Port -gt 0) { [int]$uri.Port } else { 8000 }
$jlBaseUrl = "{0}://{1}:{2}" -f $scheme, $jlHost, $jlPort
$uiPath = if ($env:JL_PLATFORM_UI_PATH) { [string]$env:JL_PLATFORM_UI_PATH } else { "/ui/" }
if (-not $uiPath.StartsWith("/")) {
    $uiPath = "/$uiPath"
}
$jlUiUrl = "{0}{1}" -f $jlBaseUrl, $uiPath
$jlHealthUrl = "{0}/health" -f $jlBaseUrl

$reloadEnabled = $false
if ($env:JL_PLATFORM_RELOAD) {
    $reloadEnabled = @("1", "true", "yes", "on") -contains $env:JL_PLATFORM_RELOAD.Trim().ToLowerInvariant()
}

$openBrowser = $true
if ($env:JL_PLATFORM_OPEN_BROWSER) {
    $openBrowser = @("1", "true", "yes", "on") -contains $env:JL_PLATFORM_OPEN_BROWSER.Trim().ToLowerInvariant()
}

$launchMode = if ($env:JL_PLATFORM_LAUNCH_MODE) {
    [string]$env:JL_PLATFORM_LAUNCH_MODE
} else {
    "standalone"
}
$launchMode = $launchMode.Trim().ToLowerInvariant()
if ($launchMode -notin @("standalone", "browser")) {
    $launchMode = "standalone"
}

try {
    $startupTimeoutSeconds = [int]($env:JL_PLATFORM_STARTUP_TIMEOUT_SECONDS)
} catch {
    $startupTimeoutSeconds = 30
}
if ($startupTimeoutSeconds -lt 5) {
    $startupTimeoutSeconds = 5
}

function Get-ListeningProcessId {
    $conn = Get-NetTCPConnection -LocalAddress $jlHost -LocalPort $jlPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $conn) {
        return [string]$conn.OwningProcess
    }
    return ""
}

function Test-PlatformReady {
    try {
        $null = Invoke-WebRequest -Uri $jlHealthUrl -UseBasicParsing -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

function Get-StandaloneBrowserPath {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe")
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Open-PlatformUi {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    if (-not $openBrowser) {
        return
    }

    if ($launchMode -eq "standalone") {
        $browserPath = Get-StandaloneBrowserPath
        if ($browserPath) {
            Start-Process -FilePath $browserPath -ArgumentList "--app=$Url" | Out-Null
            return
        }
    }

    Start-Process $Url | Out-Null
}

$existingPid = Get-ListeningProcessId
if ($existingPid) {
    if (Test-PlatformReady) {
        Write-Host "[JL Command Deck] Reusing existing server on PID $existingPid."
        Write-Host "[JL Command Deck] Open $jlUiUrl"
        Open-PlatformUi -Url $jlUiUrl
        exit 0
    }

    Write-Host "[JL Command Deck] Stale listener detected on PID $existingPid. Cleaning up..."
    Stop-Process -Id $existingPid -Force -ErrorAction Stop
    Start-Sleep -Seconds 1

    $existingPid = Get-ListeningProcessId
    if ($existingPid) {
        Write-Host "[JL Command Deck] Port $jlPort still busy after cleanup (PID $existingPid)."
        exit 1
    }

    Write-Host "[JL Command Deck] Stale listener cleaned. Starting fresh server..."
}

Write-Host "[JL Command Deck] Starting API + Web UI..."
Write-Host "[JL Command Deck] Open $jlUiUrl"
if ($openBrowser) {
    Start-Job -ScriptBlock {
        param($healthUrl, $url, $timeoutSeconds, $preferredMode)

        function Get-StandaloneBrowserPath {
            $candidates = @(
                (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
                (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
                (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
                (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe")
            ) | Where-Object { $_ }

            foreach ($candidate in $candidates) {
                if (Test-Path $candidate) {
                    return $candidate
                }
            }
            return $null
        }

        $deadline = (Get-Date).AddSeconds([int]$timeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            try {
                $null = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
                if ($preferredMode -eq "standalone") {
                    $browserPath = Get-StandaloneBrowserPath
                    if ($browserPath) {
                        Start-Process -FilePath $browserPath -ArgumentList "--app=$url" | Out-Null
                        return
                    }
                }
                Start-Process $url | Out-Null
                return
            } catch {
                Start-Sleep -Milliseconds 500
            }
        }
    } -ArgumentList $jlHealthUrl, $jlUiUrl, $startupTimeoutSeconds, $launchMode | Out-Null
}

$uvicornArgs = @(
    "-m",
    "uvicorn",
    "jl_platform.services.api.main:app",
    "--host",
    $jlHost,
    "--port",
    [string]$jlPort
)
if ($reloadEnabled) {
    $uvicornArgs += "--reload"
}
if ($args.Count -gt 0) {
    $uvicornArgs += $args
}

python @uvicornArgs
exit $LASTEXITCODE
