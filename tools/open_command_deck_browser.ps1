param(
    [Parameter(Mandatory = $true)]
    [string]$HealthUrl,
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$TimeoutSeconds = 30,
    [ValidateSet("standalone", "browser")]
    [string]$LaunchMode = "standalone",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

function Write-BrowserLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host "[JL Command Deck Browser] $Message"
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

$transcriptStarted = $false
if ($LogPath) {
    $logDir = Split-Path -Parent $LogPath
    if ($logDir -and -not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    try {
        Start-Transcript -Path $LogPath -Append | Out-Null
        $transcriptStarted = $true
    } catch {
        Write-BrowserLog ("Unable to start transcript at {0}: {1}" -f $LogPath, $_.Exception.Message)
    }
}

$exitCode = 0
try {
    $deadline = (Get-Date).AddSeconds([int]$TimeoutSeconds)
    Write-BrowserLog "Waiting for $HealthUrl"

    $opened = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $null = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
            $opened = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $opened) {
        Write-BrowserLog "Timed out waiting for $HealthUrl after $TimeoutSeconds seconds."
        $exitCode = 1
        return
    }

    Write-BrowserLog "Health check passed."
    if ($LaunchMode -eq "standalone") {
        $browserPath = Get-StandaloneBrowserPath
        if ($browserPath) {
            Write-BrowserLog "Opening standalone browser at $Url"
            Start-Process -FilePath $browserPath -ArgumentList "--app=$Url" | Out-Null
            return
        }
    }

    Write-BrowserLog "Opening browser at $Url"
    Start-Process $Url | Out-Null
} catch {
    $exitCode = 1
    Write-BrowserLog "Browser helper failed: $($_.Exception.Message)"
} finally {
    if ($transcriptStarted) {
        try {
            Stop-Transcript | Out-Null
        } catch {
        }
    }
}

exit $exitCode
