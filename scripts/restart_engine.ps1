param(
    [Parameter(Mandatory=$true)][int]$PreviousProcessId,
    [Parameter(Mandatory=$true)][string]$JuliaExe,
    [Parameter(Mandatory=$true)][string]$ProjectDir,
    [Parameter(Mandatory=$true)][string]$ScriptPath,
    [string]$ScriptArgument = ''
)
$ErrorActionPreference = 'Stop'
# Wait on the specific existing process handle, never a PID polling loop.
$previous = Get-Process -Id $PreviousProcessId -ErrorAction SilentlyContinue
if ($null -ne $previous) {
    if (-not $previous.WaitForExit(60000)) {
        throw 'Previous engine did not exit within 60 seconds; replacement was not started.'
    }
}
Set-Location -LiteralPath $ProjectDir
$arguments = @("--project=$ProjectDir", $ScriptPath)
if ($ScriptArgument) { $arguments += $ScriptArgument }
& $JuliaExe @arguments
exit $LASTEXITCODE
