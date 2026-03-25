$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptRoot
Set-Location $root

$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$launchLogPath = Join-Path $logDir ("command_deck_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$transcriptEnabled = $true
if ($env:JL_COMMAND_DECK_TRANSCRIPT) {
    $transcriptEnabled = @("1", "true", "yes", "on") -contains $env:JL_COMMAND_DECK_TRANSCRIPT.Trim().ToLowerInvariant()
}
$transcriptStarted = $false
if ($transcriptEnabled) {
    try {
        Start-Transcript -Path $launchLogPath -Append | Out-Null
        $transcriptStarted = $true
    } catch {
        Write-Host ("[JL Command Deck] Unable to start transcript at {0}: {1}" -f $launchLogPath, $_.Exception.Message)
    }
} else {
    Write-Host "[JL Command Deck] Transcript logging disabled by JL_COMMAND_DECK_TRANSCRIPT=0"
}

function Write-LaunchLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host "[JL Command Deck] $Message"
}

$unsafeToolsEnabled = $true
if ($env:JL_LOCAL_UNSAFE_TOOLS) {
    $unsafeToolsEnabled = @("1", "true", "yes", "on") -contains $env:JL_LOCAL_UNSAFE_TOOLS.Trim().ToLowerInvariant()
}
Write-Host ("[JL Command Deck] Unsafe tools: {0}" -f ($(if ($unsafeToolsEnabled) { "ON" } else { "OFF" })))

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

if ($transcriptEnabled) {
    Write-LaunchLog "Transcript logging enabled: $launchLogPath"
} else {
    Write-LaunchLog "Transcript logging disabled."
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
        Write-LaunchLog "Reusing existing server on PID $existingPid."
        Write-LaunchLog "Open $jlUiUrl"
        Open-PlatformUi -Url $jlUiUrl
        if ($transcriptStarted) {
            try {
                Stop-Transcript | Out-Null
            } catch {
            }
        }
        exit 0
    }

    Write-LaunchLog "Stale listener detected on PID $existingPid. Cleaning up..."
    Stop-Process -Id $existingPid -Force -ErrorAction Stop
    Start-Sleep -Seconds 1

    $existingPid = Get-ListeningProcessId
    if ($existingPid) {
        Write-LaunchLog "Port $jlPort still busy after cleanup (PID $existingPid)."
        if ($transcriptStarted) {
            try {
                Stop-Transcript | Out-Null
            } catch {
            }
        }
        exit 1
    }

    Write-LaunchLog "Stale listener cleaned. Starting fresh server..."
}

Write-LaunchLog "Starting API + Web UI..."
Write-LaunchLog "Open $jlUiUrl"
if ($openBrowser) {
    $browserHelper = Join-Path $root "tools\open_command_deck_browser.ps1"
    $browserLogPath = if ($transcriptEnabled) {
        Join-Path $logDir ("command_deck_browser_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    } else {
        ""
    }
    function Get-PowerShellExecutor {
        $candidates = @()

        $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
        if ($pwsh) { $candidates += $pwsh.Source }

        $winPs = Get-Command powershell -ErrorAction SilentlyContinue
        if ($winPs) { $candidates += $winPs.Source }

        foreach ($candidate in $candidates) {
            if (Test-Path $candidate) {
                return $candidate
            }
        }

        return $null
    }

    $executor = Get-PowerShellExecutor
    if (-not $executor) {
        Write-LaunchLog "Browser helper failed to start: neither pwsh nor powershell was found on PATH."
        if ($transcriptStarted) {
            try {
                Stop-Transcript | Out-Null
            } catch {
            }
        }
        exit 1
    }

    try {
        $browserArgs = @(
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $browserHelper,
            "-HealthUrl",
            $jlHealthUrl,
            "-Url",
            $jlUiUrl,
            "-TimeoutSeconds",
            [string]$startupTimeoutSeconds,
            "-LaunchMode",
            $launchMode
        )
        if ($browserLogPath) {
            $browserArgs += @("-LogPath", $browserLogPath)
        }
        Start-Process -FilePath $executor -WindowStyle Normal -ArgumentList $browserArgs | Out-Null
        if ($browserLogPath) {
            Write-LaunchLog "Browser helper window started. Log: $browserLogPath"
        } else {
            Write-LaunchLog "Browser helper window started."
        }
    } catch {
        Write-LaunchLog "Browser helper failed to start: $($_.Exception.Message)"
    }
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

$exitCode = 0
try {
    python @uvicornArgs
    $exitCode = $LASTEXITCODE
} finally {
    if ($transcriptStarted) {
        try {
            Stop-Transcript | Out-Null
        } catch {
        }
    }
}
exit $exitCode
