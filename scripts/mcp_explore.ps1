$methods = @("getToolGroupPermissionModes", "getMcpServerSettings")

foreach ($method in $methods) {
    Write-Output "=== $method ==="
    $body = @{method=$method} | ConvertTo-Json
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:3333/control" -Method Post -ContentType "application/json" -Body $body
        Write-Output ($response | ConvertTo-Json -Depth 10)
    } catch {
        Write-Output "STATUS: $($_.Exception.Response.StatusCode.value__)"
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        Write-Output "BODY: $($reader.ReadToEnd())"
    }
    Write-Output ""
}