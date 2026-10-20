$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$tunnelClient = Join-Path $projectRoot "tools\tunnel-client\tunnel-client.exe"
$mcpServer = Join-Path $projectRoot "mcp_server\server.py"
$runtimeKey = [Environment]::GetEnvironmentVariable("CONTROL_PLANE_API_KEY", "User")

if ([string]::IsNullOrWhiteSpace($runtimeKey)) {
    throw "CONTROL_PLANE_API_KEY is not stored in the current user's environment."
}

$env:CONTROL_PLANE_API_KEY = $runtimeKey

if (-not (Test-Path $mcpServer)) {
    throw "SparkByte MCP server was not found at $mcpServer."
}

& $tunnelClient run `
    --profile-dir "$env:APPDATA\tunnel-client" `
    --profile sparkbyte

if ($LASTEXITCODE -ne 0) {
    throw "SparkByte tunnel startup failed with exit code $LASTEXITCODE."
}
