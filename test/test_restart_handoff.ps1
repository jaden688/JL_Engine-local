$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$helper = Join-Path $root 'scripts\restart_engine.ps1'
if (-not (Test-Path -LiteralPath $helper)) { throw 'Restart helper missing: replacement must wait for previous engine exit.' }
$julia = Join-Path $env:USERPROFILE '.julia\juliaup\julia-1.12.6+0.x64.w64.mingw32\bin\julia.exe'
$testDir = Join-Path $root 'tmp\restart-handoff-test'
New-Item -ItemType Directory -Force -Path $testDir | Out-Null
$marker = Join-Path $testDir 'replacement-started.txt'
Remove-Item -LiteralPath $marker -ErrorAction SilentlyContinue
$fixture = Join-Path $testDir 'replacement.jl'
[IO.File]::WriteAllText($fixture, 'write(ARGS[1], get(ENV, "SPARKBYTE_RESTART_TEST", "missing"))')
$env:SPARKBYTE_RESTART_TEST = 'inherited'
$parent = Start-Process powershell.exe -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 4') -PassThru
$job = Start-Job -ArgumentList $helper,$parent.Id,$julia,$root,$fixture,$marker -ScriptBlock {
    param($helper,$oldId,$julia,$root,$fixture,$marker)
    & $helper -PreviousProcessId $oldId -JuliaExe $julia -ProjectDir $root -ScriptPath $fixture -ScriptArgument $marker
}
Start-Sleep -Milliseconds 500
if (Test-Path -LiteralPath $marker) { throw 'Replacement started before old process exited.' }
Wait-Job $job -Timeout 45 | Out-Null
if ($job.State -ne 'Completed') { throw "Restart job did not finish: $($job.State)" }
Receive-Job $job -ErrorAction Stop
if ((Get-Content -LiteralPath $marker -Raw) -ne 'inherited') { throw 'Restart failed to inherit environment.' }
Remove-Job $job
'PASS: waited for prior process; launched exact Julia path; inherited environment; handled project paths with spaces.'
