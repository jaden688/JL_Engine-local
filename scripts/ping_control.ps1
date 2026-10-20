$body = "{}" | ConvertTo-Json
try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:3333/control" -Method Post -ContentType "application/json" -Body "{}"
    Write-Output $response
} catch {
    Write-Output "STATUS: $($_.Exception.Response.StatusCode.value__)"
    Write-Output "BODY: $($_.ErrorDetails.Message)"
}