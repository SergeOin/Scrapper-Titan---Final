$exe = Join-Path $PSScriptRoot '..\dist\TitanScraper.exe'
if (!(Test-Path $exe)) { Write-Host "EXE not found: $exe" -ForegroundColor Red; exit 1 }
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 3
if ($p.HasExited) { Write-Host 'EXE exited unexpectedly' -ForegroundColor Red; exit 1 }
Write-Host "Started EXE PID $($p.Id)"
