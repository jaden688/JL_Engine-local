[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $OpenCodeArgs
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$legacyCli = Join-Path $env:LOCALAPPDATA 'OpenCodeV1\node_modules\.bin\opencode.cmd'
$legacyConfig = Join-Path $env:USERPROFILE '.config\opencode\opencode-omo-v1.jsonc'

if (-not (Test-Path -LiteralPath $legacyCli)) {
    throw "OpenCode 1.19.0 side-by-side install is missing. Install it with: npm install --prefix `"$env:LOCALAPPDATA\OpenCodeV1`" opencode-ai@1.19.0"
}
if (-not (Test-Path -LiteralPath $legacyConfig)) {
    throw "OMO's OpenCode 1.x config is missing: $legacyConfig"
}

Set-Location -LiteralPath $repositoryRoot
$previousConfig = $env:OPENCODE_CONFIG
try {
    $env:OPENCODE_CONFIG = $legacyConfig
    $argsToPass = @($OpenCodeArgs)
    if ($argsToPass -notcontains '--port' -and $argsToPass -notcontains '-p') {
        if ($argsToPass.Count -eq 0 -or $argsToPass[0] -in @('--agent', '-a', '--model', '-m')) {
            $argsToPass = @('--port', '4097') + $argsToPass
        }
        elseif ($argsToPass[0] -in @('run', 'serve', 'web')) {
            $argsToPass = @($argsToPass[0], '--port', '4097') + @($argsToPass | Select-Object -Skip 1)
        }
    }
    & $legacyCli @argsToPass
    $exitCode = $LASTEXITCODE
}
finally {
    $env:OPENCODE_CONFIG = $previousConfig
}

exit $exitCode
