# Quick smoke: SparkByte UI health, A2A health + agent card.
# Usage: .\scripts\smoke_endpoints.ps1
# Optional: $env:SPARKBYTE_BASE='http://127.0.0.1:8081' $env:A2A_BASE='http://127.0.0.1:8082'

$ErrorActionPreference = 'Stop'
$sb = if ($env:SPARKBYTE_BASE) { $env:SPARKBYTE_BASE } else { 'http://127.0.0.1:8081' }
$a2a = if ($env:A2A_BASE) { $env:A2A_BASE } else { 'http://127.0.0.1:8082' }

Write-Host "SparkByte GET $sb/health"
Invoke-RestMethod -Uri "$sb/health" -Method Get | ConvertTo-Json -Compress

Write-Host "`nA2A GET $a2a/health"
Invoke-RestMethod -Uri "$a2a/health" -Method Get | ConvertTo-Json -Compress

Write-Host "`nA2A agent card (first 400 chars):"
$r = Invoke-WebRequest -Uri "$a2a/.well-known/agent.json" -UseBasicParsing
$txt = $r.Content
if ($txt.Length -gt 400) { $txt = $txt.Substring(0, 400) + '...' }
Write-Host $txt

Write-Host "`nOK: Endpoints responded."
