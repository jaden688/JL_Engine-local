# docker-push.ps1 — Build and push both images to Docker Hub
# Usage:
#   .\scripts\docker-push.ps1              # tag: latest
#   .\scripts\docker-push.ps1 -Tag v1.2.3  # tag: v1.2.3 + latest

param(
    [string]$Tag = "latest",
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path $PSScriptRoot -Parent

$ENGINE_IMAGE = "jaden688/jl-engine"
$MCP_IMAGE    = "jaden688/sparkbyte-mcp"

Write-Host "`n🐳  JL_Engine Docker Push" -ForegroundColor Cyan
Write-Host "   Engine : $ENGINE_IMAGE"
Write-Host "   MCP    : $MCP_IMAGE"
Write-Host "   Tag    : $Tag`n"

# ── Login check ───────────────────────────────────────────────────────────────
$whoami = docker info --format '{{.RegistryConfig.IndexConfigs}}' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker daemon not running or not logged in. Run: docker login"
    exit 1
}

# ── Build ─────────────────────────────────────────────────────────────────────
if (-not $NoBuild) {
    Write-Host "🔨  Building jl-engine..." -ForegroundColor Yellow
    docker build `
        --target runtime `
        -t "${ENGINE_IMAGE}:${Tag}" `
        -t "${ENGINE_IMAGE}:latest" `
        -f "$ROOT\Dockerfile" `
        $ROOT
    if ($LASTEXITCODE -ne 0) { Write-Error "Engine build failed"; exit 1 }

    Write-Host "`n🔨  Building sparkbyte-mcp..." -ForegroundColor Yellow
    docker build `
        -t "${MCP_IMAGE}:${Tag}" `
        -t "${MCP_IMAGE}:latest" `
        -f "$ROOT\mcp_server\Dockerfile" `
        $ROOT
    if ($LASTEXITCODE -ne 0) { Write-Error "MCP build failed"; exit 1 }
} else {
    Write-Host "⏭️   Skipping build (-NoBuild flag set)" -ForegroundColor DarkGray
}

# ── Push ──────────────────────────────────────────────────────────────────────
Write-Host "`n🚀  Pushing $ENGINE_IMAGE..." -ForegroundColor Green
docker push "${ENGINE_IMAGE}:${Tag}"
if ($Tag -ne "latest") { docker push "${ENGINE_IMAGE}:latest" }

Write-Host "`n🚀  Pushing $MCP_IMAGE..." -ForegroundColor Green
docker push "${MCP_IMAGE}:${Tag}"
if ($Tag -ne "latest") { docker push "${MCP_IMAGE}:latest" }

Write-Host "`n✅  Done!" -ForegroundColor Cyan
Write-Host "   https://hub.docker.com/r/jaden688/jl-engine"
Write-Host "   https://hub.docker.com/r/jaden688/sparkbyte-mcp`n"
