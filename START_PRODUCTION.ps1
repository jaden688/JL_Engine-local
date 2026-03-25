$unsafe = $false
$network = $false
$temporal = $false
$tqa = $false
$autoApprove = $false

$cognitiveModes = @("balanced", "high_fidelity", "pattern_tech", "compression", "expansion", "rebinding")
$cognitiveIdx = 0

$profiles = @("expressive", "safe_default", "chaos_coherence")
$profileIdx = 0

$selection = 0
$optionsCount = 8

while ($true) {
    Clear-Host
    Write-Host "===============================================================================" -ForegroundColor Green
    Write-Host "                    JL ENGINE: PRODUCTION LAUNCH MENU" -ForegroundColor Green
    Write-Host "===============================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host " Use UP/DOWN arrows to select, and SPACE or ENTER to toggle/cycle." -ForegroundColor DarkGray
    Write-Host ""
    
    $opt1 = if ($unsafe) { "[ON]  (Allows agents to edit files/run commands)" } else { "[OFF] (Sandbox mode - Text only, no system access)" }
    $opt2 = if ($network) { "[ON]  (Engine can scrape web and call external APIs)" } else { "[OFF] (Offline mode - Outbound connections blocked)" }
    $opt3 = if ($autoApprove) { "[ON]  (Executes tools instantly)" } else { "[OFF] (Requires Y/N confirmation for tools)" }
    $opt4 = if ($temporal) { "[ON]  (Background loop for emotional decay over time)" } else { "[OFF] (Stateless emotions - No organic cool-down)" }
    $opt5 = if ($tqa) { "[ON]  (Active background prediction of future states)" } else { "[OFF] (Passive mode - Engine sleeps between messages)" }
    
    $cog = $cognitiveModes[$cognitiveIdx]
    $opt6 = "[$cog]"
    
    $prof = $profiles[$profileIdx]
    $opt7 = "[$prof]"

    $displayOptions = @(
        " Physical Tool Use  : $opt1",
        " Network Access     : $opt2",
        " Auto-Approve Tools : $opt3",
        " Temporal Field     : $opt4",
        " TQA Predictive Loop: $opt5",
        " Cognitive Mode     : $opt6",
        " Engine Profile     : $opt7",
        " START ENGINE  (Launches PySide UI with selected environment)",
        " QUIT"
    )

    for ($i = 0; $i -lt $displayOptions.Count; $i++) {
        if ($i -eq 7) {
            Write-Host "-------------------------------------------------------------------------------" -ForegroundColor DarkGray
        }
        
        $text = $displayOptions[$i]
        if ($i -eq $selection) {
            Write-Host "  > $text " -ForegroundColor Black -BackgroundColor Cyan
        } else {
            Write-Host "    $text "
        }
    }

    $keyInfo = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    $keyCode = $keyInfo.VirtualKeyCode

    if ($keyCode -eq 38) { # Up Arrow
        $selection = ($selection - 1 + $displayOptions.Count) % $displayOptions.Count
    } elseif ($keyCode -eq 40) { # Down Arrow
        $selection = ($selection + 1) % $displayOptions.Count
    } elseif ($keyCode -eq 13 -or $keyCode -eq 32 -or $keyCode -eq 39) { # Enter, Space, Right Arrow
        if ($selection -eq 0) { $unsafe = -not $unsafe }
        elseif ($selection -eq 1) { $network = -not $network }
        elseif ($selection -eq 2) { $autoApprove = -not $autoApprove }
        elseif ($selection -eq 3) { $temporal = -not $temporal }
        elseif ($selection -eq 4) { $tqa = -not $tqa }
        elseif ($selection -eq 5) { $cognitiveIdx = ($cognitiveIdx + 1) % $cognitiveModes.Count }
        elseif ($selection -eq 6) { $profileIdx = ($profileIdx + 1) % $profiles.Count }
        elseif ($selection -eq 7) { break }
        elseif ($selection -eq 8) { exit 0 }
    }
}

Clear-Host
Write-Host "[SYSTEM] Booting up JL Engine..." -ForegroundColor Green
Write-Host "[SYSTEM] Auto-Approve is $(if($autoApprove){'ON'}else{'OFF'})." -ForegroundColor Green
Write-Host "[SYSTEM] Direct Action Fallback is ON." -ForegroundColor Green
Write-Host "[SYSTEM] Core Rules Injected." -ForegroundColor Green
Write-Host "`nLaunching the Mothership..." -ForegroundColor Cyan

$env:JL_LOCAL_UNSAFE_TOOLS = if ($unsafe) { "1" } else { "0" }
$env:JL_PLATFORM_ALLOW_NETWORK = if ($network) { "1" } else { "0" }
$env:JL_ENGINE_CLI_AUTO_APPROVE = if ($autoApprove) { "1" } else { "0" }
$env:JL_TEMPORAL_FIELD = if ($temporal) { "1" } else { "0" }
$env:JL_TQA_INTERNAL_LOOP = if ($tqa) { "1" } else { "0" }
$env:JL_STARTUP_COGNITIVE_MODE = $cognitiveModes[$cognitiveIdx]
$env:JL_STARTUP_PROFILE = $profiles[$profileIdx]

$env:JL_INTERPRETER_ALLOW_DIRECT_ACTION_FALLBACK = "1"
$env:JL_COMMAND_DECK_TRANSCRIPT = "1"

# Combine script path with src path for PYTHONPATH
$env:PYTHONPATH = "$PSScriptRoot;$PSScriptRoot\src;$env:PYTHONPATH"

# Run python module
& python -m ui.pyside_ui

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[ERROR] The engine crashed." -ForegroundColor Red
    pause
}
