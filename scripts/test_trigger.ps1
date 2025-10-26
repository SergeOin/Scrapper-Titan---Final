$ErrorActionPreference = 'Stop'
$exe = Join-Path (Join-Path 'dist' 'TitanScraper') 'TitanScraper.exe'
if(!(Test-Path $exe)){ throw "EXE not found: $exe" }
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 6
$srvInfo = Join-Path $env:LOCALAPPDATA 'TitanScraper\last_server.json'
if (Test-Path $srvInfo) {
  $data = Get-Content $srvInfo -Raw | ConvertFrom-Json
  $base = "http://$($data.host):$($data.port)"
} else {
  $base = "http://127.0.0.1:8000"
}
Write-Output "Base=$base"
try {
  Invoke-WebRequest -Uri "$base/trigger?sync=1" -Method POST -UseBasicParsing -TimeoutSec 120 | Out-Null
  Write-Output 'Trigger=OK'
} catch {
  Write-Output ("TriggerErr=" + $_)
}
Try { Stop-Process -Id $p.Id -Force } Catch {}
