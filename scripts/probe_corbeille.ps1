param()

function Get-LastServerInfo {
  try {
    $jsonPath = Join-Path $Env:LOCALAPPDATA 'TitanScraper\last_server.json'
    if (Test-Path -LiteralPath $jsonPath) {
      $raw = Get-Content -LiteralPath $jsonPath -Raw -ErrorAction Stop
      return $raw | ConvertFrom-Json -ErrorAction Stop
    }
  } catch {}
  return $null
}

$ErrorActionPreference = "Stop"
$hostName = '127.0.0.1'
$last = Get-LastServerInfo
$ports = @()
if ($last -and $last.port) { $ports += [int]$last.port }
$ports += 8000,8001,8002,8003,8004 | Select-Object -Unique

foreach ($port in $ports) {
  $Url = "http://$($hostName):$port/corbeille"
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -Headers @{Accept='text/html'} -TimeoutSec 5
    Write-Host "OK $Url -> $($r.StatusCode)" -ForegroundColor Green
    if ($r.StatusCode -ne 200) {
      Write-Host "Body:"; Write-Output $r.Content
    }
    exit 0
  } catch {
    $ex = $_.Exception
    if ($ex.Response) {
      try { $status = $ex.Response.StatusCode.value__ } catch { $status = "" }
      Write-Host "ERR $Url -> $status" -ForegroundColor Yellow
      try {
        $reader = New-Object System.IO.StreamReader($ex.Response.GetResponseStream())
        $body = $reader.ReadToEnd()
        Write-Host "Body:"; Write-Output $body
      } catch {}
      if ($status -eq 500) { exit 2 }
    } else {
      Write-Host "ERR $Url -> connection failed" -ForegroundColor Yellow
    }
  }
}

Write-Host "No reachable server on candidate ports: $($ports -join ',')" -ForegroundColor Red
exit 1