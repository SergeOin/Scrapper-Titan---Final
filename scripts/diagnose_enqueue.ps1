$ErrorActionPreference = 'Stop'
param([string]$Base, [string]$Keywords)
if (-not $Base) { $Base = 'http://127.0.0.1:8001' }
if (-not $Keywords) { $Keywords = 'avocat' }
$headers = @{}
Write-Host "Enqueue relaxed job on $Base with keywords='$Keywords'" -ForegroundColor Yellow
$resp = Invoke-WebRequest -Uri ($Base + '/trigger?relaxed=1') -Method POST -UseBasicParsing -ContentType 'application/x-www-form-urlencoded' -Body ("keywords=$Keywords") -Headers $headers
Write-Host ("Status=" + $resp.StatusCode)
