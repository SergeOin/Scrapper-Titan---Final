$ErrorActionPreference = 'Stop'
$exe = Join-Path (Join-Path 'dist' 'TitanScraper') 'TitanScraper.exe'
if(!(Test-Path $exe)){ throw "EXE not found: $exe" }
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 8
$srvInfo = Join-Path $env:LOCALAPPDATA 'TitanScraper\last_server.json'
if (Test-Path $srvInfo) {
  $data = Get-Content $srvInfo -Raw | ConvertFrom-Json
  $base = "http://$($data.host):$($data.port)"
} else {
  $base = "http://127.0.0.1:8000"
}
Write-Output "Base=$base"
# Build form body with a tiny keyword set to keep run short
$body = 'keywords=avocat'
try {
  $resp = Invoke-WebRequest -Uri "$base/trigger?sync=1" -Method POST -UseBasicParsing -ContentType 'application/x-www-form-urlencoded' -Body $body -TimeoutSec 180
  Write-Output ("InlineTriggerStatus=" + $resp.StatusCode)
  Write-Output ("InlineTriggerBody=" + $resp.Content)
} catch {
  Write-Output ("InlineTriggerErr=" + $_)
}
Try { Stop-Process -Id $p.Id -Force } Catch {}
